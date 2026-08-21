import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from accounts.csv_import_services import CsvImportError, import_staff_csv
from accounts.forms import LoginForm, StaffEditForm, StaffRegistForm
from accounts.models import Employee, Position, Rank
from accounts.services import reset_permission_profile_if_needed
from audit.models import AuditLog
from organizations.models import Department
from permissions.models import PermissionProfile, PermissionRole


class EmployeeModelTests(TestCase):
    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )

    def test_create_user_sets_hashed_password(self):
        """平文パスワードがそのままDBに保存されないこと（ハッシュ化必須の規約）。"""
        employee = Employee.objects.create_user(
            employee_no="1111",
            name="農協 太郎",
            password="plaintext123",
            department=self.department,
            rank=Rank.KOSAYAKU,
            position=Position.KACHO,
        )
        self.assertNotEqual(employee.password, "plaintext123")
        self.assertTrue(employee.check_password("plaintext123"))


class LoginFormTests(TestCase):
    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )

    def test_retired_employee_cannot_login(self):
        """xlsx ログイン画面!B39-42「退職している職員はログイン不可とする」。"""
        Employee.objects.create_user(
            employee_no="9999",
            name="退職 太郎",
            password="pass1234",
            department=self.department,
            rank=Rank.KOSAYAKU,
            position=Position.KACHO,
            is_retired=True,
        )
        form = LoginForm(data={"username": "9999", "password": "pass1234"})
        self.assertFalse(form.is_valid())
        self.assertIn("退職済みの職員はログインできません。", str(form.errors))

    def test_active_employee_can_login(self):
        Employee.objects.create_user(
            employee_no="8888",
            name="在職 太郎",
            password="pass1234",
            department=self.department,
            rank=Rank.KOSAYAKU,
            position=Position.KACHO,
        )
        form = LoginForm(data={"username": "8888", "password": "pass1234"})
        self.assertTrue(form.is_valid())


class StaffRegistFormTests(TestCase):
    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )

    def _valid_data(self, employee_no="1234"):
        return {
            "employee_no": employee_no,
            "name": "農協 花子",
            "department": self.department.pk,
            "rank": Rank.KOSAYAKU,
            "position": Position.KACHO,
        }

    def test_duplicate_employee_no_rejected(self):
        """xlsx 職員マスタ!B166「既に存在している職員番号の場合は登録時にエラーとする」。"""
        Employee.objects.create_user(
            employee_no="1234", name="既存太郎", password="x", department=self.department,
            rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        form = StaffRegistForm(data=self._valid_data(employee_no="1234"))
        self.assertFalse(form.is_valid())
        self.assertIn("employee_no", form.errors)

    def test_save_sets_initial_password_ja_plus_last4(self):
        """xlsx 職員マスタ!B184「登録時のパスワード初期値はja+職員番号下4桁」。"""
        form = StaffRegistForm(data=self._valid_data(employee_no="9012"))
        self.assertTrue(form.is_valid(), form.errors)
        employee = form.save()
        self.assertTrue(employee.check_password("ja9012"))

    def test_rank_position_have_blank_choice_label(self):
        """Django既定の「---------」ではなく原本通り「(選択してください)」を使うこと。"""
        form = StaffRegistForm()
        self.assertIn(("", "(選択してください)"), form.fields["rank"].choices)
        self.assertIn(("", "(選択してください)"), form.fields["position"].choices)

    def test_fullwidth_employee_no_converted_to_halfwidth(self):
        """xlsx 職員マスタ!B173(Rev1.1)「半角数字のみ許可する。(全角の場合は登録時に半角へ変換)」。"""
        form = StaffRegistForm(data=self._valid_data(employee_no="１２３４"))
        self.assertTrue(form.is_valid(), form.errors)
        employee = form.save()
        self.assertEqual(employee.employee_no, "1234")

    def test_non_digit_employee_no_rejected(self):
        form = StaffRegistForm(data=self._valid_data(employee_no="12a4"))
        self.assertFalse(form.is_valid())
        self.assertIn("employee_no", form.errors)

    def test_employee_no_0000_allowed(self):
        """xlsx 職員マスタ!B175(Rev1.1)「職員番号0000の登録も許可(可能)とする。※管理者扱いとしたい為」。"""
        form = StaffRegistForm(data=self._valid_data(employee_no="0000"))
        self.assertTrue(form.is_valid(), form.errors)


class StaffEditFormTests(TestCase):
    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.employee = Employee.objects.create_user(
            employee_no="5555", name="編集太郎", password="original-pass",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )

    def test_blank_password_does_not_change_password(self):
        form = StaffEditForm(
            data={
                "name": "編集太郎", "department": self.department.pk,
                "rank": Rank.KOSAYAKU, "position": Position.KACHO, "password": "",
            },
            instance=self.employee,
        )
        self.assertTrue(form.is_valid(), form.errors)
        employee = form.save()
        self.assertTrue(employee.check_password("original-pass"))

    def test_new_password_changes_password(self):
        form = StaffEditForm(
            data={
                "name": "編集太郎", "department": self.department.pk,
                "rank": Rank.KOSAYAKU, "position": Position.KACHO, "password": "new-pass-999",
            },
            instance=self.employee,
        )
        self.assertTrue(form.is_valid(), form.errors)
        employee = form.save()
        self.assertTrue(employee.check_password("new-pass-999"))


class ResetPermissionProfileTests(TestCase):
    """xlsx 職員マスタ!B228「本支所〜役職いずれかが変更になった場合、又は「退職」に設定した場合、
    更新対象職員の権限設定をリセットする」に対応するaccounts.services.reset_permission_profile_if_needed。
    """

    def setUp(self):
        self.dept1 = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.dept2 = Department.objects.create(
            branch_code="777", branch_name="テスト支店", section_code="", section_name=""
        )
        self.employee = Employee.objects.create_user(
            employee_no="4444", name="権限太郎", password="x",
            department=self.dept1, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        self.profile = PermissionProfile.objects.create(
            employee=self.employee, role=PermissionRole.ADMIN, doc_download=True,
            doc_retention_edit=True,
        )

    def test_no_reset_when_nothing_changed(self):
        reset_permission_profile_if_needed(
            self.employee,
            department_changed=False,
            rank_changed=False,
            position_changed=False,
            actor=self.employee,
        )
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.role, PermissionRole.ADMIN)
        self.assertTrue(self.profile.doc_download)

    def test_reset_on_department_change(self):
        reset_permission_profile_if_needed(
            self.employee,
            department_changed=True,
            rank_changed=False,
            position_changed=False,
            actor=self.employee,
        )
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.role, PermissionRole.STAFF)
        self.assertFalse(self.profile.doc_download)
        self.assertFalse(self.profile.doc_retention_edit)

    def test_reset_on_department_change_creates_audit_log(self):
        """権限に関わる操作のため、リセット実行時は操作者(actor)を記録主体として操作履歴ログに残る
        （permissions/views.pyの権限管理・手動更新と同じ扱い）。"""
        reset_permission_profile_if_needed(
            self.employee,
            department_changed=True,
            rank_changed=False,
            position_changed=False,
            actor=self.employee,
        )
        entry = AuditLog.objects.get(action="権限管理 自動リセット")
        self.assertEqual(entry.employee_no, self.employee.employee_no)
        self.assertIn(self.employee.name, entry.event_message)

    def test_reset_on_retirement(self):
        self.employee.is_retired = True
        reset_permission_profile_if_needed(
            self.employee,
            department_changed=False,
            rank_changed=False,
            position_changed=False,
            actor=self.employee,
        )
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.role, PermissionRole.STAFF)
        self.assertFalse(self.profile.doc_download)

    def test_no_profile_is_noop(self):
        """権限プロファイル未設定の職員は何もしない（例外を出さない）。"""
        other = Employee.objects.create_user(
            employee_no="3333", name="未設定太郎", password="x",
            department=self.dept1, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        reset_permission_profile_if_needed(
            other, department_changed=True, rank_changed=False, position_changed=False, actor=self.employee
        )
        self.assertFalse(PermissionProfile.objects.filter(employee=other).exists())
        # プロファイルが無くリセット自体が発生しないため、監査ログも記録されないこと。
        self.assertFalse(AuditLog.objects.filter(action="権限管理 自動リセット").exists())


class LoginLogoutAuditLogTests(TestCase):
    """原本index.html:3223,3226等の操作履歴ログサンプルに「ログイン」「ログアウト」行があるが、
    以前はaudit.services.log()がdocuments/contracts以外から一切呼ばれておらず記録されていなかった
    （原本フィデリティ監査で発見・修正）。
    """

    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.employee = Employee.objects.create_user(
            employee_no="1", name="監査太郎", password="pass1234",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )

    def test_login_creates_audit_log(self):
        self.client.post("/accounts/login/", {"username": "1", "password": "pass1234"})
        entry = AuditLog.objects.get(action="ログイン")
        self.assertEqual(entry.employee_no, "1")

    def test_logout_creates_audit_log(self):
        self.client.login(username="1", password="pass1234")
        self.client.post("/accounts/logout/")
        entry = AuditLog.objects.get(action="ログアウト")
        self.assertEqual(entry.employee_no, "1")

    def test_wrong_password_creates_failure_audit_log_with_employee_name(self):
        """職員番号は実在するがパスワードが誤っている場合、氏名・部署まで記録できること。"""
        self.client.post("/accounts/login/", {"username": "1", "password": "wrong-password"})
        entry = AuditLog.objects.get(action="ログイン失敗")
        self.assertEqual(entry.employee_no, "1")
        self.assertEqual(entry.employee_name, "監査太郎")

    def test_unknown_employee_no_creates_failure_audit_log(self):
        """職員番号自体が存在しない場合はEmployeeを引けないため「不明」で記録されること。"""
        self.client.post("/accounts/login/", {"username": "99999999", "password": "whatever"})
        entry = AuditLog.objects.get(action="ログイン失敗")
        self.assertEqual(entry.employee_no, "99999999")
        self.assertEqual(entry.employee_name, "(不明)")


class StaffCsvExportViewTests(TestCase):
    """xlsx 職員マスタ!B88-91「一覧表に表示されている内容(絞込み結果)をCSV形式で出力する。
    パスワードはセキュリティ上、空欄で出力すること」。
    """

    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.employee = Employee.objects.create_user(
            employee_no="1111", name="農協 太郎", password="pass1234",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.ADMIN)
        self.client.login(username="1111", password="pass1234")

    def test_export_contains_header_and_row_with_blank_password(self):
        response = self.client.get("/accounts/staff/csv/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8-sig")
        content = response.content.decode("utf-8-sig")
        self.assertIn("職員番号,氏名,パスワード", content)
        self.assertIn("1111,農協 太郎,,000,本店,01,総務部", content)

    def test_export_respects_search_filter(self):
        Employee.objects.create_user(
            employee_no="2222", name="除外太郎", password="x", department=self.department,
            rank=Rank.KOSAYAKU, position=Position.KACHO, is_retired=True,
        )
        response = self.client.get("/accounts/staff/csv/")
        content = response.content.decode("utf-8-sig")
        # include_retired未指定なので退職者はデフォルトで除外される。
        self.assertNotIn("除外太郎", content)

    def test_export_creates_audit_log_with_personal_info_flag(self):
        """氏名等の個人情報を含む一覧ファイル出力のため、documents系のダウンロードと同様に
        personal_info_flag=Trueで操作履歴ログへ記録すること（コード監査で発見された記録漏れの修正）。
        """
        self.client.get("/accounts/staff/csv/")
        entry = AuditLog.objects.get(action="職員マスタ CSV出力")
        self.assertEqual(entry.employee_no, "1111")
        self.assertTrue(entry.personal_info_flag)


class StaffSettingsMenuAccessControlTests(TestCase):
    """設定メニュー「職員マスタ」は管理者のみ表示・利用可（xlsx 設定メニュー!B46以降）。
    以前はcore.views.SettingsMenuViewでのボタン非表示のみで、URLを直接開けば所属長・一般でも
    到達できてしまっていた（LoginRequiredMixin止まりだったアクセス制御の穴、2026-08-20修正）。
    permissions.mixins.SettingsMenuAccessMixinの回帰テスト。
    """

    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.target = Employee.objects.create_user(
            employee_no="2", name="対象太郎", password="x",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )

    def _login_as(self, role):
        employee = Employee.objects.create_user(
            employee_no="1", name="ログイン太郎", password="pass1234",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        PermissionProfile.objects.create(employee=employee, role=role)
        self.client.login(username="1", password="pass1234")
        return employee

    def test_manager_cannot_access_staff_list(self):
        self._login_as(PermissionRole.MANAGER)
        response = self.client.get("/accounts/staff/")
        self.assertEqual(response.status_code, 403)

    def test_staff_cannot_access_staff_list(self):
        self._login_as(PermissionRole.STAFF)
        response = self.client.get("/accounts/staff/")
        self.assertEqual(response.status_code, 403)

    def test_manager_cannot_access_staff_detail(self):
        self._login_as(PermissionRole.MANAGER)
        response = self.client.get(f"/accounts/staff/{self.target.pk}/")
        self.assertEqual(response.status_code, 403)

    def test_admin_can_access_staff_list(self):
        self._login_as(PermissionRole.ADMIN)
        response = self.client.get("/accounts/staff/")
        self.assertEqual(response.status_code, 200)


class StaffRegistEditAuditLogTests(TestCase):
    """職員マスタの新規登録・更新もmasters/permissions系の登録・更新ビューと同様に
    audit_services.log()で操作履歴ログへ記録されること（コード監査で発見された記録漏れの修正）。
    """

    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.operator = Employee.objects.create_user(
            employee_no="1", name="操作太郎", password="pass1234",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        PermissionProfile.objects.create(employee=self.operator, role=PermissionRole.ADMIN)
        self.client.login(username="1", password="pass1234")

    def test_regist_creates_audit_log(self):
        token = self.client.get("/accounts/staff/regist/").context["token"]
        self.client.post(
            "/accounts/staff/regist/",
            {
                "token": token,
                "employee_no": "2020",
                "name": "新規 花子",
                "department": self.department.pk,
                "rank": Rank.KOSAYAKU,
                "position": Position.KACHO,
            },
        )
        entry = AuditLog.objects.get(action="職員マスタ 新規登録")
        self.assertEqual(entry.employee_no, "1")
        self.assertIn("2020", entry.event_message)

    def test_edit_creates_audit_log(self):
        target = Employee.objects.create_user(
            employee_no="3030", name="編集対象", password="x",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        token = self.client.get(f"/accounts/staff/{target.pk}/edit/").context["token"]
        self.client.post(
            f"/accounts/staff/{target.pk}/edit/",
            {
                "token": token,
                "name": "編集後太郎",
                "department": self.department.pk,
                "rank": Rank.KOSAYAKU,
                "position": Position.KACHO,
            },
        )
        entry = AuditLog.objects.get(action="職員マスタ 更新")
        self.assertEqual(entry.employee_no, "1")
        self.assertIn("3030", entry.event_message)


class StaffRegistIntegrityErrorTests(TestCase):
    """StaffRegistForm.clean_employee_no()のcheck-then-act方式では防ぎきれない、DBレベルの
    unique制約違反(IntegrityError)が起きた場合でも、生の例外(500)ではなく利用者にわかる
    エラーメッセージを返すこと。IntegrityErrorはフォームのis_valid()を意図的にバイパスして
    Employee.objects.create_user()を直接呼び出すことで再現する（通常の二重送信対策トークンは
    同一セッション内の再送信しか防げず、この種の競合は防げないため）。
    """

    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.operator = Employee.objects.create_user(
            employee_no="1", name="操作太郎", password="pass1234",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        PermissionProfile.objects.create(employee=self.operator, role=PermissionRole.ADMIN)
        self.client.login(username="1", password="pass1234")

    def test_integrity_error_shows_friendly_message_without_500(self):
        from unittest.mock import patch

        from django.db import IntegrityError

        token = self.client.get("/accounts/staff/regist/").context["token"]
        with patch("accounts.forms.StaffRegistForm.save", side_effect=IntegrityError("duplicate key")):
            response = self.client.post(
                "/accounts/staff/regist/",
                {
                    "token": token,
                    "employee_no": "4040",
                    "name": "競合 太郎",
                    "department": self.department.pk,
                    "rank": Rank.KOSAYAKU,
                    "position": Position.KACHO,
                },
            )
        self.assertEqual(response.status_code, 200)
        messages = [str(m) for m in response.context["messages"]]
        self.assertTrue(any("登録された可能性" in m for m in messages))
        self.assertFalse(Employee.objects.filter(employee_no="4040").exists())


CSV_HEADER_LINE = "職員番号,氏名,支所コード,本支所名正式名称,部課コード,部課名,役職コード,役職名,職階コード,職階名,所属長フラグ"


def _csv_upload(rows):
    content = "\n".join([CSV_HEADER_LINE] + rows) + "\n"
    return SimpleUploadedFile("staff.csv", content.encode("utf-8-sig"), content_type="text/csv")


class ImportStaffCsvServiceTests(TestCase):
    """accounts.csv_import_services.import_staff_csv（xlsx 職員マスタ!B93-142、
    権限管理!B120-125の所属長フラグ連動を含む）。
    """

    def setUp(self):
        self.actor_department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="09", section_name="ＤＸ推進課"
        )
        self.actor = Employee.objects.create_user(
            employee_no="9999", name="操作太郎", password="x",
            department=self.actor_department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )

    def test_invalid_header_raises(self):
        bad_csv = SimpleUploadedFile("staff.csv", b"a,b,c\n1,2,3\n", content_type="text/csv")
        with self.assertRaises(CsvImportError):
            import_staff_csv(bad_csv, actor=self.actor)

    def test_new_employee_is_created_with_department_and_default_password(self):
        upload = _csv_upload(["0832,農協 太郎,000,本　店,09,ＤＸ推進課,16,課長,20,考査役,0"])
        summary = import_staff_csv(upload, actor=self.actor)
        self.assertEqual(summary.created, 1)
        employee = Employee.objects.get(employee_no="0832")
        self.assertEqual(employee.name, "農協 太郎")
        self.assertEqual(employee.department.branch_code, "000")
        self.assertEqual(employee.department.section_code, "09")
        self.assertEqual(employee.rank, Rank.KOSAYAKU)
        self.assertEqual(employee.position, Position.KACHO)
        self.assertTrue(employee.check_password("ja0832"))
        self.assertEqual(employee.permission_profile.role, PermissionRole.STAFF)

    def test_department_is_created_when_missing(self):
        upload = _csv_upload(["0832,農協 太郎,100,物流センター,,,16,課長,20,考査役,0"])
        import_staff_csv(upload, actor=self.actor)
        self.assertTrue(Department.objects.filter(branch_code="100", section_code="").exists())

    def test_department_name_is_updated_when_different(self):
        Department.objects.create(branch_code="100", branch_name="旧名称", section_code="", section_name="")
        upload = _csv_upload(["0832,農協 太郎,100,新名称,,,16,課長,20,考査役,0"])
        import_staff_csv(upload, actor=self.actor)
        department = Department.objects.get(branch_code="100", section_code="")
        self.assertEqual(department.branch_name, "新名称")

    def test_name_only_change_updates_without_resetting_permissions(self):
        """xlsx B111-112(Rev1.1)「職員番号が同じで氏名が変わった場合...氏名を更新する」。
        部課/役職/職階に変更が無いため権限リセット対象外。"""
        department = self.actor_department
        employee = Employee.objects.create_user(
            employee_no="0832", name="旧姓 太郎", password="x",
            department=department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        PermissionProfile.objects.create(employee=employee, role=PermissionRole.ADMIN, doc_download=True)

        upload = _csv_upload(["0832,新姓 太郎,000,本　店,09,ＤＸ推進課,16,課長,20,考査役,0"])
        summary = import_staff_csv(upload, actor=self.actor)

        self.assertEqual(summary.updated, 1)
        employee.refresh_from_db()
        self.assertEqual(employee.name, "新姓 太郎")
        self.assertEqual(employee.permission_profile.role, PermissionRole.ADMIN)
        self.assertTrue(employee.permission_profile.doc_download)

    def test_department_change_resets_permissions(self):
        """xlsx B108-109「部課コード...に差分があった場合...権限設定をリセットする」。"""
        old_department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        employee = Employee.objects.create_user(
            employee_no="0832", name="農協 太郎", password="x",
            department=old_department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        PermissionProfile.objects.create(employee=employee, role=PermissionRole.ADMIN, doc_download=True)

        upload = _csv_upload(["0832,農協 太郎,000,本　店,09,ＤＸ推進課,16,課長,20,考査役,0"])
        summary = import_staff_csv(upload, actor=self.actor)

        self.assertEqual(summary.updated, 1)
        employee.refresh_from_db()
        self.assertEqual(employee.department.section_code, "09")
        self.assertEqual(employee.permission_profile.role, PermissionRole.STAFF)
        self.assertFalse(employee.permission_profile.doc_download)

    def test_section_code_99_marks_employee_retired(self):
        """xlsx B114-115「部課コードが"99"の場合...退職扱いとし退職フラグをセットする」。"""
        department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        employee = Employee.objects.create_user(
            employee_no="0832", name="農協 太郎", password="x",
            department=department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        upload = _csv_upload(["0832,農協 太郎,000,本　店,99,退職,16,課長,20,考査役,0"])
        summary = import_staff_csv(upload, actor=self.actor)
        self.assertEqual(summary.retired, 1)
        employee.refresh_from_db()
        self.assertTrue(employee.is_retired)

    def test_employee_not_in_csv_is_left_untouched(self):
        """xlsx B121-122「職員マスタテーブルに存在し、取込用CSVにない場合...処理不要」。"""
        department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        employee = Employee.objects.create_user(
            employee_no="0832", name="農協 太郎", password="x",
            department=department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        upload = _csv_upload(["9111,別の職員,000,本　店,01,総務部,16,課長,20,考査役,0"])
        import_staff_csv(upload, actor=self.actor)
        employee.refresh_from_db()
        self.assertEqual(employee.name, "農協 太郎")
        self.assertFalse(employee.is_retired)

    def test_manager_flag_promotes_staff_to_manager(self):
        """xlsx B124-125(Rev1.1)「所属長フラグが"1"の場合...権限マスタの対象者を『所属長』として
        権限更新する」。"""
        department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        employee = Employee.objects.create_user(
            employee_no="0832", name="農協 太郎", password="x",
            department=department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        PermissionProfile.objects.create(employee=employee, role=PermissionRole.STAFF)
        upload = _csv_upload(["0832,農協 太郎,000,本　店,01,総務部,16,課長,20,考査役,1"])
        import_staff_csv(upload, actor=self.actor)
        employee.refresh_from_db()
        self.assertEqual(employee.permission_profile.role, PermissionRole.MANAGER)

    def test_manager_flag_does_not_downgrade_admin(self):
        department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        employee = Employee.objects.create_user(
            employee_no="0832", name="農協 太郎", password="x",
            department=department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        PermissionProfile.objects.create(employee=employee, role=PermissionRole.ADMIN)
        upload = _csv_upload(["0832,農協 太郎,000,本　店,01,総務部,16,課長,20,考査役,1"])
        import_staff_csv(upload, actor=self.actor)
        employee.refresh_from_db()
        self.assertEqual(employee.permission_profile.role, PermissionRole.ADMIN)

    def test_row_error_does_not_stop_other_rows(self):
        upload = _csv_upload(
            [
                ",氏名なし,000,本　店,01,総務部,16,課長,20,考査役,0",
                "0832,農協 太郎,000,本　店,01,総務部,16,課長,20,考査役,0",
            ]
        )
        summary = import_staff_csv(upload, actor=self.actor)
        self.assertEqual(summary.created, 1)
        self.assertEqual(len(summary.errors), 1)
        self.assertTrue(Employee.objects.filter(employee_no="0832").exists())


class StaffCsvImportViewTests(TestCase):
    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.operator = Employee.objects.create_user(
            employee_no="9999", name="操作太郎", password="pass1234",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        PermissionProfile.objects.create(employee=self.operator, role=PermissionRole.ADMIN)
        self.client.login(username="9999", password="pass1234")

    def test_post_imports_csv_and_shows_summary_message(self):
        token = self.client.get("/accounts/staff/").context["csv_import_token"]
        upload = _csv_upload(["0832,農協 太郎,000,本　店,01,総務部,16,課長,20,考査役,0"])
        response = self.client.post(
            "/accounts/staff/csv/import/", {"token": token, "csv_file": upload}, follow=True
        )
        self.assertTrue(Employee.objects.filter(employee_no="0832").exists())
        messages = [str(m) for m in response.context["messages"]]
        self.assertTrue(any("新規登録1件" in m for m in messages))

    def test_post_invalid_extension_shows_error(self):
        token = self.client.get("/accounts/staff/").context["csv_import_token"]
        upload = SimpleUploadedFile("staff.txt", b"dummy", content_type="text/plain")
        response = self.client.post(
            "/accounts/staff/csv/import/", {"token": token, "csv_file": upload}, follow=True
        )
        messages = [str(m) for m in response.context["messages"]]
        self.assertTrue(any("csv" in m.lower() for m in messages))
