"""検索結果一覧「一括編集」用のセッション状態ヘルパー。

`core.upload_services.get_pending_files`/`clear_pending_files`と同じ最小主義パターンで、
セッションキー文字列は呼び出し元のアプリ（documents/contracts）が渡す。

2026-08-28ユーザー確定で「更新」ボタン押下まで一切DBへ反映しない**ステージング型**に変更した
（それ以前は各ステップの送信ごとにDBへ直接保存する save-as-you-go 方式だった。詳細は
HTML_REIMPL_CHECKLIST_ARCHIVE.md「一括編集を全ページ一括確定モデルへ改修」節参照）。
セッションに保持するのは全てJSON直列化可能な値のみ:

    session[<app>_bulk_edit] = {
        "pks": [int, ...],           # 編集対象の並び順
        "index": int,                # 現在表示中のページ位置
        "staged": {"<pk>": {<フォームフィールド名>: "<生値>"}},  # 入力欄に触れたページ
        "to_delete": [int, ...],     # 「削除」ボタンでマークされた削除予定pk
        "staged_related": {"<pk>": {"related_ids": [int, ...]}},  # 関連書類を編集したページ
    }

`staged` のキーは `str(pk)`（Djangoのセッションは既定でJSONシリアライズし、dictの整数キーは
文字列化されるため、最初から文字列で統一する）。`staged_related` は契約書の関連書類専用で、
Rev1.6で「紐付け先契約書pkの全量リスト」だけを持つ（Rev1.5までは物理ファイルを tmp_uploads/ に
退避していたが、関連書類が既存契約書への参照になったためファイルI/Oは消えた）。
"""

import logging

logger = logging.getLogger(__name__)


def resolve_ordered_pks(raw_pks, *, model, dept_ids_resolver, employee):
    """screen-search「一括編集」開始時（documents/contracts.views.BulkEditStartView.post）に、
    POSTされたpks（文字列リスト）を検証・部署スコープで絞り込んだ上で、選択順を保った有効な
    pk一覧を返す。documents.views.BulkEditStartView.post/contracts.views.BulkEditStartView.postが
    ほぼ同一実装のまま重複していたため集約した（品質レビューで発見、2026-08-25修正）。

    pksはURLパスコンバータを経由しない生のPOST値のため、改ざんや誤ったリンク等で数値以外が
    混入し得る。無効な値は除外しつつ、不正アクセス試行の兆候として警告ログに残す
    （BulkDownloadViewと同じ理由）。セキュリティレビューで発見：部署スコープ外のpkも
    「存在しない」ものとして静かに除外する（scoped_get_object_or_404 docstring参照。除外せずに
    セッションへ積むと、BulkEditView側で結局404になるだけだが「選択した覚えのない他部署の対象」
    がウィザードの巡回対象に紛れ込む点で挙動が一貫しない。2026-08-25修正）。

    `dept_ids_resolver`はemployeeから許可部署ID集合（Noneなら無制限）を返す関数
    （documents.services.document_searchable_department_ids/permissions.services.
    contract_searchable_department_idsを渡す）。
    """
    valid_pks = []
    for p in raw_pks:
        try:
            valid_pks.append(int(p))
        except (TypeError, ValueError):
            logger.warning(
                "一括編集の選択値(pks)に不正な値が含まれていたため除外しました: "
                "employee_no=%s value=%r",
                employee.employee_no,
                p,
            )

    allowed_department_ids = dept_ids_resolver(employee)
    candidates = model.objects.filter(pk__in=valid_pks, is_deleted=False)
    if allowed_department_ids is not None:
        candidates = candidates.filter(department_id__in=allowed_department_ids)
    existing_pks = set(candidates.values_list("pk", flat=True))
    # 改ざんで同じ pk が複数回 POST されても1回だけ扱う（dict.fromkeys で順序保持 dedupe）。
    # dedupe しないと BulkEditView の確定ループが同一レコードを2回削除扱いし、削除監査ログが
    # 重複する（コードレビュー audit/core No.3）。
    return [pk for pk in dict.fromkeys(valid_pks) if pk in existing_pks]


def start_bulk_edit(session, session_key, pks):
    """一括編集ウィザードを開始し、対象pkの並び順・先頭位置と空のステージ領域をセッションに保存する。"""
    session[session_key] = {
        "pks": pks,
        "index": 0,
        "staged": {},
        "to_delete": [],
        "staged_related": {},
    }
    session.modified = True


def get_bulk_edit_state(session, session_key):
    """stateのdict、未開始または期限切れの場合はNone。古い形式（staged等が無い）を読んでも
    落ちないよう、参照側は`state.get("staged", {})`のように防御的に扱う。"""
    return session.get(session_key)


def set_bulk_edit_index(session, session_key, index):
    """現在位置だけを更新する。stateが無い（セッション切れ等）場合は何もしない。"""
    state = session.get(session_key)
    if state is not None:
        state["index"] = index
        session[session_key] = state
        session.modified = True


def stage_page(session, session_key, pk, form_values):
    """ページ移動・トグル・更新の各POSTで、表示中ページのフォーム生値（str→str のdict）を
    セッションへ退避する。`form_values`は呼び出し側（view）がアプリ別のフィールド名リストで
    `{k: request.POST.get(k) for k in ...}` として組み立てて渡す。"""
    state = session.get(session_key)
    if state is None:
        return
    state.setdefault("staged", {})[str(pk)] = form_values
    session[session_key] = state
    session.modified = True


def staged_page_data(state, pk):
    """`state`にステージ済みの生値dictがあれば返す、無ければNone。"""
    if not state:
        return None
    return state.get("staged", {}).get(str(pk))


def toggle_delete_mark(session, session_key, pk):
    """「削除」/「削除取消」ボタン。`to_delete`にpkを入れる/外す。戻り値は操作後に「削除予定か」。"""
    state = session.get(session_key)
    if state is None:
        return False
    to_delete = state.setdefault("to_delete", [])
    if pk in to_delete:
        to_delete.remove(pk)
        now_marked = False
    else:
        to_delete.append(pk)
        now_marked = True
    session[session_key] = state
    session.modified = True
    return now_marked


def is_marked_for_delete(state, pk):
    return bool(state) and pk in state.get("to_delete", [])


def stage_related_ids(session, session_key, pk, related_ids):
    """契約書の関連書類（紐付け先契約書pkの並び）をステージする。`related_ids`はそのページで
    最終的に紐付けたい契約書pkの全量リスト（差分ではない）。ページを送信するたびに丸ごと
    上書きする（Rev1.6：ポップアップ検索で選び直した結果をそのまま反映する方式）。"""
    state = session.get(session_key)
    if state is None:
        return
    state.setdefault("staged_related", {})[str(pk)] = {"related_ids": list(related_ids)}
    session[session_key] = state
    session.modified = True


def staged_related_ids_for(state, pk):
    """そのページでステージ済みの紐付け先契約書pkリスト、無ければ `None`（＝未編集＝現状維持）。"""
    if not state:
        return None
    bucket = state.get("staged_related", {}).get(str(pk))
    # bucket.get(...) で参照する（bucket["related_ids"] だと、旧形式セッションがデプロイ跨ぎで
    # 残った場合に KeyError。本番未リリースで現状は旧形式は存在しないが、リリース済み環境への
    # 適用時の申し送りを消すための無害化。コードレビュー audit/core No.7）。
    return bucket.get("related_ids", []) if bucket else None


def discard_bulk_edit(session, session_key):
    """「キャンセル」ボタン。stateを破棄する（Rev1.6で関連書類の一時ファイルが無くなったため
    掃除処理は不要になった）。"""
    clear_bulk_edit_state(session, session_key)


def clear_bulk_edit_state(session, session_key):
    session.pop(session_key, None)
    session.modified = True
