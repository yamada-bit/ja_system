import logging
import uuid

from django.contrib import messages
from django.db import IntegrityError, transaction
from django.shortcuts import redirect

from core.models import ConsumedFormToken

logger = logging.getLogger(__name__)

SESSION_KEY = "double_submit_tokens"


def issue_token(session, form_id):
    """二重送信対策トークンを発行しセッションに記録する。フォーム表示のたびに呼ぶ。

    既知の制約（未実装・低優先度）: 発行したトークンが一度も`consume_token`されないまま
    （フォームを開いたまま離脱する、複数の設定画面を渡り歩く等）セッションが続くと、
    `tokens`辞書に`form_id`ごとのエントリが溜まり続ける。`form_id`の種類数は画面数に比例した
    小さな有限集合であり、同じ`form_id`を再訪すれば上書きされる（本関数内`tokens[form_id] = token`）
    ため実害は乏しいが、自動的な期限切れ・掃除の仕組みは無い。セッション自体がDjangoのSESSION_COOKIE_AGE等で
    最終的に失効するため、無限に肥大化するわけではない点も踏まえ現状は許容している。
    """
    token = uuid.uuid4().hex
    tokens = session.setdefault(SESSION_KEY, {})
    tokens[form_id] = token
    session.modified = True
    return token


def consume_token(session, form_id, submitted_token):
    """POST時にトークンを検証し、成功したら即座に無効化する（同じトークンでの再送信＝ブラウザの
    戻る+再送信や二度押しを弾く）。検証失敗時はFalseを返すのみで例外は投げない
    （呼び出し側でユーザーにわかるエラーメッセージを出す）。

    セッション辞書との比較（下記`expected != submitted_token`）だけでは、同一セッションから
    同一フォームへの同時並行リクエスト（2タブでの同時送信、1タブでの多重クリックがネットワーク
    層でほぼ同時に2リクエストとして届く場合等）が両方とも「トークンはまだ有効」と判定しうる
    （Djangoのセッション読み書きはリクエスト単位でアトミックではないため。典型的なTOCTOU）。
    ユーザー報告（2026-09-28、保管画面２「登録」ボタン連打で500エラー）により実際に発生することが
    判明したため、実際に処理を継続してよいリクエストを1つに絞る「消費」の部分を
    `core.models.ConsumedFormToken`（token列にユニーク制約）へのINSERTに置き換えた。
    2つのリクエストが両方とも上のセッション比較を通過しても、実際にINSERTへ成功できるのは
    どちらか一方だけに限定される（DBのユニーク制約はプロセス・スレッドをまたいでDB自体が
    保証するため、セッションバックエンドの種類に依存しない）。詳細経緯は
    `docs/HTML_REIMPL_CHECKLIST_ARCHIVE.md`参照。
    """
    tokens = session.get(SESSION_KEY, {})
    expected = tokens.get(form_id)
    if not expected or expected != submitted_token:
        logger.warning("二重送信を検知またはトークン不正: form_id=%s", form_id)
        return False
    try:
        with transaction.atomic():
            ConsumedFormToken.objects.create(token=submitted_token, form_id=form_id)
    except IntegrityError:
        # 上のセッション比較は通過したが、ほぼ同時に届いた別リクエストが先にこのtokenを
        # 消費済み（INSERT成功）にしていた場合。DBのユニーク制約違反として確実に検知できる。
        logger.warning("二重送信を検知（DB側で消費済み・TOCTOU対策）: form_id=%s", form_id)
        return False
    del tokens[form_id]
    session.modified = True
    return True


def reject_if_resubmitted(request, form_id, redirect_to, *redirect_args, **redirect_kwargs):
    """POST冒頭での「トークン検証→失敗ならmessages.error+redirect」という定型パターンの共通処理。

    organizations/masters系の登録・編集・削除ビューで同一の4行パターンが11箇所重複していた
    ため集約した（コード監査で発見、2026-08-25修正）。戻り値がNoneでなければ呼び出し元は
    それをそのままreturnする（`if (resp := reject_if_resubmitted(...)) is not None: return resp`）。
    `redirect_to`以降は`django.shortcuts.redirect`にそのまま渡すため、pk付きURL等
    （`redirect_to="masters:class_edit", pk=pk`）にも対応する。
    """
    submitted_token = request.POST.get("token", "")
    if consume_token(session=request.session, form_id=form_id, submitted_token=submitted_token):
        return None
    messages.error(request, "二重に送信された可能性があるため処理を中断しました。もう一度やり直してください。")
    return redirect(redirect_to, *redirect_args, **redirect_kwargs)
