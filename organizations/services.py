import json
import logging

from organizations.models import Department, DepartmentViewScope

logger = logging.getLogger(__name__)


def apply_dept_action(department, action, targets):
    """screen-dept-editの「部署統合・分割」実行（xlsx 部署管理!B209-212(Rev1.1)）。

    `department`は編集対象（統合の場合は存続する部署、分割の場合は分割元の部署）、`targets`は
    ポップアップで選択した対象部署のQuerySet/リスト。方向の解釈はorganizations.models.
    DepartmentViewScopeのdocstring参照。既に同じ組み合わせが存在する場合は何もしない
    （UniqueConstraintがあるためget_or_createで冪等にする）。
    """
    if action == DepartmentViewScope.ACTION_MERGE:
        for target in targets:
            DepartmentViewScope.objects.get_or_create(
                viewer_department=department, visible_department=target,
                defaults={"action": DepartmentViewScope.ACTION_MERGE},
            )
            logger.info(
                "部署統合による閲覧部署範囲を追加しました: viewer=%s visible=%s", department, target
            )
    elif action == DepartmentViewScope.ACTION_SPLIT:
        for target in targets:
            DepartmentViewScope.objects.get_or_create(
                viewer_department=target, visible_department=department,
                defaults={"action": DepartmentViewScope.ACTION_SPLIT},
            )
            logger.info(
                "部署分割による閲覧部署範囲を追加しました: viewer=%s visible=%s", target, department
            )


def visible_department_ids(employee):
    """employeeの自部署に加え、閲覧部署範囲テーブルで追加された部署のID一覧を返す
    （xlsx 検索・閲覧・変更!B48,417-418(Rev1.1)「閲覧部署範囲テーブルを参照し...自動セットする」。
    documents/contracts.search_servicesの非管理者向け部署フィルタ、およびSearchFormの
    初期表示値の両方で使う）。
    """
    ids = [employee.department_id]
    ids.extend(
        DepartmentViewScope.objects.filter(viewer_department_id=employee.department_id).values_list(
            "visible_department_id", flat=True
        )
    )
    return ids


def departments_json():
    """本支所→部課の連動プルダウン用データ（テンプレートのJSでフィルタする）。
    accounts（職員マスタ登録・編集・一覧検索）とorganizations（部署管理一覧検索）の両方で
    同じ連動プルダウンJSを使うため、Department自体が属するこのモジュールに集約する。
    """
    return json.dumps(
        [
            {
                "id": d.pk,
                "branch_code": d.branch_code,
                "branch_name": d.branch_name,
                "section_code": d.section_code,
                "section_name": d.section_name,
            }
            for d in Department.objects.order_by("branch_code", "section_code")
        ]
    )
