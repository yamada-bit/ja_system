import logging

from django.http import Http404

logger = logging.getLogger(__name__)


def scoped_get_object_or_404(
    base_qs, employee, pk, *, dept_ids_resolver, entity_name, scope_queryset=None, on_denied=None
):
    """部署スコープ外のpkへのURL直打ちを404にしつつ、セキュリティ上意味のある事象として
    logger.warningに残す共通ヘルパー。documents.services.scoped_get_object_or_404/
    contracts.services.scoped_get_object_or_404（部署ID解決関数・ログ文言・エンティティ名のみ
    差異）、masters.services.scoped_get_object_or_404（NULL許容の絞り込み方式・英語モデル名の
    ログという2点の差異）が同一アルゴリズムのまま重複実装されていたため集約した
    （can_delete/deletion_denial_message/build_zip_archiveと同じ経緯。品質レビューで発見、
    2026-08-25修正）。

    `dept_ids_resolver`はemployeeから許可部署ID集合（管理者等で無制限ならNone）を返す関数
    （documents.services.document_searchable_department_ids/permissions.services.
    contract_searchable_department_ids/masters.services.department_scope_idsを渡す）。
    `entity_name`はログ文言の「文書」「契約書」「分類」等の出し分けにのみ使う。`scope_queryset`は
    `(qs, dept_ids) -> qs`のクエリセット絞り込み関数（省略時は`department_id__in=dept_ids`の
    厳密フィルタ）。masters.Group/Categoryのように部署未設定(NULL)の行も許容する場合は
    masters.services.scope_queryset_by_departmentを渡す。存在自体しないpkとの区別のため、
    スコープ無しでの存在確認を1回追加で行っている。

    `on_denied`は「pkは存在するが部署スコープ外」＝URL直打ちアクセス試行を検出したときに
    logger.warningに加えて呼ぶ引数無しコールバック。documents/contractsは操作履歴ログ（audit）
    にも残したいのでこれを渡す。masters（分類・カテゴリー）側は管理者用画面で監査価値が相対的に
    低いため渡さず、従来どおりwarningのみに留める（review_rule_doc_contract.txt No.1、2026-09-09
    ユーザー確定）。
    """
    dept_ids = dept_ids_resolver(employee)
    if scope_queryset is not None:
        qs = scope_queryset(base_qs, dept_ids)
    else:
        qs = base_qs if dept_ids is None else base_qs.filter(department_id__in=dept_ids)
    obj = qs.filter(pk=pk).first()
    if obj is not None:
        return obj
    if base_qs.filter(pk=pk).exists():
        logger.warning(
            "部署スコープ外の%sへのアクセスを試行しました: employee_no=%s pk=%s",
            entity_name,
            employee.employee_no,
            pk,
        )
        if on_denied is not None:
            on_denied()
    raise Http404(f"No {base_qs.model._meta.object_name} matches the given query.")
