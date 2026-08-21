import logging

from audit import services as audit_services
from accounts.models import Employee
from core.text_normalization import filter_by_full_name
from permissions.models import PermissionProfile, PermissionRole

logger = logging.getLogger(__name__)

# screen-staff-listのソート対象列（xlsx 職員マスタ!B56-62）。CSV出力（B88-91「一覧表に表示
# されている内容(絞込み結果)をCSV形式で出力する」）でも同じ絞込み・並び順を再利用するため
# accounts/views.pyと共有する。
STAFF_SORT_FIELDS = {
    "employee_no": "employee_no",
    "name": "name",
    "branch_code": "department__branch_code",
    "section_code": "department__section_code",
    "rank": "rank",
    "position": "position",
}


def filter_staff_queryset(form, *, sort_key=None, sort_dir="asc"):
    """screen-staff-listの検索条件・ソート順でEmployeeを絞り込む（一覧表示とCSV出力で共有）。

    呼び出し側は`StaffSearchForm(request.GET)`のように必ず（`request.GET or None`ではなく）
    実際のQueryDictをバインドすること。クエリパラメータが1つも無い初回アクセス時、
    `request.GET`は空だが`or None`にすると未バインドフォーム扱いになり`is_valid()`が常にFalseを
    返すため、下記の「退職者を含めない」既定フィルタが効かず退職者が一覧・CSV出力に
    紛れ込むバグが実際に発生していた（ユニットテストで発覚、2026-08-09修正）。
    全フィールドrequired=Falseのフォームなので、空QueryDictでバインドしても検証エラーは出ない。
    """
    qs = Employee.objects.select_related("department")
    if form.is_valid():
        if form.cleaned_data.get("branch_code"):
            qs = qs.filter(department__branch_code=form.cleaned_data["branch_code"])
        if form.cleaned_data.get("section_code"):
            qs = qs.filter(department__section_code=form.cleaned_data["section_code"])
        if form.cleaned_data.get("name"):
            qs = filter_by_full_name(qs, form.cleaned_data["name"])
        if not form.cleaned_data.get("include_retired"):
            qs = qs.filter(is_retired=False)
    field = STAFF_SORT_FIELDS.get(sort_key)
    if field:
        prefix = "-" if sort_dir == "desc" else ""
        qs = qs.order_by(f"{prefix}{field}", "employee_no")
    else:
        # xlsx B51-54: 初期ソート順は本支所コード→部課コード→職階コード→役職コード。
        qs = qs.order_by(
            "department__branch_code", "department__section_code", "rank", "position", "employee_no"
        )
    return qs


def reset_permission_profile_if_needed(
    employee, *, department_changed, rank_changed, position_changed, actor
):
    """xlsx 職員マスタ!B228「本支所～役職いずれかが変更になった場合、又は「退職」に設定した場合、
    更新対象職員の権限設定をリセットする」に対応する。

    「リセット」の具体的な中身（プロファイル自体の削除か、フラグを既定値に戻すだけか）は
    HTML/xlsxいずれにも記載が無い。誤って権限を昇格させる方向のバグを避けるため、
    最も安全側（=すべての権限フラグをFalseに戻す、役職はSTAFFへ引き下げ）に倒して実装する。
    プロファイル自体が存在しない職員（権限管理でまだ設定されていない）は何もしない。

    `actor`は本処理を引き起こした操作者（職員編集画面の操作ログインユーザー）。リセット自体が
    「権限に関わる操作」（permissions/views.pyの権限管理・手動更新と同種）のため、実行時に
    audit_services.log()で操作履歴ログへ記録する。記録主体は対象職員(employee)本人ではなく、
    permissions/views.pyの権限管理・更新と同様に操作を行った職員(actor)にする。
    """
    if not (department_changed or rank_changed or position_changed or employee.is_retired):
        return

    try:
        profile = employee.permission_profile
    except PermissionProfile.DoesNotExist:
        return

    flag_fields = [
        "doc_retention_edit",
        "doc_download",
        "contract_download",
        "eapproval_view_setting",
        "eapproval_doc_name_manage",
        "eapproval_retention",
    ]
    for field in flag_fields:
        setattr(profile, field, False)
    profile.role = PermissionRole.STAFF
    profile.doc_visible_groups.clear()
    profile.contract_visible_departments.clear()
    profile.contract_visible_groups.clear()
    profile.save()
    logger.info(
        "所属/職階/役職変更または退職により権限設定をリセットしました: employee_no=%s",
        employee.employee_no,
    )
    audit_services.log(
        employee=actor,
        action="権限管理 自動リセット",
        event_message=(
            f"職員：{employee.name}({employee.employee_no}),"
            "所属/職階/役職変更または退職に伴い権限設定を自動リセットしました"
        ),
    )
