import logging
import uuid

from django.contrib import messages
from django.shortcuts import redirect

logger = logging.getLogger(__name__)

SESSION_KEY = "double_submit_tokens"


def issue_token(session, form_id):
    """二重送信対策トークンを発行しセッションに記録する。フォーム表示のたびに呼ぶ。

    既知の制約（未実装・低優先度）: 発行したトークンが一度も`consume_token`されないまま
    （フォームを開いたまま離脱する、複数の設定画面を渡り歩く等）セッションが続くと、
    `tokens`辞書に`form_id`ごとのエントリが溜まり続ける。`form_id`の種類数は画面数に比例した
    小さな有限集合であり、同じ`form_id`を再訪すれば上書きされる（13行目）ため実害は乏しいが、
    自動的な期限切れ・掃除の仕組みは無い。セッション自体がDjangoのSESSION_COOKIE_AGE等で
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

    既知の制約（未対応・低優先度）: 同一セッションから同一フォームへの同時並行リクエスト
    （例: 同じ画面を2タブで開いて起こる稀なケース、あるいは1タブでの多重クリックが
    ネットワーク層でほぼ同時に2リクエストとして届く場合）は、Djangoのセッション読み書きが
    リクエスト単位でアトミックではないため、理論上は両方が同じトークンの検証を通過しうる
    （典型的なTOCTOU）。本アプリのセッションバックエンド・アクセスパターン上、実害は小さいと
    判断し現状は対策していないが、将来的にDB行ロック（`select_for_update`）等でセッションを
    扱うようになった場合はこの前提を見直すこと。
    """
    tokens = session.get(SESSION_KEY, {})
    expected = tokens.get(form_id)
    if not expected or expected != submitted_token:
        logger.warning("二重送信を検知またはトークン不正: form_id=%s", form_id)
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
