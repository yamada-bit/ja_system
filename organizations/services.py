import json
import logging

from organizations.models import RETIRED_SECTION_CODE, Department, DepartmentViewScope

logger = logging.getLogger(__name__)


def apply_dept_action(department, action, targets):
    """screen-dept-editの「部署統合・分割」実行（xlsx 部署管理!B209-212(Rev1.1)）。

    `department`は編集対象（統合の場合は存続する部署、分割の場合は分割元の部署）、`targets`は
    ポップアップで選択した対象部署のQuerySet/リスト。方向の解釈はorganizations.models.
    DepartmentViewScopeのdocstring参照。

    以前はmerge/split別々のブロックでget_or_createを使っており、既に同じ(viewer, visible)組が
    一方のactionで作成済みの場合、後からもう一方のactionで実行してもdefaultsが適用されず
    actionフィールドが古い値のまま残る不具合があった（呼び出し元のviews.pyでは実行した
    action名で監査ログを記録するため、DB上のactionと監査ログの内容が食い違っていた）。
    update_or_createでactionを常に最新の実行内容に更新するよう修正した
    （コード監査で発見、2026-08-24修正）。
    """
    for target in targets:
        if target.pk == department.pk:
            # DeptEditForm.clean()が既に自己参照をエラーにしているため通常は到達しないが、
            # 将来フォームを経由しない呼び出し元が増えた場合の防御（コード監査で発見、
            # 2026-08-24追加）。
            logger.warning("部署統合・分割で自部署が対象に含まれていたためスキップしました: department=%s", department)
            continue
        if action == DepartmentViewScope.ACTION_MERGE:
            viewer, visible, label = department, target, "統合"
        else:
            viewer, visible, label = target, department, "分割"
        DepartmentViewScope.objects.update_or_create(
            viewer_department=viewer, visible_department=visible, defaults={"action": action},
        )
        logger.info("部署%sによる閲覧部署範囲を追加しました: viewer=%s visible=%s", label, viewer, visible)


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


def branch_choices():
    """本支所プルダウンの選択肢（distinctなbranch_code→branch_name、"(全て)"付き）。
    accounts.forms.StaffSearchForm・organizations.forms.DeptSearchFormで共有する
    （以前は両ファイルに同一ロジックが重複実装されていた。コード監査で発見、2026-08-24集約）。
    """
    branches = Department.objects.order_by("branch_code").values_list("branch_code", "branch_name").distinct()
    return [("", "(全て)")] + [(code, name) for code, name in dict(branches).items()]


def section_choices():
    """部課プルダウンの選択肢。退職者用部課コード(RETIRED_SECTION_CODE)は除外する
    （xlsx 職員マスタ!B41・部署管理!B45「(但し部課コード99の退職者は対象外)」）。
    accounts.forms.StaffSearchForm・organizations.forms.DeptSearchFormで共有する。
    """
    sections = (
        Department.objects.exclude(section_code="")
        .exclude(section_code=RETIRED_SECTION_CODE)
        .order_by("section_code")
        .values_list("section_code", "section_name")
        .distinct()
    )
    return [("", "(全て)")] + [(code, name) for code, name in dict(sections).items()]


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
