from django.test import TestCase

from accounts.models import Employee, Position, Rank
from audit.models import AuditLog
from organizations.forms import DeptEditForm, DeptRegistForm
from organizations.models import Department, DepartmentViewScope
from organizations.services import apply_dept_action, visible_department_ids
from permissions.models import PermissionProfile, PermissionRole


class DepartmentModelTests(TestCase):
    def test_str_without_section_name(self):
        """原本index.html:2408等、部課の無い本支所（物流センター等）は区切り文字なしで
        本支所名のみ表示する。
        """
        department = Department.objects.create(
            branch_code="100", branch_name="物流センター", section_code="", section_name=""
        )
        self.assertEqual(str(department), "物流センター")

    def test_str_with_section_name(self):
        """Rev1.1原本で「本支所名|部課名」の表示から本支所名プレフィックスが撤去され、
        部課名のみの表示になった。"""
        department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.assertEqual(str(department), "総務部")


class DeptRegistFormTests(TestCase):
    def setUp(self):
        Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )

    def test_duplicate_branch_and_section_rejected(self):
        """xlsx 部署管理!B87「既に存在している"本支所コード+部課コード"の場合はエラー」。"""
        form = DeptRegistForm(
            data={"branch_code": "000", "branch_name": "本店", "section_code": "01", "section_name": "総務部(重複)"}
        )
        self.assertFalse(form.is_valid())

    def test_new_section_under_existing_branch_allowed(self):
        """xlsx B88「本支所コードと本支所名が既存で部課コードと部課名が無い場合は、
        その本支所への部課追加として新規登録する」。
        """
        form = DeptRegistForm(
            data={"branch_code": "000", "branch_name": "本店", "section_code": "02", "section_name": "経理部"}
        )
        self.assertTrue(form.is_valid(), form.errors)
        department = form.save()
        self.assertEqual(Department.objects.filter(branch_code="000").count(), 2)
        self.assertEqual(str(department), "経理部")


class DeptEditFormTests(TestCase):
    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )

    def test_name_only_update_allowed(self):
        """xlsx 部署管理!B107「各名称のみ、変更可とする」。"""
        form = DeptEditForm(
            data={"branch_name": "本店(新)", "section_name": "総務部(新)", "dept_action": "none"},
            instance=self.department,
        )
        self.assertTrue(form.is_valid(), form.errors)
        department = form.save()
        self.assertEqual(department.branch_name, "本店(新)")
        self.assertEqual(department.section_name, "総務部(新)")
        # コードは編集フォームの対象外のまま。
        self.assertEqual(department.branch_code, "000")

    def test_merge_action_requires_target(self):
        """xlsx 部署管理!B209-212(Rev1.1)で統合・分割の実処理が確定した。対象部署の選択は必須。"""
        form = DeptEditForm(
            data={"branch_name": "本店", "section_name": "総務部", "dept_action": "merge"},
            instance=self.department,
        )
        self.assertFalse(form.is_valid())

    def test_split_action_requires_target(self):
        form = DeptEditForm(
            data={"branch_name": "本店", "section_name": "総務部", "dept_action": "split"},
            instance=self.department,
        )
        self.assertFalse(form.is_valid())

    def test_merge_action_with_target_is_valid(self):
        other = Department.objects.create(
            branch_code="999", branch_name="別支店", section_code="", section_name=""
        )
        form = DeptEditForm(
            data={
                "branch_name": "本店", "section_name": "総務部", "dept_action": "merge",
                "dept_action_target": str(other.pk),
            },
            instance=self.department,
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_cannot_select_self_as_target(self):
        form = DeptEditForm(
            data={
                "branch_name": "本店", "section_name": "総務部", "dept_action": "merge",
                "dept_action_target": str(self.department.pk),
            },
            instance=self.department,
        )
        self.assertFalse(form.is_valid())


class DeptSettingsMenuAccessControlTests(TestCase):
    """設定メニュー「部署管理」は管理者のみ表示・利用可（xlsx 設定メニュー!B46以降）。
    以前はcore.views.SettingsMenuViewでのボタン非表示のみで、URLを直接開けば所属長・一般でも
    到達できてしまっていた（LoginRequiredMixin止まりだったアクセス制御の穴、2026-08-20修正）。
    permissions.mixins.SettingsMenuAccessMixinの回帰テスト。
    """

    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )

    def _login_as(self, role):
        employee = Employee.objects.create_user(
            employee_no="1", name="ログイン太郎", password="pass1234",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        PermissionProfile.objects.create(employee=employee, role=role)
        self.client.login(username="1", password="pass1234")
        return employee

    def test_manager_cannot_access_dept_list(self):
        self._login_as(PermissionRole.MANAGER)
        response = self.client.get("/organizations/")
        self.assertEqual(response.status_code, 403)

    def test_staff_cannot_access_dept_list(self):
        self._login_as(PermissionRole.STAFF)
        response = self.client.get("/organizations/")
        self.assertEqual(response.status_code, 403)

    def test_admin_can_access_dept_list(self):
        self._login_as(PermissionRole.ADMIN)
        response = self.client.get("/organizations/")
        self.assertEqual(response.status_code, 200)


class DeptRegistEditAuditLogTests(TestCase):
    """部署管理の新規登録・更新もmasters/permissions系の登録・更新ビューと同様に
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
        token = self.client.get("/organizations/regist/").context["token"]
        self.client.post(
            "/organizations/regist/",
            {"token": token, "branch_code": "999", "branch_name": "新支店", "section_code": "01", "section_name": "総務部"},
        )
        entry = AuditLog.objects.get(action="部署管理 新規登録")
        self.assertEqual(entry.employee_no, "1")
        self.assertIn("999", entry.event_message)

    def test_edit_creates_audit_log(self):
        target = Department.objects.create(
            branch_code="777", branch_name="テスト支店", section_code="02", section_name="経理部"
        )
        token = self.client.get(f"/organizations/{target.pk}/edit/").context["token"]
        self.client.post(
            f"/organizations/{target.pk}/edit/",
            {"token": token, "branch_name": "テスト支店(新)", "section_name": "経理部(新)", "dept_action": "none"},
        )
        entry = AuditLog.objects.get(action="部署管理 更新")
        self.assertEqual(entry.employee_no, "1")
        self.assertIn("777", entry.event_message)


class DeptRegistIntegrityErrorTests(TestCase):
    """DeptRegistForm.clean()のcheck-then-act方式では防ぎきれない、DBレベルのUniqueConstraint
    違反(IntegrityError)が起きた場合でも、生の例外(500)ではなく利用者にわかるエラーメッセージを
    返すこと。IntegrityErrorはフォームのis_valid()を意図的にバイパスして
    Department.objects.create()を直接呼び出すことで再現する（二重送信対策トークンは同一セッション
    内の再送信しか防げず、この種の競合は防げないため）。
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

        token = self.client.get("/organizations/regist/").context["token"]
        with patch("organizations.forms.DeptRegistForm.save", side_effect=IntegrityError("duplicate key")):
            response = self.client.post(
                "/organizations/regist/",
                {"token": token, "branch_code": "555", "branch_name": "競合支店", "section_code": "01", "section_name": "総務部"},
            )
        self.assertEqual(response.status_code, 200)
        messages = [str(m) for m in response.context["messages"]]
        self.assertTrue(any("登録された可能性" in m for m in messages))
        self.assertFalse(Department.objects.filter(branch_code="555").exists())


class ApplyDeptActionTests(TestCase):
    """organizations.services.apply_dept_action（xlsx 部署管理!B209-212(Rev1.1)）。
    統合・分割の方向の解釈はorganizations.models.DepartmentViewScopeのdocstring参照。
    """

    def setUp(self):
        self.dept_x = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="部署X"
        )
        self.dept_y = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="02", section_name="部署Y"
        )
        self.dept_z = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="03", section_name="部署Z"
        )

    def test_merge_grants_editing_department_visibility_into_target(self):
        """部署Xに部署Yを統合 → Xの職員がYの文書も閲覧可能になる。"""
        apply_dept_action(self.dept_x, DepartmentViewScope.ACTION_MERGE, [self.dept_y])
        scope = DepartmentViewScope.objects.get()
        self.assertEqual(scope.viewer_department, self.dept_x)
        self.assertEqual(scope.visible_department, self.dept_y)

    def test_split_grants_targets_visibility_into_editing_department(self):
        """部署Xを部署Y・Zへ分割 → Y・Zの職員がXの文書も閲覧可能になる。"""
        apply_dept_action(self.dept_x, DepartmentViewScope.ACTION_SPLIT, [self.dept_y, self.dept_z])
        scopes = {(s.viewer_department_id, s.visible_department_id) for s in DepartmentViewScope.objects.all()}
        self.assertEqual(
            scopes,
            {(self.dept_y.pk, self.dept_x.pk), (self.dept_z.pk, self.dept_x.pk)},
        )

    def test_apply_dept_action_is_idempotent(self):
        apply_dept_action(self.dept_x, DepartmentViewScope.ACTION_MERGE, [self.dept_y])
        apply_dept_action(self.dept_x, DepartmentViewScope.ACTION_MERGE, [self.dept_y])
        self.assertEqual(DepartmentViewScope.objects.count(), 1)

    def test_visible_department_ids_includes_own_and_scope(self):
        apply_dept_action(self.dept_x, DepartmentViewScope.ACTION_MERGE, [self.dept_y])
        employee = Employee.objects.create_user(
            employee_no="1", name="テスト太郎", password="x",
            department=self.dept_x, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        self.assertEqual(set(visible_department_ids(employee)), {self.dept_x.pk, self.dept_y.pk})


class DeptEditViewMergeSplitTests(TestCase):
    """screen-dept-editから統合・分割を実行するとDepartmentViewScopeが作成されること。"""

    def setUp(self):
        self.dept_x = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="部署X"
        )
        self.dept_y = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="02", section_name="部署Y"
        )
        self.operator = Employee.objects.create_user(
            employee_no="1", name="操作太郎", password="pass1234",
            department=self.dept_x, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        PermissionProfile.objects.create(employee=self.operator, role=PermissionRole.ADMIN)
        self.client.login(username="1", password="pass1234")

    def test_merge_via_view_creates_scope_and_audit_log(self):
        token = self.client.get(f"/organizations/{self.dept_x.pk}/edit/").context["token"]
        response = self.client.post(
            f"/organizations/{self.dept_x.pk}/edit/",
            {
                "token": token, "branch_name": "本店", "section_name": "部署X",
                "dept_action": "merge", "dept_action_target": str(self.dept_y.pk),
            },
        )
        self.assertRedirects(response, "/organizations/")
        self.assertTrue(
            DepartmentViewScope.objects.filter(
                viewer_department=self.dept_x, visible_department=self.dept_y
            ).exists()
        )
        self.assertTrue(AuditLog.objects.filter(action="部署管理 統合").exists())
        # 部署マスタからの削除は行わない（Rev1.1で論理削除から閲覧部署範囲テーブル更新へ変更）。
        self.assertTrue(Department.objects.filter(pk=self.dept_y.pk).exists())
