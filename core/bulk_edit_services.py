"""検索結果一覧「一括編集」用のセッション状態ヘルパー。

`core.upload_services.get_pending_files`/`clear_pending_files`と同じ最小主義パターンで、
セッションキー文字列は呼び出し元のアプリ（documents/contracts）が渡す。保持するのは
「編集対象pkの並び順」と「現在どこまで進んだか」だけで、フォームの入力値そのものは
持たない（各ステップの送信ごとにDBへ直接保存する save-as-you-go 方式のため）。
"""


def start_bulk_edit(session, session_key, pks):
    """一括編集ウィザードを開始し、対象pkの並び順と先頭位置をセッションに保存する。"""
    session[session_key] = {"pks": pks, "index": 0}


def get_bulk_edit_state(session, session_key):
    """`{"pks": [...], "index": int}`、未開始または期限切れの場合はNone。"""
    return session.get(session_key)


def set_bulk_edit_index(session, session_key, index):
    """現在位置だけを更新する。stateが無い（セッション切れ等）場合は何もしない。"""
    state = session.get(session_key)
    if state is not None:
        state["index"] = index
        session[session_key] = state


def clear_bulk_edit_state(session, session_key):
    session.pop(session_key, None)
