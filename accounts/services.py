import logging

from django.db import transaction

from audit import services as audit_services
from accounts.models import Employee, Position, Rank
from core.text_normalization import filter_by_full_name
from permissions.models import FLAG_FIELDS, MULTI_FIELDS, PermissionProfile, PermissionRole
from permissions.services import lock_active_admin_profiles, would_orphan_admins

logger = logging.getLogger(__name__)


class LastAdminError(ValueError):
    """権限リセットの結果、システムの"管理者"が0人になるため処理を中止した場合に送出する
    （xlsx 権限管理!B222-223 / 職員マスタ!B127-128）。

    ValueError を継承するのは、accounts.csv_import_services.import_staff_csv が行データ起因の
    エラーを `except ValueError` で行単位に握って summary.errors へ集積する既存フローに
    そのまま乗せるため（中止は行単位＝1行のミスで取込全体を止めない本モジュールの方針）。
    職員マスタ手動編集（accounts.views.StaffEditView）側は transaction.atomic() でラップして
    この例外を捕捉し、保存前の状態に巻き戻したうえでフォームエラーとして再表示する。
    """

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
    employee, *, department_changed, rank_changed, position_changed, retired_changed, actor
):
    """xlsx 職員マスタ!B228「本支所～役職いずれかが変更になった場合、又は「退職」に設定した場合、
    更新対象職員の権限設定をリセットする」に対応する。

    「リセット」の具体的な中身（プロファイル自体の削除か、フラグを既定値に戻すだけか）は
    HTML/xlsxいずれにも記載が無い。誤って権限を昇格させる方向のバグを避けるため、
    最も安全側（=すべての権限フラグをFalseに戻す、役職はSTAFFへ引き下げ）に倒して実装する。
    プロファイル自体が存在しない職員（権限管理でまだ設定されていない）は何もしない。

    4引数とも「変更になったか」という遷移フラグである点に注意（現在の状態ではない）。
    以前は`retired_changed`の代わりに`employee.is_retired`（保存後の現在値）を直接見ていたため、
    既に退職済みの職員を編集するたび（氏名の誤字修正等、退職と無関係な変更でも）に毎回
    権限がリセットされるバグがあった（コード監査で発見、2026-08-24修正）。呼び出し側は
    department_changed等と同様、保存前後のis_retiredの差分をここに渡すこと。

    `actor`は本処理を引き起こした操作者（職員編集画面の操作ログインユーザー）。リセット自体が
    「権限に関わる操作」（permissions/views.pyの権限管理・手動更新と同種）のため、実行時に
    audit_services.log()で操作履歴ログへ記録する。記録主体は対象職員(employee)本人ではなく、
    permissions/views.pyの権限管理・更新と同様に操作を行った職員(actor)にする。
    """
    if not (department_changed or rank_changed or position_changed or retired_changed):
        return

    try:
        profile = employee.permission_profile
    except PermissionProfile.DoesNotExist:
        return

    # xlsx 権限管理!B222-223 / 職員マスタ!B127-128：システム唯一の"管理者"を、本支所〜役職の
    # 変更や退職に伴うリセットでSTAFFへ落とすと管理者が0人になる。Rev1.5はこのリセット経路
    # 自体の0人ガードを明記していないが、明示的なロール変更（権限管理編集の更新・CSV所属長
    # フラグ降格）だけ塞いでリセット経由を野放しにするとサイレントな孤児化が残る
    # （会話ログ 2026-09-04 の指摘①）。role変更前に判定し、孤児化するなら中止する。
    #
    # 判定〜保存は transaction.atomic() + lock_active_admin_profiles() で囲む。呼び出し側
    # （StaffEditView.post / _import_row）は既に atomic 内だが、ここで明示的に囲むことで本関数
    # 単体でも 0人ガードの check-then-act 競合（review_code_permissions_accounts No.2）を
    # 塞ぐ。在職管理者行をロックしてから admin_count するため、別セッション／CSV取込の別行と
    # 同時に別の管理者を降格しても、片方の commit 後にもう片方が減った人数を見て中止できる。
    with transaction.atomic():
        lock_active_admin_profiles()
        if would_orphan_admins(profile, PermissionRole.STAFF):
            raise LastAdminError(
                "この職員はシステム唯一の「管理者」です。本支所・部課・職階・役職の変更、または"
                "退職の設定を行うと管理者が不在になります。先に他の職員を「管理者」に設定してください。"
            )

        for field in FLAG_FIELDS:
            setattr(profile, field, False)
        profile.role = PermissionRole.STAFF
        for field in MULTI_FIELDS:
            getattr(profile, field).clear()
        profile.save()
        logger.info(
            "所属/職階/役職変更または退職により権限設定をリセットしました: employee_no=%s",
            employee.employee_no,
        )
        audit_services.log(
            employee=actor,
            action="権限管理　自動リセット",
            event_message=(
                f"職員：{employee.name}({employee.employee_no}),"
                "所属/職階/役職変更または退職に伴い権限設定を自動リセットしました"
            ),
        )


def build_staff_edit_diff_message(
    employee, *, before_name, before_department, before_rank, before_position, before_is_retired, password_changed
):
    """screen-staff-edit「更新」ボタンのイベントメッセージ（xlsx 操作履歴ログ!B69-70
    ＜職員マスタ更新　例＞「職員：職員名(職員番号),更新した項目名：更新前データ -> 更新後データ,
    ………」）。実際に変更されたフィールドのみを列挙する（原本フィデリティ監査で発見：以前は
    更新後の職員番号・氏名のみを記録し、何がどう変わったか一切記録していなかった）。

    `before_*`は呼び出し側（accounts.views.StaffEditView.post）がform.save()実行前に
    保存しておいた変更前の値。`password_changed`は新しいパスワードが入力されたかどうかの
    真偽値のみを渡すこと（パスワード自体の値はCLAUDE.mdのマスキング方針によりログに残さない、
    core.views.OtherSettingsView.postの「パスワード　更新」と同じ判断。仮にここで実値を渡しても
    audit_services.build_diff_message が最終防衛としてマスクする）。
    """
    subject = f"職員：{employee.name}({employee.employee_no})"
    changes = []
    if employee.name != before_name:
        changes.append(("氏名", before_name, employee.name))
    if employee.department_id != before_department.pk:
        changes.append(("所属部署", before_department, employee.department))
    if employee.rank != before_rank:
        changes.append(("職階", Rank(before_rank).label, employee.get_rank_display()))
    if employee.position != before_position:
        changes.append(("役職", Position(before_position).label, employee.get_position_display()))
    if employee.is_retired != before_is_retired:
        before_text = "退職" if before_is_retired else "在籍"
        after_text = "退職" if employee.is_retired else "在籍"
        changes.append(("退職", before_text, after_text))
    if password_changed:
        changes.append(("パスワード", "(変更あり)", "(変更あり)"))
    return audit_services.build_diff_message(subject, changes)
