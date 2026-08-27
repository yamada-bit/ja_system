from django.test import TestCase

from accounts.models import Employee, Position, Rank
from audit.models import AuditLog
from organizations.forms import DeptEditForm, DeptRegistForm
from organizations.models import Department, DepartmentViewScope
from organizations.services import (
    apply_dept_action,
    branch_choices,
    departments_list,
    section_choices,
    visible_department_ids,
)
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

    def test_manager_cannot_access_dept_regist(self):
        self._login_as(PermissionRole.MANAGER)
        response = self.client.get("/organizations/regist/")
        self.assertEqual(response.status_code, 403)

    def test_staff_cannot_access_dept_edit(self):
        self._login_as(PermissionRole.STAFF)
        response = self.client.get(f"/organizations/{self.department.pk}/edit/")
        self.assertEqual(response.status_code, 403)

    def test_manager_cannot_access_option_list_api(self):
        """organizations.api.OptionListAPIViewはLoginRequiredMixinのみでdept_management限定に
        なっておらず、非管理者でも/organizations/api/options/を直叩きすれば全部署一覧を取得
        できてしまっていた（コード監査で発見、2026-08-24修正）。"""
        self._login_as(PermissionRole.MANAGER)
        response = self.client.get("/organizations/api/options/", {"type": "dept"})
        self.assertEqual(response.status_code, 403)

    def test_admin_can_access_option_list_api(self):
        self._login_as(PermissionRole.ADMIN)
        response = self.client.get("/organizations/api/options/", {"type": "dept"})
        self.assertEqual(response.status_code, 200)

    def test_anonymous_option_list_api_redirects_to_login_not_500(self):
        """SettingsMenuAccessMixinを多重継承で挟み込まずdispatch()内で明示チェックしているため、
        未ログイン時にget_role()へAnonymousUserが渡りAttributeErrorで落ちないことを確認する。"""
        response = self.client.get("/organizations/api/options/", {"type": "dept"})
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)


class OptionListAPIResponseContentTests(TestCase):
    """organizations.api.OptionListAPIViewはアクセス制御のみ検証されており、実際のレスポンス
    内容（`_department_items()`が返す{value, label}のリスト、branch_code→section_code順）が
    一度も検証されていなかった（テストカバレッジ棚卸しで発見、2026-08-26追加）。
    """

    def setUp(self):
        self.dept_a = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.dept_b = Department.objects.create(
            branch_code="999", branch_name="別支店", section_code="", section_name=""
        )
        self.operator = Employee.objects.create_user(
            employee_no="1", name="操作太郎", password="pass1234",
            department=self.dept_a, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        PermissionProfile.objects.create(employee=self.operator, role=PermissionRole.ADMIN)
        self.client.login(username="1", password="pass1234")

    def test_dept_options_returns_all_departments_ordered_by_branch_and_section_code(self):
        response = self.client.get("/organizations/api/options/", {"type": "dept"})
        self.assertEqual(
            response.json(),
            {
                "items": [
                    {"value": self.dept_a.pk, "label": str(self.dept_a)},
                    {"value": self.dept_b.pk, "label": str(self.dept_b)},
                ]
            },
        )

    def test_unsupported_type_returns_400(self):
        """BaseOptionListAPIView.getのelse分岐（type未指定・未対応値）は本画面が使わない
        分岐だが、共通実装として未検証だった（本画面はdeptのみ使用するため実害は小さい）。"""
        response = self.client.get("/organizations/api/options/", {"type": "unsupported"})
        self.assertEqual(response.status_code, 400)


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


class DeptDoubleSubmitTokenTests(TestCase):
    """二重送信対策トークン不正時（core.double_submit.consume_tokenがFalseを返すケース）の分岐が
    organizations側の登録・編集Viewで未テストだった（2026-08-25付permissions/accounts棚卸しの
    中優先度7と同一パターン。テストカバレッジ棚卸しで発見、2026-08-26追加）。
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

    def test_regist_post_with_invalid_token_shows_error_and_does_not_save(self):
        response = self.client.post(
            "/organizations/regist/",
            {
                "token": "invalid-token", "branch_code": "999", "branch_name": "新支店",
                "section_code": "01", "section_name": "総務部",
            },
            follow=True,
        )
        messages = [str(m) for m in response.context["messages"]]
        self.assertTrue(any("二重に送信された可能性" in m for m in messages))
        self.assertFalse(Department.objects.filter(branch_code="999").exists())

    def test_edit_post_with_invalid_token_shows_error_and_does_not_save(self):
        response = self.client.post(
            f"/organizations/{self.department.pk}/edit/",
            {
                "token": "invalid-token", "branch_name": "本店(改)", "section_name": "総務部(改)",
                "dept_action": "none",
            },
            follow=True,
        )
        messages = [str(m) for m in response.context["messages"]]
        self.assertTrue(any("二重に送信された可能性" in m for m in messages))
        self.department.refresh_from_db()
        self.assertEqual(self.department.branch_name, "本店")


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


class DeptEditIntegrityErrorTests(TestCase):
    """DeptEditView.postはform.save()とapply_dept_action()を単一のtransaction.atomic()で
    まとめており、統合・分割実行中にIntegrityErrorが発生した場合はform.save()側の変更も含めて
    ロールバックされる（2026-08-25にコードレビュー指摘を受けて追加された修正）。
    apply_dept_actionをモックしてIntegrityErrorを発生させ、DeptRegistIntegrityErrorTestsと
    同様に生の例外(500)ではなくフレンドリーメッセージを返し、DBには一切反映されないことを
    確認する回帰テスト。
    """

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

    def test_integrity_error_during_merge_rolls_back_form_save_too(self):
        from unittest.mock import patch

        from django.db import IntegrityError

        token = self.client.get(f"/organizations/{self.dept_x.pk}/edit/").context["token"]
        with patch("organizations.views.apply_dept_action", side_effect=IntegrityError("duplicate key")):
            response = self.client.post(
                f"/organizations/{self.dept_x.pk}/edit/",
                {
                    "token": token, "branch_name": "本店(競合)", "section_name": "部署X(競合)",
                    "dept_action": "merge", "dept_action_target": str(self.dept_y.pk),
                },
            )
        self.assertEqual(response.status_code, 200)
        messages = [str(m) for m in response.context["messages"]]
        self.assertTrue(any("競合したため保存できませんでした" in m for m in messages))
        # transaction.atomic()のロールバックにより、apply_dept_action側だけでなくform.save()側の
        # 変更も反映されていないこと。
        self.dept_x.refresh_from_db()
        self.assertEqual(self.dept_x.branch_name, "本店")
        self.assertEqual(self.dept_x.section_name, "部署X")
        self.assertFalse(
            DepartmentViewScope.objects.filter(
                viewer_department=self.dept_x, visible_department=self.dept_y
            ).exists()
        )
        self.assertFalse(AuditLog.objects.filter(action="部署管理 統合").exists())


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

    def test_action_is_updated_when_same_pair_reached_via_different_action(self):
        """以前はget_or_createのdefaultsが新規作成時にしか適用されず、先にsplitで作られた
        (viewer, visible)組を後からmergeで実行してもactionが古い値のまま残っていた
        （コード監査で発見、2026-08-24修正）。update_or_createで常に最新のactionに揃うことを
        確認する。"""
        # SPLIT(department=dept_y, targets=[dept_x]) → viewer=dept_x, visible=dept_y（分割の方向は
        # viewer=対象部署、visible=分割元＝department）。
        apply_dept_action(self.dept_y, DepartmentViewScope.ACTION_SPLIT, [self.dept_x])
        scope = DepartmentViewScope.objects.get(viewer_department=self.dept_x, visible_department=self.dept_y)
        self.assertEqual(scope.action, DepartmentViewScope.ACTION_SPLIT)

        # MERGE(department=dept_x, targets=[dept_y]) → viewer=dept_x, visible=dept_y（統合の方向は
        # viewer=department、visible=対象部署）。上と同じ(viewer, visible)組に別actionで到達する。
        apply_dept_action(self.dept_x, DepartmentViewScope.ACTION_MERGE, [self.dept_y])
        scope.refresh_from_db()
        self.assertEqual(scope.action, DepartmentViewScope.ACTION_MERGE)
        self.assertEqual(DepartmentViewScope.objects.count(), 1)

    def test_self_referential_target_is_skipped(self):
        """DeptEditForm.clean()が既に自己参照をエラーにしているため通常は到達しないが、
        サービス層でも防御することを確認する（コード監査で発見、2026-08-24追加）。"""
        apply_dept_action(self.dept_x, DepartmentViewScope.ACTION_MERGE, [self.dept_x, self.dept_y])
        self.assertFalse(
            DepartmentViewScope.objects.filter(viewer_department=self.dept_x, visible_department=self.dept_x).exists()
        )
        self.assertTrue(
            DepartmentViewScope.objects.filter(viewer_department=self.dept_x, visible_department=self.dept_y).exists()
        )


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


class BranchAndSectionChoicesTests(TestCase):
    """organizations.services.branch_choices/section_choices（accounts.forms.StaffSearchForm・
    organizations.forms.DeptSearchFormで共有、コード監査で発見された重複実装の解消、
    2026-08-24）。"""

    def setUp(self):
        Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        Department.objects.create(
            branch_code="000", branch_name="本店", section_code="99", section_name="退職"
        )

    def test_branch_choices_includes_all_option_and_branches(self):
        choices = branch_choices()
        self.assertIn(("", "(全て)"), choices)
        self.assertIn(("000", "本店"), choices)

    def test_section_choices_excludes_retired_section_code(self):
        choices = section_choices()
        codes = [code for code, _ in choices]
        self.assertIn("01", codes)
        self.assertNotIn("99", codes)


class DepartmentsListTests(TestCase):
    def test_returns_department_fields_as_list(self):
        Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        data = departments_list()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["branch_code"], "000")
        self.assertEqual(data[0]["section_name"], "総務部")

    def test_exclude_retired_true_omits_section_code_99(self):
        # フル監査で発見（2026-08-27）：本支所選択時のJS再構築（departments_pulldown）が
        # section_choices()と異なり退職(99)を除外していなかった不具合の回帰テスト
        # （xlsx 部署管理!B45・職員マスタ!B41）。
        Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        Department.objects.create(
            branch_code="000", branch_name="本店", section_code="99", section_name="退職"
        )
        data = departments_list(exclude_retired=True)
        section_codes = [d["section_code"] for d in data]
        self.assertIn("01", section_codes)
        self.assertNotIn("99", section_codes)

    def test_exclude_retired_false_keeps_section_code_99(self):
        # 職員マスタ登録/編集画面の部署欄は退職への変更を許容するため除外しない。
        Department.objects.create(
            branch_code="000", branch_name="本店", section_code="99", section_name="退職"
        )
        data = departments_list(exclude_retired=False)
        self.assertIn("99", [d["section_code"] for d in data])


class DeptListViewSearchTests(TestCase):
    """screen-dept-listの検索フィルタ・ソート（xlsx 部署管理!B53-56）。"""

    def setUp(self):
        self.dept_a = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.dept_b = Department.objects.create(
            branch_code="999", branch_name="別支店", section_code="02", section_name="経理部"
        )
        self.operator = Employee.objects.create_user(
            employee_no="1", name="操作太郎", password="pass1234",
            department=self.dept_a, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        PermissionProfile.objects.create(employee=self.operator, role=PermissionRole.ADMIN)
        self.client.login(username="1", password="pass1234")

    def test_filter_by_branch_code(self):
        # "総務部"/"経理部"は検索パネルのプルダウン選択肢（絞込み対象外の全選択肢）にも
        # 出るため、レスポンス本文の文字列検索ではなくcontext["departments"]で確認する。
        response = self.client.get("/organizations/", {"branch_code": "999"})
        self.assertEqual(list(response.context["departments"]), [self.dept_b])

    def test_filter_by_section_code(self):
        response = self.client.get("/organizations/", {"section_code": "01"})
        self.assertEqual(list(response.context["departments"]), [self.dept_a])

    def test_sort_by_branch_code_desc(self):
        response = self.client.get("/organizations/", {"sort": "branch_code", "dir": "desc"})
        departments = list(response.context["departments"])
        self.assertEqual(departments[0].branch_code, "999")

    def test_departments_pulldown_excludes_retired_section(self):
        # xlsx 部署管理!B45「(但し部課コード99の退職者は対象外)」がビュー経由でも
        # 効いていることの確認（organizations.services.departments_listのユニットテストとは別に、
        # DeptListView側の呼び出しでexclude_retired=Trueが実際に渡っていることを保証する）。
        Department.objects.create(
            branch_code="000", branch_name="本店", section_code="99", section_name="退職"
        )
        response = self.client.get("/organizations/")
        section_codes = [d["section_code"] for d in response.context["departments_pulldown"]]
        self.assertNotIn("99", section_codes)

    def test_filter_by_branch_code_and_section_code_combined(self):
        """xlsx 部署管理!B53-56の絞り込みは本支所コード・部課コードを同時指定した場合AND条件で
        絞り込む（従来は単独指定のみ検証されていた。テストカバレッジ棚卸しで発見、
        2026-08-26追加）。同一本支所コード内に別の部課コードを持つ部署を用意し、両方指定した
        場合に該当する1件のみに絞られることを確認する。"""
        Department.objects.create(
            branch_code="000", branch_name="本店", section_code="02", section_name="経理部"
        )
        response = self.client.get("/organizations/", {"branch_code": "000", "section_code": "01"})
        self.assertEqual(list(response.context["departments"]), [self.dept_a])

    def test_sort_by_section_code_desc(self):
        """SORT_FIELDSのbranch_code以外（section_code等）が未検証だったため追加
        （テストカバレッジ棚卸しで発見、2026-08-26追加）。"""
        response = self.client.get("/organizations/", {"sort": "section_code", "dir": "desc"})
        departments = list(response.context["departments"])
        self.assertEqual([d.section_code for d in departments], ["02", "01"])

    def test_department_name_with_script_tag_is_escaped_in_pulldown_json(self):
        """本支所→部課連動プルダウンのデータは`departments_json()`を`json.dumps`＋`|safe`で
        scriptタグに直書きしていたため、部課名に`</script>`を仕込まれると格納型XSSになる
        脆弱性があった（セキュリティレビュー2026-08-26で発見・修正）。`|json_script`経由の
        現在の実装では`</script>`が`\u003C/script\u003E`にエスケープされ、レンダリング後の
        HTMLに生の閉じタグとして現れないことを確認する。"""
        Department.objects.create(
            branch_code="777",
            branch_name="</script><script>alert(1)</script>",
            section_code="01",
            section_name="経理部",
        )
        response = self.client.get("/organizations/")
        content = response.content.decode()
        self.assertNotIn("</script><script>alert(1)</script>", content)
        self.assertIn("\\u003C/script\\u003E", content)

    def test_sort_by_branch_name_and_section_name_are_reversible(self):
        """branch_name/section_nameは日本語文字列のためDBの照合順序（Japanese_Japan.utf8）に
        依存し、昇順の絶対的な並び順をハードコードすると環境依存になる。asc/descが互いに
        完全な逆順であることを確認することで、SORT_FIELDS経由でこれらの列が実際に
        並び替えに使われていることを検証する（テストカバレッジ棚卸しで発見、2026-08-26追加）。"""
        for field in ("branch_name", "section_name"):
            asc = [d.pk for d in self.client.get("/organizations/", {"sort": field, "dir": "asc"}).context["departments"]]
            desc = [d.pk for d in self.client.get("/organizations/", {"sort": field, "dir": "desc"}).context["departments"]]
            self.assertEqual(asc, list(reversed(desc)), f"sort={field}")
            self.assertEqual(set(asc), {self.dept_a.pk, self.dept_b.pk})
