import logging

from django.http import Http404

logger = logging.getLogger(__name__)


def scoped_get_object_or_404(base_qs, employee, pk, *, dept_ids_resolver, entity_name):
    """文書/契約書の詳細操作（ダウンロード・プレビュー・編集・削除・一括編集）で、部署スコープ
    外のpkへのURL直打ちを404にしつつ、セキュリティ上意味のある事象としてlogger.warningに残す
    共通ヘルパー。documents.services.scoped_get_object_or_404/contracts.services.
    scoped_get_object_or_404が部署ID解決関数・ログ文言・エンティティ名以外完全に同一実装のまま
    重複していたため集約した（can_delete/deletion_denial_message/build_zip_archiveと同じ経緯。
    品質レビューで発見、2026-08-25修正）。

    `dept_ids_resolver`はemployeeから許可部署ID集合（管理者等で無制限ならNone）を返す関数
    （documents.services.document_searchable_department_ids/permissions.services.
    contract_searchable_department_idsを渡す）。`entity_name`はログ文言の「文書」「契約書」の
    出し分けにのみ使う。存在自体しないpkとの区別のため、スコープ無しでの存在確認を1回追加で
    行っている。
    """
    dept_ids = dept_ids_resolver(employee)
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
    raise Http404(f"No {base_qs.model._meta.object_name} matches the given query.")
