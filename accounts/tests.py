import io
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from accounts.csv_import_services import CsvImportError, import_staff_csv
from accounts.forms import LoginForm, StaffEditForm, StaffRegistForm, StaffSearchForm
from accounts.models import Employee, Position, Rank
from accounts.services import LastAdminError, filter_staff_queryset, reset_permission_profile_if_needed
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
        # リセットで self.employee が管理者から降格しても「管理者が0人」にならないよう、
        # 別の在職管理者を1名用意しておく（B222-223/B127-128の0人ガードは会話ログ2026-09-04
        # の指摘①で reset 経路にも適用済み。0人ガード自体の検証は test_reset_blocked_* で行う）。
        self.keeper_admin = Employee.objects.create_user(
            employee_no="4445", name="番人 管理者", password="x",
            department=self.dept1, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        PermissionProfile.objects.create(employee=self.keeper_admin, role=PermissionRole.ADMIN)

    def test_no_reset_when_nothing_changed(self):
        reset_permission_profile_if_needed(
            self.employee,
            department_changed=False,
            rank_changed=False,
            position_changed=False,
            retired_changed=False,
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
            retired_changed=False,
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
            retired_changed=False,
            actor=self.employee,
        )
        entry = AuditLog.objects.get(action="権限管理　自動リセット")
        self.assertEqual(entry.employee_no, self.employee.employee_no)
        self.assertIn(self.employee.name, entry.event_message)

    def test_reset_on_retirement(self):
        self.employee.is_retired = True
        reset_permission_profile_if_needed(
            self.employee,
            department_changed=False,
            rank_changed=False,
            position_changed=False,
            retired_changed=True,
            actor=self.employee,
        )
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.role, PermissionRole.STAFF)
        self.assertFalse(self.profile.doc_download)

    def test_no_reset_for_already_retired_employee_with_unrelated_change(self):
        """retired_changed引数を新設する前は、employee.is_retired（現在値）を直接見ていたため、
        既に退職済みの職員を編集するたび（退職と無関係な変更でも）毎回リセットされるバグがあった
        （コード監査で発見、2026-08-24修正）。退職済みだがretired_changed=Falseの場合、
        他のフラグも全てFalseならリセットされないことを確認する回帰テスト。"""
        self.employee.is_retired = True
        self.employee.save(update_fields=["is_retired"])
        reset_permission_profile_if_needed(
            self.employee,
            department_changed=False,
            rank_changed=False,
            position_changed=False,
            retired_changed=False,
            actor=self.employee,
        )
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.role, PermissionRole.ADMIN)
        self.assertTrue(self.profile.doc_download)

    def test_no_profile_is_noop(self):
        """権限プロファイル未設定の職員は何もしない（例外を出さない）。"""
        other = Employee.objects.create_user(
            employee_no="3333", name="未設定太郎", password="x",
            department=self.dept1, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        reset_permission_profile_if_needed(
            other, department_changed=True, rank_changed=False, position_changed=False,
            retired_changed=False, actor=self.employee,
        )
        self.assertFalse(PermissionProfile.objects.filter(employee=other).exists())
        # プロファイルが無くリセット自体が発生しないため、監査ログも記録されないこと。
        self.assertFalse(AuditLog.objects.filter(action="権限管理　自動リセット").exists())

    def test_reset_blocked_when_it_would_orphan_admins(self):
        """xlsx 権限管理!B222-223 / 職員マスタ!B127-128（会話ログ2026-09-04の指摘①）：
        システム唯一の在職管理者を、本支所〜役職変更・退職に伴うリセットでSTAFFへ落とす場合は
        LastAdminError を送出し、権限を一切変更しない。"""
        self.keeper_admin.delete()  # self.employee が唯一の管理者になる
        with self.assertRaises(LastAdminError):
            reset_permission_profile_if_needed(
                self.employee,
                department_changed=True, rank_changed=False, position_changed=False,
                retired_changed=False, actor=self.employee,
            )
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.role, PermissionRole.ADMIN)
        self.assertTrue(self.profile.doc_download)
        self.assertFalse(AuditLog.objects.filter(action="権限管理　自動リセット").exists())

    def test_retired_keeper_admin_does_not_satisfy_the_guard(self):
        """admin_count は退職者を除外する（指摘③）。番人役の管理者が退職済みなら、
        もう一方の管理者のリセットは「0人になる」として弾かれる。"""
        self.keeper_admin.is_retired = True
        self.keeper_admin.save(update_fields=["is_retired"])
        with self.assertRaises(LastAdminError):
            reset_permission_profile_if_needed(
                self.employee,
                department_changed=False, rank_changed=False, position_changed=True,
                retired_changed=False, actor=self.employee,
            )
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.role, PermissionRole.ADMIN)


class FilterStaffQuerysetTests(TestCase):
    """screen-staff-listの検索条件・ソート順（accounts.services.filter_staff_queryset）の
    回帰テスト。permissions側のAuthorityListSortTestsに相当するものが無く、絞り込み・ソートの
    実データ検証が丸ごと無テストだった（コード監査で発見、2026-08-25追加）。
    """

    def setUp(self):
        self.dept_a = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="99", section_name="総務部"
        )
        self.dept_b = Department.objects.create(
            branch_code="999", branch_name="支店", section_code="01", section_name="営業部"
        )
        self.emp_a = Employee.objects.create_user(
            employee_no="2", name="部署A所属", password="x",
            department=self.dept_a, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        self.emp_b = Employee.objects.create_user(
            employee_no="1", name="部署B所属", password="x",
            department=self.dept_b, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        self.retired = Employee.objects.create_user(
            employee_no="3", name="退職太郎", password="x",
            department=self.dept_a, rank=Rank.KOSAYAKU, position=Position.KACHO,
            is_retired=True,
        )

    def test_default_sort_uses_branch_code_before_section_code(self):
        """xlsx 職員マスタ!B51-54: 初期ソート順は本支所コード→部課コード→職階コード→役職コード。
        dept_a(branch=000)のほうがdept_b(branch=999)より先に来ること。"""
        form = StaffSearchForm(data={})
        qs = filter_staff_queryset(form)
        self.assertEqual(list(qs), [self.emp_a, self.emp_b])

    def test_employee_no_sort(self):
        form = StaffSearchForm(data={})
        qs = filter_staff_queryset(form, sort_key="employee_no", sort_dir="asc")
        self.assertEqual(list(qs), [self.emp_b, self.emp_a])

    def test_branch_code_filter(self):
        form = StaffSearchForm(data={"branch_code": "999"})
        qs = filter_staff_queryset(form)
        self.assertEqual(list(qs), [self.emp_b])

    def test_section_code_filter(self):
        form = StaffSearchForm(data={"section_code": "01"})
        qs = filter_staff_queryset(form)
        self.assertEqual(list(qs), [self.emp_b])

    def test_name_filter(self):
        form = StaffSearchForm(data={"name": "部署A"})
        qs = filter_staff_queryset(form)
        self.assertEqual(list(qs), [self.emp_a])

    def test_include_retired_false_excludes_retired_by_default(self):
        form = StaffSearchForm(data={})
        qs = filter_staff_queryset(form)
        self.assertNotIn(self.retired, list(qs))

    def test_include_retired_true_includes_retired(self):
        form = StaffSearchForm(data={"include_retired": "on"})
        qs = filter_staff_queryset(form)
        self.assertIn(self.retired, list(qs))


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
    """xlsx 職員マスタ!B88-91「一覧表に表示されている内容(絞込み結果)をCSV形式で出力する」。
    Rev1.5でパスワード列自体が一覧画面から撤去された（原本html6、旧B91「パスワードは
    セキュリティ上、空欄で出力すること」も削除）ため、CSV出力の列もパスワード無しに揃える。
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

    def test_export_contains_header_and_row_without_password_column(self):
        response = self.client.get("/accounts/staff/csv/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8-sig")
        content = response.content.decode("utf-8-sig")
        self.assertIn("職員番号,氏名,本支所コード", content)
        self.assertNotIn("パスワード", content)
        self.assertIn("1111,農協 太郎,000,本店,01,総務部", content)

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
        entry = AuditLog.objects.get(action="職員マスタ　CSV出力")
        self.assertEqual(entry.employee_no, "1111")
        self.assertTrue(entry.personal_info_flag)

    def test_export_escapes_formula_prefixed_name(self):
        """氏名が「=」等で始まる場合、Excel等で開いた際の数式インジェクション対策として
        シングルクォートを付与する（2026-08-24追加、core.csv_services.sanitize_csv_row参照）。"""
        Employee.objects.create_user(
            employee_no="3333", name="=cmd|'/c calc'!A1", password="x", department=self.department,
            rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        response = self.client.get("/accounts/staff/csv/")
        content = response.content.decode("utf-8-sig")
        self.assertIn("'=cmd|'/c calc'!A1", content)


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

    def test_staff_list_has_no_password_column(self):
        """Rev1.5（原本html6）で職員マスタ一覧からパスワード列（<th>パスワード</th>と
        各行の********セル）が撤去された。"""
        self._login_as(PermissionRole.ADMIN)
        response = self.client.get("/accounts/staff/")
        self.assertNotContains(response, "<th>パスワード</th>", html=True)
        self.assertNotContains(response, "<td>********</td>", html=True)

    def test_staff_edit_keeps_password_reveal_toggle(self):
        """職員マスタ編集の 👁️ トグル（password-toggle2）は Rev1.5/原本html6 で原本からは
        削除されたが、他人のパスワードを設定・リセットする画面での入力確認 UX を優先し、
        ja_pj では意図的に保持する（差異一覧xlsx シート4）。原本追随で誤って消さないための回帰テスト。"""
        self._login_as(PermissionRole.ADMIN)
        response = self.client.get(f"/accounts/staff/{self.target.pk}/edit/")
        self.assertContains(response, 'id="pass-toggle-icon2"')

    def test_manager_cannot_access_staff_csv_export(self):
        self._login_as(PermissionRole.MANAGER)
        response = self.client.get("/accounts/staff/csv/")
        self.assertEqual(response.status_code, 403)

    def test_staff_cannot_access_staff_csv_import(self):
        self._login_as(PermissionRole.STAFF)
        response = self.client.get("/accounts/staff/csv/import/")
        self.assertEqual(response.status_code, 403)

    def test_manager_cannot_access_staff_regist(self):
        self._login_as(PermissionRole.MANAGER)
        response = self.client.get("/accounts/staff/regist/")
        self.assertEqual(response.status_code, 403)

    def test_staff_cannot_access_staff_edit(self):
        self._login_as(PermissionRole.STAFF)
        response = self.client.get(f"/accounts/staff/{self.target.pk}/edit/")
        self.assertEqual(response.status_code, 403)


class StaffDetailViewTests(TestCase):
    """screen-staff-detail。以前は丸ごと無テストだった
    （アクセス拒否側＝所属長403のみStaffSettingsMenuAccessControlTestsでカバー済み、
    コード監査で発見、2026-08-25追加）。
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
        self.target = Employee.objects.create_user(
            employee_no="2", name="対象太郎", password="secret-pass",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        self.client.login(username="1", password="pass1234")

    def test_admin_can_access_staff_detail(self):
        response = self.client.get(f"/accounts/staff/{self.target.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "対象太郎")

    def test_password_is_masked_not_shown_in_plaintext(self):
        """ハッシュ化必須の規約上マスク表示にする（CLAUDE.md参照）。マスク文字は
        Rev1.5/html6でマスク化された原本に合わせ ●●●●●●。"""
        response = self.client.get(f"/accounts/staff/{self.target.pk}/")
        self.assertNotContains(response, "secret-pass")
        self.assertContains(response, "●●●●●●")

    def test_nonexistent_pk_returns_404(self):
        response = self.client.get("/accounts/staff/999999/")
        self.assertEqual(response.status_code, 404)


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
        entry = AuditLog.objects.get(action="職員マスタ　新規登録")
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
        entry = AuditLog.objects.get(action="職員マスタ　更新")
        self.assertEqual(entry.employee_no, "1")
        self.assertIn("3030", entry.event_message)

    def test_edit_creates_audit_log_with_diff_content(self):
        """xlsx 操作履歴ログ!B69-70＜職員マスタ更新　例＞「職員：職員名(職員番号),更新した項目名：
        更新前データ -> 更新後データ,………」形式で、実際に変更されたフィールドのみが記録されること
        （原本フィデリティ監査で発見：以前は更新後の職員番号・氏名のみを記録し、何がどう変わったか
        一切記録していなかった）。氏名と職階を変更し、部署・役職は変更しない。
        """
        target = Employee.objects.create_user(
            employee_no="3031", name="差分太郎", password="x",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        token = self.client.get(f"/accounts/staff/{target.pk}/edit/").context["token"]
        self.client.post(
            f"/accounts/staff/{target.pk}/edit/",
            {
                "token": token,
                "name": "差分太郎改",
                "department": self.department.pk,
                "rank": Rank.CHOSAYAKU,
                "position": Position.KACHO,
            },
        )
        entry = AuditLog.objects.get(action="職員マスタ　更新", employee_no="1")
        self.assertEqual(
            entry.event_message,
            "職員：差分太郎改(3031),氏名：差分太郎 -> 差分太郎改,職階：考査役 -> 調査役",
        )

    def test_edit_with_no_field_changes_creates_audit_log_without_diff(self):
        """変更が無いフィールドは列挙しない（build_diff_messageは差分が0件なら対象識別子のみ返す）。"""
        target = Employee.objects.create_user(
            employee_no="3032", name="無変更太郎", password="x",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        token = self.client.get(f"/accounts/staff/{target.pk}/edit/").context["token"]
        self.client.post(
            f"/accounts/staff/{target.pk}/edit/",
            {
                "token": token,
                "name": "無変更太郎",
                "department": self.department.pk,
                "rank": Rank.KOSAYAKU,
                "position": Position.KACHO,
            },
        )
        entry = AuditLog.objects.get(action="職員マスタ　更新", employee_no="1")
        self.assertEqual(entry.event_message, "職員：無変更太郎(3032)")

    def test_edit_password_change_records_marker_without_actual_value(self):
        """CLAUDE.mdのパスワードマスキング方針により、パスワード自体の値はログに残さない
        （core.views.OtherSettingsView.postの「パスワード　更新」と同じ判断）。
        """
        target = Employee.objects.create_user(
            employee_no="3033", name="鍵太郎", password="x",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        token = self.client.get(f"/accounts/staff/{target.pk}/edit/").context["token"]
        self.client.post(
            f"/accounts/staff/{target.pk}/edit/",
            {
                "token": token,
                "name": "鍵太郎",
                "department": self.department.pk,
                "rank": Rank.KOSAYAKU,
                "position": Position.KACHO,
                "password": "shinpasuwaado",
            },
        )
        entry = AuditLog.objects.get(action="職員マスタ　更新", employee_no="1")
        self.assertNotIn("shinpasuwaado", entry.event_message)
        self.assertEqual(entry.event_message, "職員：鍵太郎(3033),パスワード：(変更あり) -> (変更あり)")

    def test_regist_post_with_invalid_token_shows_error_and_does_not_create(self):
        """二重送信対策トークン不正時（core.double_submit.consume_tokenがFalseを返すケース）の
        分岐が未テストだった（コード監査で発見、2026-08-25追加）。"""
        response = self.client.post(
            "/accounts/staff/regist/",
            {
                "token": "invalid-token",
                "employee_no": "5050",
                "name": "無効太郎",
                "department": self.department.pk,
                "rank": Rank.KOSAYAKU,
                "position": Position.KACHO,
            },
            follow=True,
        )
        self.assertFalse(Employee.objects.filter(employee_no="5050").exists())
        messages = [str(m) for m in response.context["messages"]]
        self.assertTrue(any("二重に送信された可能性" in m for m in messages))


class StaffEditViewResetPermissionIntegrationTests(TestCase):
    """StaffEditView.postがbefore_department_id等の差分検出ロジックを介して
    reset_permission_profile_if_neededを実際に「変更あり」で駆動する経路の統合テスト。
    既存のtest_edit_creates_audit_log（StaffRegistEditAuditLogTests）は変更前と同一の値で
    POSTしているため、この結線自体は一度もHTTP経由で通っていなかった
    （コード監査で発見、2026-08-25追加）。
    """

    def setUp(self):
        self.dept1 = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.dept2 = Department.objects.create(
            branch_code="999", branch_name="別支店", section_code="", section_name=""
        )
        self.operator = Employee.objects.create_user(
            employee_no="1", name="操作太郎", password="pass1234",
            department=self.dept1, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        PermissionProfile.objects.create(employee=self.operator, role=PermissionRole.ADMIN)
        self.client.login(username="1", password="pass1234")

    def test_department_change_via_post_resets_permission_profile(self):
        target = Employee.objects.create_user(
            employee_no="3030", name="編集対象", password="x",
            department=self.dept1, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        profile = PermissionProfile.objects.create(
            employee=target, role=PermissionRole.ADMIN, doc_download=True
        )
        token = self.client.get(f"/accounts/staff/{target.pk}/edit/").context["token"]
        self.client.post(
            f"/accounts/staff/{target.pk}/edit/",
            {
                "token": token,
                "name": "編集対象",
                "department": self.dept2.pk,
                "rank": Rank.KOSAYAKU,
                "position": Position.KACHO,
            },
        )
        profile.refresh_from_db()
        self.assertEqual(profile.role, PermissionRole.STAFF)
        self.assertFalse(profile.doc_download)
        self.assertTrue(AuditLog.objects.filter(action="権限管理　自動リセット").exists())

    def test_no_change_via_post_does_not_reset_permission_profile(self):
        """比較対象として、実際に値を変えないPOSTではリセットされないことも合わせて確認する。"""
        target = Employee.objects.create_user(
            employee_no="4040", name="編集対象2", password="x",
            department=self.dept1, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        profile = PermissionProfile.objects.create(
            employee=target, role=PermissionRole.ADMIN, doc_download=True
        )
        token = self.client.get(f"/accounts/staff/{target.pk}/edit/").context["token"]
        self.client.post(
            f"/accounts/staff/{target.pk}/edit/",
            {
                "token": token,
                "name": "編集対象2",
                "department": self.dept1.pk,
                "rank": Rank.KOSAYAKU,
                "position": Position.KACHO,
            },
        )
        profile.refresh_from_db()
        self.assertEqual(profile.role, PermissionRole.ADMIN)
        self.assertTrue(profile.doc_download)

    def test_editing_last_admins_own_position_is_blocked(self):
        """会話ログ2026-09-04の指摘①：職員マスタ手動編集でも、システム唯一の在職管理者の
        本支所〜役職変更・退職はリセット経由で管理者を0人にしてしまう。
        LastAdminError をビューが捕捉し、トランザクションごと巻き戻して更新を中止する。"""
        # self.operator が唯一の管理者。自分の役職を変更しようとする。
        profile = PermissionProfile.objects.get(employee=self.operator)
        token = self.client.get(f"/accounts/staff/{self.operator.pk}/edit/").context["token"]
        response = self.client.post(
            f"/accounts/staff/{self.operator.pk}/edit/",
            {
                "token": token,
                "name": "操作太郎",
                "department": self.dept1.pk,
                "rank": Rank.KOSAYAKU,
                "position": Position.KAKARICHO,  # 課長 -> 係長
            },
        )
        self.assertEqual(response.status_code, 200)
        messages = [str(m) for m in response.context["messages"]]
        self.assertTrue(any("システム唯一の「管理者」" in m for m in messages))
        self.operator.refresh_from_db()
        profile.refresh_from_db()
        # 役職も権限も変わっていない（トランザクションごとロールバック）。
        self.assertEqual(self.operator.position, Position.KACHO)
        self.assertEqual(profile.role, PermissionRole.ADMIN)
        self.assertFalse(AuditLog.objects.filter(action="権限管理　自動リセット").exists())

    def test_editing_last_admins_own_position_allowed_with_another_admin(self):
        """他に在職管理者が居れば、同じ操作は通り、権限はリセットされる。"""
        other_admin = Employee.objects.create_user(
            employee_no="2", name="副管理者", password="x",
            department=self.dept1, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        PermissionProfile.objects.create(employee=other_admin, role=PermissionRole.ADMIN)
        profile = PermissionProfile.objects.get(employee=self.operator)
        token = self.client.get(f"/accounts/staff/{self.operator.pk}/edit/").context["token"]
        self.client.post(
            f"/accounts/staff/{self.operator.pk}/edit/",
            {
                "token": token,
                "name": "操作太郎",
                "department": self.dept1.pk,
                "rank": Rank.KOSAYAKU,
                "position": Position.KAKARICHO,
            },
        )
        self.operator.refresh_from_db()
        profile.refresh_from_db()
        self.assertEqual(self.operator.position, Position.KAKARICHO)
        self.assertEqual(profile.role, PermissionRole.STAFF)

    def test_edit_post_with_invalid_token_does_not_save_or_reset(self):
        """二重送信対策トークン不正時（core.double_submit.consume_tokenがFalseを返すケース）の
        分岐が未テストだった（コード監査で発見、2026-08-25追加）。"""
        target = Employee.objects.create_user(
            employee_no="6060", name="編集対象3", password="x",
            department=self.dept1, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        response = self.client.post(
            f"/accounts/staff/{target.pk}/edit/",
            {
                "token": "invalid-token",
                "name": "改ざん太郎",
                "department": self.dept2.pk,
                "rank": Rank.KOSAYAKU,
                "position": Position.KACHO,
            },
            follow=True,
        )
        target.refresh_from_db()
        self.assertEqual(target.name, "編集対象3")
        self.assertEqual(target.department_id, self.dept1.pk)
        messages = [str(m) for m in response.context["messages"]]
        self.assertTrue(any("二重に送信された可能性" in m for m in messages))


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
        # 降格しても管理者が0人にならないよう別の在職管理者を1名用意（0人ガードは
        # 会話ログ2026-09-04の指摘①でリセット経路にも適用。ガード自体は
        # test_department_change_blocked_when_it_would_orphan_admins で検証）。
        keeper = Employee.objects.create_user(
            employee_no="0001", name="番人 管理者", password="x",
            department=self.actor_department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        PermissionProfile.objects.create(employee=keeper, role=PermissionRole.ADMIN)

        upload = _csv_upload(["0832,農協 太郎,000,本　店,09,ＤＸ推進課,16,課長,20,考査役,0"])
        summary = import_staff_csv(upload, actor=self.actor)

        self.assertEqual(summary.updated, 1)
        employee.refresh_from_db()
        self.assertEqual(employee.department.section_code, "09")
        self.assertEqual(employee.permission_profile.role, PermissionRole.STAFF)
        self.assertFalse(employee.permission_profile.doc_download)

    def test_department_change_blocked_when_it_would_orphan_admins(self):
        """会話ログ2026-09-04の指摘①：所属長フラグ経由でなくても、CSVで最後の在職管理者の
        部課/役職が変わると reset_permission_profile_if_needed が管理者を0人にしてしまう。
        LastAdminError（ValueError サブクラス）で当該行をロールバックし summary.errors へ集積する。"""
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

        self.assertEqual(summary.updated, 0)
        self.assertEqual(len(summary.errors), 1)
        self.assertIn("管理者", summary.errors[0])
        employee.refresh_from_db()
        # 行全体がロールバックされるので部課変更も権限リセットも反映されない。
        self.assertEqual(employee.department.section_code, "01")
        self.assertEqual(employee.permission_profile.role, PermissionRole.ADMIN)
        self.assertTrue(employee.permission_profile.doc_download)

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

    def test_manager_flag_demotes_admin_when_another_admin_exists(self):
        """Rev1.5 職員マスタ!B127-128：所属長フラグによる管理者→所属長の降格を許容する
        （他に管理者が居る場合）。以前はCSV取込では管理者を降格させない安全弁を入れていたが、
        Rev1.5が降格前提の0人チェックを要求したため方針転換（ユーザー確認 2026-09-04）。"""
        target = Employee.objects.create_user(
            employee_no="0832", name="農協 太郎", password="x",
            department=self.actor_department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        PermissionProfile.objects.create(employee=target, role=PermissionRole.ADMIN)
        # 他にもう1人管理者が居るので降格しても0人にはならない。
        keeper = Employee.objects.create_user(
            employee_no="0001", name="残る管理者", password="x",
            department=self.actor_department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        PermissionProfile.objects.create(employee=keeper, role=PermissionRole.ADMIN)

        upload = _csv_upload(["0832,農協 太郎,000,本　店,09,ＤＸ推進課,16,課長,20,考査役,1"])
        summary = import_staff_csv(upload, actor=self.actor)

        self.assertEqual(summary.errors, [])
        target.refresh_from_db()
        self.assertEqual(target.permission_profile.role, PermissionRole.MANAGER)
        self.assertTrue(
            AuditLog.objects.filter(action="職員マスタ　CSV取込 所属長降格").exists()
        )

    def test_manager_flag_demotion_blocked_when_last_admin(self):
        """Rev1.5 職員マスタ!B128：所属長フラグによる降格で管理者が0人になる場合は、
        メッセージを表示してその行の取込を中止する（行単位トランザクションをロールバック）。"""
        target = Employee.objects.create_user(
            employee_no="0832", name="農協 太郎", password="x",
            department=self.actor_department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        PermissionProfile.objects.create(employee=target, role=PermissionRole.ADMIN)

        upload = _csv_upload(["0832,農協 花子,000,本　店,09,ＤＸ推進課,16,課長,20,考査役,1"])
        summary = import_staff_csv(upload, actor=self.actor)

        self.assertEqual(len(summary.errors), 1)
        self.assertIn("管理者が0人になる", summary.errors[0])
        target.refresh_from_db()
        # 行全体がロールバックされるので氏名変更も権限降格も反映されない。
        self.assertEqual(target.name, "農協 太郎")
        self.assertEqual(target.permission_profile.role, PermissionRole.ADMIN)
        # 中止された行はsummaryのカウンタにも計上しない（氏名・部課の差分がある行だが
        # _apply_manager_flagのLastAdminErrorでロールバックされるため updated=0）。
        self.assertEqual(summary.updated, 0)
        self.assertEqual(summary.unchanged, 0)
        self.assertEqual(summary.retired, 0)
        self.assertEqual(summary.created, 0)

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

    def test_invalid_rank_code_is_rejected(self):
        """StaffRegistForm/StaffEditFormはChoiceFieldで職階コードを検証するが、CSV取込は
        Employee.save()を直接呼ぶためchoices検証を経由しない。手動フォームと同じ検証を行う
        （コード監査で発見、2026-08-24修正）。"""
        upload = _csv_upload(["0832,農協 太郎,000,本　店,01,総務部,16,課長,XX,不正,0"])
        summary = import_staff_csv(upload, actor=self.actor)
        self.assertEqual(summary.created, 0)
        self.assertEqual(len(summary.errors), 1)
        self.assertIn("職階コード", summary.errors[0])
        self.assertFalse(Employee.objects.filter(employee_no="0832").exists())

    def test_invalid_position_code_is_rejected(self):
        upload = _csv_upload(["0832,農協 太郎,000,本　店,01,総務部,XX,不正,20,考査役,0"])
        summary = import_staff_csv(upload, actor=self.actor)
        self.assertEqual(summary.created, 0)
        self.assertEqual(len(summary.errors), 1)
        self.assertIn("役職コード", summary.errors[0])
        self.assertFalse(Employee.objects.filter(employee_no="0832").exists())

    def test_column_count_mismatch_is_rejected(self):
        # 所属長フラグ列が欠落した10列の行（正しくは11列）。
        upload = _csv_upload(["0832,農協 太郎,000,本　店,01,総務部,16,課長,20,考査役"])
        summary = import_staff_csv(upload, actor=self.actor)
        self.assertEqual(len(summary.errors), 1)
        self.assertIn("列数", summary.errors[0])

    def test_empty_file_raises(self):
        empty = SimpleUploadedFile("staff.csv", b"", content_type="text/csv")
        with self.assertRaises(CsvImportError):
            import_staff_csv(empty, actor=self.actor)

    def test_invalid_encoding_raises(self):
        # Shift-JISのバイト列はUTF-8として不正な並びになるため、utf-8-sigでのdecodeが失敗する。
        bad_bytes = SimpleUploadedFile("staff.csv", b"\x82\xa0\x82\xa2\x82\xa4", content_type="text/csv")
        with self.assertRaises(CsvImportError):
            import_staff_csv(bad_bytes, actor=self.actor)

    def test_unexpected_exception_shows_generic_message_not_raw_text(self):
        """行処理中に想定外の例外（バグ等）が起きた場合、生の例外メッセージをそのまま
        利用者に見せず、汎用的な日本語メッセージを返す（コード監査で発見、2026-08-24修正）。"""
        upload = _csv_upload(["0832,農協 太郎,000,本　店,01,総務部,16,課長,20,考査役,0"])
        with patch("accounts.csv_import_services._upsert_department", side_effect=RuntimeError("boom")):
            summary = import_staff_csv(upload, actor=self.actor)
        self.assertEqual(len(summary.errors), 1)
        self.assertIn("予期しないエラー", summary.errors[0])
        self.assertNotIn("boom", summary.errors[0])

    def test_manager_flag_does_not_promote_employee_who_just_retired(self):
        """退職とマネージャー昇格が同じ行に含まれる場合、退職によるSTAFFへのリセットを
        所属長フラグが上書きしないことを確認する（コード監査で発見、2026-08-24修正）。"""
        department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        employee = Employee.objects.create_user(
            employee_no="0832", name="農協 太郎", password="x",
            department=department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        PermissionProfile.objects.create(employee=employee, role=PermissionRole.STAFF)
        upload = _csv_upload(["0832,農協 太郎,000,本　店,99,退職,16,課長,20,考査役,1"])
        import_staff_csv(upload, actor=self.actor)
        employee.refresh_from_db()
        self.assertTrue(employee.is_retired)
        self.assertEqual(employee.permission_profile.role, PermissionRole.STAFF)

    def test_manager_flag_promotion_creates_audit_log(self):
        """所属長フラグによる昇格もreset_permission_profile_if_neededと同様に権限に関わる操作の
        ため、audit_services.log()で記録する（コード監査で発見、2026-08-24修正）。"""
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
        entry = AuditLog.objects.get(action="職員マスタ　CSV取込 所属長昇格")
        self.assertIn("0832", entry.event_message)


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

    def test_post_with_invalid_token_shows_error_and_does_not_import(self):
        """二重送信対策トークン不正時（core.double_submit.consume_tokenがFalseを返すケース）の
        分岐が未テストだった（コード監査で発見、2026-08-25追加）。"""
        upload = _csv_upload(["0832,農協 太郎,000,本　店,01,総務部,16,課長,20,考査役,0"])
        response = self.client.post(
            "/accounts/staff/csv/import/", {"token": "invalid-token", "csv_file": upload}, follow=True
        )
        self.assertFalse(Employee.objects.filter(employee_no="0832").exists())
        messages = [str(m) for m in response.context["messages"]]
        self.assertTrue(any("二重に送信された可能性" in m for m in messages))

    def test_post_invalid_extension_shows_error(self):
        token = self.client.get("/accounts/staff/").context["csv_import_token"]
        upload = SimpleUploadedFile("staff.txt", b"dummy", content_type="text/plain")
        response = self.client.post(
            "/accounts/staff/csv/import/", {"token": token, "csv_file": upload}, follow=True
        )
        messages = [str(m) for m in response.context["messages"]]
        self.assertTrue(any("csv" in m.lower() for m in messages))

    def test_post_with_csv_import_error_shows_error_message(self):
        """import_staff_csvがCsvImportErrorを送出した場合（ここではヘッダー不正CSV）の
        messages.error案内はView統合テストとして未テストだった（サービス層の例外送出自体は
        ImportStaffCsvServiceTests.test_invalid_header_raisesでカバー済み、コード監査で発見、
        2026-08-25追加）。"""
        token = self.client.get("/accounts/staff/").context["csv_import_token"]
        upload = SimpleUploadedFile("staff.csv", b"a,b,c\n1,2,3\n", content_type="text/csv")
        response = self.client.post(
            "/accounts/staff/csv/import/", {"token": token, "csv_file": upload}, follow=True
        )
        messages = [str(m) for m in response.context["messages"]]
        self.assertTrue(any("CSVの列構成が想定と異なります" in m for m in messages))

    def test_post_with_row_errors_shows_warning_message(self):
        """summary.errorsが1件以上ある場合のmessages.warning分岐（部分成功時の警告表示）は
        View経由では未テストだった（サービス層のsummary.errors自体はImportStaffCsvServiceTests.
        test_row_error_does_not_stop_other_rowsでカバー済み、コード監査で発見、2026-08-25追加）。"""
        token = self.client.get("/accounts/staff/").context["csv_import_token"]
        upload = _csv_upload(
            [
                ",氏名なし,000,本　店,01,総務部,16,課長,20,考査役,0",
                "0832,農協 太郎,000,本　店,01,総務部,16,課長,20,考査役,0",
            ]
        )
        response = self.client.post(
            "/accounts/staff/csv/import/", {"token": token, "csv_file": upload}, follow=True
        )
        self.assertTrue(Employee.objects.filter(employee_no="0832").exists())
        messages = [str(m) for m in response.context["messages"]]
        self.assertTrue(any("一部エラーがありました" in m for m in messages))
