from django.core.exceptions import PermissionDenied
from django.test import TestCase

from accounts.models import Employee, Position, Rank
from masters.models import DocKbn, Group
from organizations.models import Department
from permissions.forms import AuthorityEditForm, AuthoritySearchForm
from permissions.models import CSV_EXPORT_FIELDS, FLAG_FIELDS, MULTI_FIELDS, PermissionProfile, PermissionRole
from permissions.services import (
    can_download,
    can_edit_contract,
    can_select_department,
    filter_authority_queryset,
    get_role,
    visible_groups,
)


class PermissionServicesTests(TestCase):
    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.employee = Employee.objects.create_user(
            employee_no="1", name="テスト太郎", password="x",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )

    def test_get_role_defaults_to_staff_without_profile(self):
        """権限プロファイル未設定の職員は最も制限の強い一般扱い。"""
        self.assertEqual(get_role(self.employee), PermissionRole.STAFF)

    def test_get_role_reflects_profile(self):
        PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.ADMIN)
        self.assertEqual(get_role(self.employee), PermissionRole.ADMIN)

    def test_can_select_department_true_only_for_admin(self):
        """xlsx 保管!B79-82「権限管理」で権限が"管理者"のログインユーザのみ表示。"""
        self.assertFalse(can_select_department(self.employee))
        profile = PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.MANAGER)
        self.assertFalse(can_select_department(self.employee))
        profile.role = PermissionRole.ADMIN
        profile.save()
        self.assertTrue(can_select_department(self.employee))

    def test_can_download_false_without_profile(self):
        self.assertFalse(can_download(self.employee, kind="document"))
        self.assertFalse(can_download(self.employee, kind="contract"))

    def test_can_download_reflects_flags(self):
        PermissionProfile.objects.create(
            employee=self.employee, role=PermissionRole.STAFF, doc_download=True, contract_download=False
        )
        self.assertTrue(can_download(self.employee, kind="document"))
        self.assertFalse(can_download(self.employee, kind="contract"))

    def test_can_download_invalid_kind_raises(self):
        PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.STAFF)
        with self.assertRaises(ValueError):
            can_download(self.employee, kind="unknown")

    def test_can_edit_contract_false_without_profile(self):
        """Rev1.2で追加。文書側に対応するフラグは無い（documents.forms/contracts.forms.
        UploadStep2Form.__init__docstring等参照。文書の保存・編集は引き続き無条件で可能）。"""
        self.assertFalse(can_edit_contract(self.employee))

    def test_can_edit_contract_reflects_flag(self):
        profile = PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.STAFF)
        self.assertFalse(can_edit_contract(self.employee))
        profile.contract_edit = True
        profile.save()
        self.assertTrue(can_edit_contract(self.employee))

    def test_can_edit_contract_true_for_admin_regardless_of_flag(self):
        PermissionProfile.objects.create(
            employee=self.employee, role=PermissionRole.ADMIN, contract_edit=False
        )
        self.assertTrue(can_edit_contract(self.employee))

    def test_can_download_true_for_admin_regardless_of_flags(self):
        """xlsx 権限管理!B180「※管理者は、所属長及び職員に対して設定する」。管理者自身は
        フラグ未設定でもダウンロード可（can_select_department/can_edit_retentionと同じ理由）。"""
        PermissionProfile.objects.create(
            employee=self.employee, role=PermissionRole.ADMIN, doc_download=False, contract_download=False
        )
        self.assertTrue(can_download(self.employee, kind="document"))
        self.assertTrue(can_download(self.employee, kind="contract"))

    def test_visible_groups_none_without_profile_means_no_filter(self):
        self.assertIsNone(visible_groups(self.employee, kind="document"))

    def test_visible_groups_none_when_empty_means_no_filter(self):
        """「所属長への権限付与」自体が保留気味の項目であり、未設定を「何も見せない」に
        倒すと検索・保管画面が事実上使えなくなるための方針（permissions/services.py参照）。
        """
        PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.STAFF)
        self.assertIsNone(visible_groups(self.employee, kind="document"))

    def test_visible_groups_returns_configured_queryset(self):
        group_a = Group.objects.create(code="A", name="分類Ａ", doc_kbn=DocKbn.DOCUMENT)
        Group.objects.create(code="B", name="分類Ｂ", doc_kbn=DocKbn.DOCUMENT)
        profile = PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.STAFF)
        profile.doc_visible_groups.add(group_a)
        result = visible_groups(self.employee, kind="document")
        self.assertEqual(list(result.all()), [group_a])

    def test_visible_groups_contract_kind_returns_configured_queryset(self):
        """visible_groups(kind="contract")分岐が未テストだった
        （コード監査で発見、2026-08-25追加）。"""
        contract_group = Group.objects.create(code="C", name="契約分類Ａ", doc_kbn=DocKbn.CONTRACT)
        Group.objects.create(code="D", name="契約分類Ｂ", doc_kbn=DocKbn.CONTRACT)
        profile = PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.STAFF)
        profile.contract_visible_groups.add(contract_group)
        result = visible_groups(self.employee, kind="contract")
        self.assertEqual(list(result.all()), [contract_group])

    def test_visible_groups_invalid_kind_raises(self):
        """can_download()/department_ids_for_group_scope()と同じ理由で想定外のkindを
        握りつぶさない分岐が未テストだった（コード監査で発見、2026-08-25追加）。"""
        PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.STAFF)
        with self.assertRaises(ValueError):
            visible_groups(self.employee, kind="unknown")

    def test_can_select_department_contract_kind_true_with_grant(self):
        """xlsx 検索・閲覧・変更!B421-423(Rev1.1)「権限が"管理者"。または契約書-部門間閲覧設定に
        設定がある場合に表示。」"""
        from permissions.services import can_select_department

        other = Department.objects.create(
            branch_code="999", branch_name="別支店", section_code="", section_name=""
        )
        profile = PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.STAFF)
        self.assertFalse(can_select_department(self.employee, kind="contract"))
        # documentは文書側の仕様（管理者のみ）が変わっていないことも合わせて確認する。
        self.assertFalse(can_select_department(self.employee, kind="document"))
        profile.contract_visible_departments.add(other)
        self.assertTrue(can_select_department(self.employee, kind="contract"))
        self.assertFalse(can_select_department(self.employee, kind="document"))

    def test_contract_searchable_department_ids(self):
        from organizations.models import DepartmentViewScope
        from permissions.services import contract_searchable_department_ids

        merged = Department.objects.create(
            branch_code="888", branch_name="統合元", section_code="", section_name=""
        )
        granted = Department.objects.create(
            branch_code="999", branch_name="権限付与先", section_code="", section_name=""
        )
        DepartmentViewScope.objects.create(
            viewer_department=self.department, visible_department=merged,
            action=DepartmentViewScope.ACTION_MERGE,
        )
        profile = PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.STAFF)
        profile.contract_visible_departments.add(granted)
        self.assertEqual(
            contract_searchable_department_ids(self.employee),
            {self.department.pk, merged.pk, granted.pk},
        )

    def test_contract_searchable_department_ids_none_for_admin(self):
        from permissions.services import contract_searchable_department_ids

        PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.ADMIN)
        self.assertIsNone(contract_searchable_department_ids(self.employee))

    def test_can_edit_retention(self):
        from permissions.services import can_edit_retention

        self.assertFalse(can_edit_retention(self.employee))
        profile = PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.STAFF)
        self.assertFalse(can_edit_retention(self.employee))
        profile.doc_retention_edit = True
        profile.save()
        self.assertTrue(can_edit_retention(self.employee))

    def test_can_edit_retention_true_for_admin_regardless_of_flag(self):
        from permissions.services import can_edit_retention

        PermissionProfile.objects.create(
            employee=self.employee, role=PermissionRole.ADMIN, doc_retention_edit=False
        )
        self.assertTrue(can_edit_retention(self.employee))

    def test_is_admin(self):
        """masters/views.py・permissions/views.py双方でget_role(employee) == PermissionRole.ADMIN
        がベタ書きで重複していたため集約したヘルパー（コード監査で発見、2026-08-24修正）。"""
        from permissions.services import is_admin

        self.assertFalse(is_admin(self.employee))
        profile = PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.MANAGER)
        self.assertFalse(is_admin(self.employee))
        profile.role = PermissionRole.ADMIN
        profile.save()
        self.assertTrue(is_admin(self.employee))

    def test_department_ids_for_group_scope_invalid_kind_raises(self):
        """can_download()と同じ理由：想定外のkindを"document"扱いで握りつぶさない
        （コード監査で発見、2026-08-24修正）。"""
        from permissions.services import department_ids_for_group_scope

        PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.STAFF)
        with self.assertRaises(ValueError):
            department_ids_for_group_scope(self.employee, kind="unknown")

    def test_department_ids_for_group_scope_document_kind(self):
        from permissions.services import department_ids_for_group_scope

        self.assertEqual(
            department_ids_for_group_scope(self.employee, kind="document"), {self.department.pk}
        )
        PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.ADMIN)
        self.assertIsNone(department_ids_for_group_scope(self.employee, kind="document"))


class AuthoritySettingsMenuAccessControlTests(TestCase):
    """設定メニュー「権限管理」は管理者/所属長のみ表示・利用可（xlsx 設定メニュー!B46以降）。
    以前はcore.views.SettingsMenuViewでのボタン非表示のみで、一般ロールでもURLを直接開けば
    一覧に到達できてしまっていた（LoginRequiredMixin止まりだったアクセス制御の穴、
    2026-08-20修正）。permissions.mixins.SettingsMenuAccessMixinの回帰テスト
    （AuthorityEditViewは対象職員単位でcan_manage_target()が既に一般ロールを含め弾くため対象外）。
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

    def test_staff_cannot_access_authority_list(self):
        self._login_as(PermissionRole.STAFF)
        response = self.client.get("/permissions/")
        self.assertEqual(response.status_code, 403)

    def test_staff_cannot_access_authority_csv_export(self):
        self._login_as(PermissionRole.STAFF)
        response = self.client.get("/permissions/csv/")
        self.assertEqual(response.status_code, 403)

    def test_manager_can_access_authority_list(self):
        self._login_as(PermissionRole.MANAGER)
        response = self.client.get("/permissions/")
        self.assertEqual(response.status_code, 200)


class AuthorityListIsAdminViewerContextTests(TestCase):
    """xlsx 権限管理!B35「部署」プルダウンの管理者限定表示に対応するis_admin_viewerフラグの
    回帰テスト（コード監査で発見：context値の分岐が未テストだった、2026-08-25追加）。
    """

    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.employee = Employee.objects.create_user(
            employee_no="1", name="テスト太郎", password="pass1234",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        self.client.login(username="1", password="pass1234")

    def test_admin_viewer_context_true_for_admin(self):
        PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.ADMIN)
        response = self.client.get("/permissions/")
        self.assertTrue(response.context["is_admin_viewer"])

    def test_admin_viewer_context_false_for_manager(self):
        PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.MANAGER)
        response = self.client.get("/permissions/")
        self.assertFalse(response.context["is_admin_viewer"])


class AuthorityListSortTests(TestCase):
    """screen-authority-list列見出しソート（permissions.services.filter_authority_queryset）の
    回帰テスト。「部署」列は`employee.department`（`Department.__str__`=本支所名｜部課名）を
    表示する単一列だが、以前はsection_codeのみでソートしており本支所をまたぐと表示と無関係な
    順序になっていた（documents/contracts検索の「保存情報」列と同じ不具合パターン、
    2026-08-17修正）。
    """

    def setUp(self):
        # 部課コードをあえて本支所と逆順にし、section_codeのみのソートだと本支所をまたいで
        # 混ざることを検証できるようにする。
        self.dept_a = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="99", section_name="総務部"
        )
        self.dept_b = Department.objects.create(
            branch_code="999", branch_name="支店", section_code="01", section_name="営業部"
        )
        self.viewer = Employee.objects.create_user(
            employee_no="1", name="管理者", password="x",
            department=self.dept_a, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        PermissionProfile.objects.create(employee=self.viewer, role=PermissionRole.ADMIN)
        self.emp_a = Employee.objects.create_user(
            employee_no="2", name="部署A所属", password="x",
            department=self.dept_a, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        self.emp_b = Employee.objects.create_user(
            employee_no="3", name="部署B所属", password="x",
            department=self.dept_b, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )

    def test_department_sort_uses_branch_code_before_section_code(self):
        """viewer自身（dept_a所属、employee_no=1）もvisible_employees()の対象に含まれるため、
        同じ部署内のタイブレークはemployee_no昇順で決まる（asc/descとも部署列の向きのみ反転し、
        employee_noの向きは変わらない）。
        """
        form = AuthoritySearchForm(data={})

        asc_qs = filter_authority_queryset(self.viewer, form, sort_key="department", sort_dir="asc")
        self.assertEqual(list(asc_qs), [self.viewer, self.emp_a, self.emp_b])

        desc_qs = filter_authority_queryset(self.viewer, form, sort_key="department", sort_dir="desc")
        self.assertEqual(list(desc_qs), [self.emp_b, self.viewer, self.emp_a])

    def test_default_sort_uses_branch_code_before_section_code(self):
        """xlsx 権限管理!B48-50「初期ソート順は部課コード(本支所コード+部課コードの5桁にて)」。
        dept_a(branch=000, section=99)のほうがdept_b(branch=999, section=01)より部課コードの
        数字自体は大きいが、本支所コードを先にソートするためdept_a側が先に来る。
        """
        form = AuthoritySearchForm(data={})
        qs = filter_authority_queryset(self.viewer, form)
        self.assertEqual(list(qs), [self.viewer, self.emp_a, self.emp_b])

    def test_department_search_condition_filters_results(self):
        """AuthoritySearchFormのdepartmentフィールドによる絞り込み。全テストがこれまで
        空条件（data={}）のみで呼んでいたため、実際に効くかは未検証だった
        （コード監査で発見、2026-08-25追加）。"""
        form = AuthoritySearchForm(data={"department": self.dept_b.pk})
        qs = filter_authority_queryset(self.viewer, form)
        self.assertEqual(list(qs), [self.emp_b])

    def test_name_search_condition_filters_results(self):
        form = AuthoritySearchForm(data={"name": "部署A"})
        qs = filter_authority_queryset(self.viewer, form)
        self.assertEqual(list(qs), [self.emp_a])


class AuthorityEditFormTests(TestCase):
    """権限管理編集フォームは原本の全項目を含むこと（Rev1.1で権限管理!B167-215の構成に
    再編。旧フィールド漏れの再発防止という趣旨を引き継ぎ、新構成の項目一覧を検証する）。
    """

    def test_form_includes_all_flag_fields(self):
        expected_fields = {
            "role",
            "doc_visible_groups",
            "doc_retention_edit",
            "doc_download",
            "contract_visible_departments",
            "contract_visible_groups",
            "contract_edit",
            "contract_download",
            "eapproval_view_setting",
            "eapproval_doc_name_manage",
            "eapproval_retention",
        }
        form = AuthorityEditForm()
        self.assertEqual(expected_fields, set(form.fields.keys()))


class AuthorityEditViewTests(TestCase):
    """xlsx 権限管理!B156「所属長は自分の権限の変更が不可」（要再確認No.2）。"""

    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.employee = Employee.objects.create_user(
            employee_no="1", name="所属長太郎", password="pass1234",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        self.other_employee = Employee.objects.create_user(
            employee_no="2", name="一般太郎", password="pass1234",
            department=self.department, rank=Rank.SHUJI, position=Position.IPPAN,
        )
        self.client.login(username="1", password="pass1234")

    def test_staff_role_cannot_edit_others_permissions(self):
        """can_manage_target()のviewer_role==STAFF（一般ロール）拒否分岐の回帰テスト。
        AuthorityEditViewはSettingsMenuAccessMixinを使わずcan_manage_target()に直接依存するため、
        一般ロールがpk直指定でアクセスした場合の403もこのdispatch()経由で確認する必要がある
        （コード監査で発見：分岐自体は未テストだった、2026-08-25追加）。
        """
        PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.STAFF)
        response = self.client.get(f"/permissions/{self.other_employee.pk}/edit/")
        self.assertEqual(response.status_code, 403)

    def test_manager_cannot_edit_own_permissions(self):
        PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.MANAGER)
        response = self.client.get(f"/permissions/{self.employee.pk}/edit/")
        self.assertEqual(response.status_code, 403)

    def test_manager_can_edit_others_permissions(self):
        PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.MANAGER)
        response = self.client.get(f"/permissions/{self.other_employee.pk}/edit/")
        self.assertEqual(response.status_code, 200)

    def test_admin_can_edit_own_permissions(self):
        PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.ADMIN)
        response = self.client.get(f"/permissions/{self.employee.pk}/edit/")
        self.assertEqual(response.status_code, 200)

    def test_manager_cannot_edit_employee_in_other_department(self):
        """xlsx 権限管理!B113「所属長は自分の部署の"一般"職員のみ権限変更可」（原本フィデリティ
        監査で発見：以前はpk直指定で他部署職員の権限も編集できてしまっていた）。"""
        other_department = Department.objects.create(
            branch_code="999", branch_name="別支店", section_code="", section_name=""
        )
        other_dept_employee = Employee.objects.create_user(
            employee_no="3", name="他部署太郎", password="x",
            department=other_department, rank=Rank.SHUJI, position=Position.IPPAN,
        )
        PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.MANAGER)
        response = self.client.get(f"/permissions/{other_dept_employee.pk}/edit/")
        self.assertEqual(response.status_code, 403)

    def test_manager_cannot_edit_employee_with_manager_role(self):
        """xlsx 権限管理!B113の「"一般"職員のみ」の裏返し：同部署でも所属長・管理者ロールの
        職員は編集不可（原本フィデリティ監査で発見：以前はロール制限が一切無かった）。"""
        PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.MANAGER)
        PermissionProfile.objects.create(employee=self.other_employee, role=PermissionRole.MANAGER)
        response = self.client.get(f"/permissions/{self.other_employee.pk}/edit/")
        self.assertEqual(response.status_code, 403)

    def test_manager_role_field_choices_restricted_to_staff(self):
        """xlsx 権限管理!B153/155「所属長はロールを"職員(一般)"のみ選択可」
        （原本フィデリティ監査で発見：以前はロール選択肢に絞り込みが無かった）。"""
        PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.MANAGER)
        response = self.client.get(f"/permissions/{self.other_employee.pk}/edit/")
        choices = {value for value, _ in response.context["form"].fields["role"].choices}
        self.assertEqual(choices, {PermissionRole.STAFF})

    def test_manager_cannot_escalate_role_via_post(self):
        """フォーム側の選択肢絞り込みだけに頼らず、POSTで直接adminを送っても
        ChoiceFieldのバリデーションで弾かれ、ロールが変更されないことを確認する。"""
        PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.MANAGER)
        get_response = self.client.get(f"/permissions/{self.other_employee.pk}/edit/")
        token = get_response.context["token"]
        response = self.client.post(
            f"/permissions/{self.other_employee.pk}/edit/",
            {"role": PermissionRole.ADMIN, "token": token},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["form"].is_valid())
        self.assertEqual(
            PermissionProfile.objects.get(employee=self.other_employee).role, PermissionRole.STAFF
        )

    def test_post_with_invalid_token_shows_error_and_does_not_save(self):
        """二重送信対策トークン不正時（core.double_submit.consume_tokenがFalseを返すケース）の
        分岐が未テストだった（コード監査で発見、2026-08-25追加）。"""
        PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.ADMIN)
        response = self.client.post(
            f"/permissions/{self.other_employee.pk}/edit/",
            {"role": PermissionRole.ADMIN, "token": "invalid-token"},
            follow=True,
        )
        messages = [str(m) for m in response.context["messages"]]
        self.assertTrue(any("二重に送信された可能性" in m for m in messages))
        self.assertEqual(
            PermissionProfile.objects.get(employee=self.other_employee).role, PermissionRole.STAFF
        )

    def test_update_creates_audit_log(self):
        """原本index.html:3221,3231の操作履歴ログサンプル「権限管理　更新」に対応
        （原本フィデリティ監査で発見：以前は一切記録されていなかった）。"""
        from audit.models import AuditLog

        PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.ADMIN)
        get_response = self.client.get(f"/permissions/{self.other_employee.pk}/edit/")
        token = get_response.context["token"]
        self.client.post(f"/permissions/{self.other_employee.pk}/edit/", {"role": PermissionRole.STAFF, "token": token})
        self.assertTrue(AuditLog.objects.filter(action="権限管理 更新").exists())


class ContractVisibleDepartmentsAdminOnlyTests(TestCase):
    """Rev1.2（xlsx 権限管理!H182「※権限：管理者のみ表示」、2026-08-24反映）で、
    「契約書-部門間閲覧設定」の編集画面での表示・設定が管理者のみに narrow された
    （以前は管理者・所属長どちらも編集可能だった）。
    """

    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.manager = Employee.objects.create_user(
            employee_no="1", name="所属長太郎", password="pass1234",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        PermissionProfile.objects.create(employee=self.manager, role=PermissionRole.MANAGER)
        self.staff = Employee.objects.create_user(
            employee_no="2", name="一般太郎", password="x",
            department=self.department, rank=Rank.SHUJI, position=Position.IPPAN,
        )
        self.other_department = Department.objects.create(
            branch_code="999", branch_name="別支店", section_code="", section_name=""
        )

    def test_manager_editor_does_not_see_contract_visible_departments_field(self):
        self.client.login(username="1", password="pass1234")
        response = self.client.get(f"/permissions/{self.staff.pk}/edit/")
        self.assertNotContains(response, 'name="contract_visible_departments"')
        self.assertContains(response, "管理者のみ設定可")

    def test_manager_post_cannot_set_contract_visible_departments(self):
        """フィールド自体をフォームから除外しているため、POSTで直接値を送っても保存されない
        （AuthorityEditForm.__init__のshow_contract_visible_departments docstring参照）。
        """
        self.client.login(username="1", password="pass1234")
        get_response = self.client.get(f"/permissions/{self.staff.pk}/edit/")
        token = get_response.context["token"]
        self.client.post(
            f"/permissions/{self.staff.pk}/edit/",
            {"role": PermissionRole.STAFF, "token": token, "contract_visible_departments": [self.other_department.pk]},
        )
        profile = PermissionProfile.objects.get(employee=self.staff)
        self.assertEqual(list(profile.contract_visible_departments.all()), [])

    def test_admin_editor_sees_contract_visible_departments_field(self):
        admin = Employee.objects.create_user(
            employee_no="3", name="管理者太郎", password="pass1234",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        PermissionProfile.objects.create(employee=admin, role=PermissionRole.ADMIN)
        self.client.login(username="3", password="pass1234")
        response = self.client.get(f"/permissions/{self.staff.pk}/edit/")
        self.assertContains(response, 'name="contract_visible_departments"')


class AuthorityCsvExportViewTests(TestCase):
    """screen-authority-list「CSV出力」。一覧に表示されている列をそのままCSV化する。"""

    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.employee = Employee.objects.create_user(
            employee_no="1", name="管理者太郎", password="pass1234",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        PermissionProfile.objects.create(
            employee=self.employee, role=PermissionRole.ADMIN, doc_download=True
        )
        self.client.login(username="1", password="pass1234")

    def test_export_contains_header_and_flag_row(self):
        response = self.client.get("/permissions/csv/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8-sig")
        content = response.content.decode("utf-8-sig")
        self.assertIn("職員番号,部署,氏名,役職,権限", content)
        self.assertIn("1,総務部,管理者太郎,課長,管理者", content)

    def test_export_respects_department_scoping_for_manager(self):
        """管理者以外は自部署の職員のみCSVに含まれる（一覧画面と同じ絞込み）。"""
        other_department = Department.objects.create(
            branch_code="999", branch_name="別支店", section_code="", section_name=""
        )
        Employee.objects.create_user(
            employee_no="2", name="別部署太郎", password="x", department=other_department,
            rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        profile = PermissionProfile.objects.get(employee=self.employee)
        profile.role = PermissionRole.MANAGER
        profile.save()
        response = self.client.get("/permissions/csv/")
        content = response.content.decode("utf-8-sig")
        self.assertNotIn("別部署太郎", content)

    def test_export_creates_audit_log_with_personal_info_flag(self):
        """氏名・部署に加え権限フラグという機微な情報を含む一覧ファイル出力のため、
        accounts.StaffCsvExportViewと同様にpersonal_info_flag=Trueで操作履歴ログへ記録すること
        （原本フィデリティ再監査で発見された記録漏れの修正）。
        """
        from audit.models import AuditLog

        self.client.get("/permissions/csv/")
        entry = AuditLog.objects.get(action="権限管理 CSV出力")
        self.assertEqual(entry.employee_no, "1")
        self.assertTrue(entry.personal_info_flag)

    def test_export_escapes_formula_prefixed_name(self):
        """氏名が「=」等で始まる場合、Excel等で開いた際の数式インジェクション対策として
        シングルクォートを付与する（2026-08-24追加、core.csv_services.sanitize_csv_row参照）。"""
        Employee.objects.create_user(
            employee_no="9", name="=cmd|'/c calc'!A1", password="x", department=self.department,
            rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        response = self.client.get("/permissions/csv/")
        content = response.content.decode("utf-8-sig")
        self.assertIn("'=cmd|'/c calc'!A1", content)

    def test_csv_export_fields_matches_flag_and_multi_fields(self):
        """permissions.models.CSV_EXPORT_FIELDSはFLAG_FIELDS/MULTI_FIELDSと過不足なく一致する
        こと。CSV_EXPORT_FIELDSはCSV列の並び順のため機械的に導出できず手書きのままだが
        （permissions/models.py CSV_EXPORT_FIELDS docstring参照）、この一致だけはテストで担保する。
        新しい権限フラグをFLAG_FIELDS/MULTI_FIELDSへ追加してCSV_EXPORT_FIELDSへの追加を
        忘れた場合、ここが真っ先に落ちる（CSVヘッダー・データ列がずれたまま気付かれずリリース
        される事故を防ぐ、コード監査で発見、2026-08-25追加）。
        """
        self.assertEqual(len(CSV_EXPORT_FIELDS), len(set(CSV_EXPORT_FIELDS)))
        self.assertEqual(set(CSV_EXPORT_FIELDS), set(FLAG_FIELDS) | set(MULTI_FIELDS))


class OptionListAPIViewTests(TestCase):
    """screen-authority-editの分類選択・部門間閲覧設定ポップアップが使うpermissions/api.py
    OptionListAPIViewの回帰テスト（コード監査で発見：丸ごと無テストだった、2026-08-25追加）。
    """

    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.employee = Employee.objects.create_user(
            employee_no="1", name="テスト太郎", password="pass1234",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        self.client.login(username="1", password="pass1234")

    def test_group_type_returns_document_groups_by_default(self):
        doc_group = Group.objects.create(code="A", name="文書分類", doc_kbn=DocKbn.DOCUMENT)
        Group.objects.create(code="B", name="契約分類", doc_kbn=DocKbn.CONTRACT)
        response = self.client.get("/permissions/api/options/", {"type": "group"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"items": [{"value": doc_group.pk, "label": "文書分類"}]})

    def test_group_type_returns_contract_groups_with_doc_kbn_param(self):
        Group.objects.create(code="A", name="文書分類", doc_kbn=DocKbn.DOCUMENT)
        contract_group = Group.objects.create(code="B", name="契約分類", doc_kbn=DocKbn.CONTRACT)
        response = self.client.get("/permissions/api/options/", {"type": "group", "doc_kbn": "contract"})
        self.assertEqual(response.json(), {"items": [{"value": contract_group.pk, "label": "契約分類"}]})

    def test_group_type_excludes_deleted_groups(self):
        Group.objects.create(code="A", name="削除済み分類", doc_kbn=DocKbn.DOCUMENT, is_deleted=True)
        response = self.client.get("/permissions/api/options/", {"type": "group"})
        self.assertEqual(response.json(), {"items": []})

    def test_dept_type_returns_all_departments(self):
        other = Department.objects.create(
            branch_code="999", branch_name="別支店", section_code="", section_name=""
        )
        response = self.client.get("/permissions/api/options/", {"type": "dept"})
        values = {item["value"] for item in response.json()["items"]}
        self.assertEqual(values, {self.department.pk, other.pk})

    def test_invalid_type_returns_400(self):
        response = self.client.get("/permissions/api/options/", {"type": "unknown"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"error": "invalid type"})

    def test_requires_login(self):
        self.client.logout()
        response = self.client.get("/permissions/api/options/", {"type": "dept"})
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])


class AuthorityListOperationColumnPositionTests(TestCase):
    """Rev1.2の埋め込み画像モック（権限管理シート、セル文字列では検出できず画像ハッシュ
    突き合わせで発見）は「操作」（編集ボタン）列が「権限」列の直後（フラグ列群より前）に
    移動していた。当初はフラグ列群の後、一番右のままだったため、モック通りの列順に
    修正した（2026-08-24）。
    """

    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.employee = Employee.objects.create_user(
            employee_no="1", name="テスト太郎", password="pass1234",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.ADMIN)
        self.client.login(username="1", password="pass1234")

    def test_operation_column_appears_right_after_role_column(self):
        response = self.client.get("/permissions/")
        content = response.content.decode("utf-8")
        # sort_key未指定時、sort_arrowは全列共通で"▼"を返す（search_extras.sort_arrow参照）ため、
        # 「権限」列見出しは"権限▼"で一意に特定できる（ページ上部の見出し「権限管理一覧」等の
        # 単なる文字列一致と区別するため）。
        role_idx = content.index("権限▼")
        operation_idx = content.index(">操作<")
        grant_idx = content.index(">権限付与<")
        self.assertLess(role_idx, operation_idx)
        self.assertLess(operation_idx, grant_idx)
