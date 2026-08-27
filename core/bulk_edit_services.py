"""検索結果一覧「一括編集」用のセッション状態ヘルパー。

`core.upload_services.get_pending_files`/`clear_pending_files`と同じ最小主義パターンで、
セッションキー文字列は呼び出し元のアプリ（documents/contracts）が渡す。保持するのは
「編集対象pkの並び順」と「現在どこまで進んだか」だけで、フォームの入力値そのものは
持たない（各ステップの送信ごとにDBへ直接保存する save-as-you-go 方式のため）。
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
    return [pk for pk in valid_pks if pk in existing_pks]


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


def remove_bulk_edit_pk(session, session_key, pk):
    """一括編集ウィザードの巡回中に、表示中の1件を対象から外して次へ進む
    （保管画面２〈edit.html〉の削除ボタンから、対象レコードを論理削除した直後に呼ぶ。
    2026-08-27ユーザー確定：一括編集中の削除は「その1件を対象から外して次のレコードへ進む」）。

    `state["pks"]` から `pk` を除去し、`index` を新しい長さの範囲内へ収める（除去位置が
    現在位置より前なら1つ前へずらし、末尾を削除した場合は最後の要素を指すよう詰める）。
    対象が0件になったら `clear_bulk_edit_state` して `None` を返す。stateが無い場合も `None`。
    それ以外は更新後のstate（dict）を返す。
    """
    state = session.get(session_key)
    if state is None or pk not in state["pks"]:
        return None

    removed_at = state["pks"].index(pk)
    state["pks"].remove(pk)
    if not state["pks"]:
        clear_bulk_edit_state(session, session_key)
        return None

    index = state["index"]
    # 除去したのが現在位置より前なら、見かけ上の並びを保つため index を1つ詰める。
    # 現在位置そのもの／後ろを除去した場合は index を動かさず、末尾を超えたらクランプする
    # （＝現在位置の要素を消したときは「次のレコード」が繰り上がって同じ index に来る）。
    if removed_at < index:
        index -= 1
    index = min(index, len(state["pks"]) - 1)
    state["index"] = index
    session[session_key] = state
    session.modified = True
    return state


def clear_bulk_edit_state(session, session_key):
    session.pop(session_key, None)
