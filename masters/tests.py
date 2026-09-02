from unittest.mock import patch

from django.test import TestCase

from accounts.models import Employee, Position, Rank
from masters.forms import CategoryForm, GroupForm, RetentionPeriodForm
from masters.models import Category, DocKbn, Group, RetentionKbn, RetentionPeriod, RetentionPeriodUnit
from organizations.models import Department
from permissions.models import PermissionProfile, PermissionRole


class GroupFormTests(TestCase):
    def setUp(self):
        self.existing = Group.objects.create(code="1", name="分類Ａ", doc_kbn=DocKbn.DOCUMENT)

    def test_duplicate_code_rejected_on_create(self):
        """xlsx 分類管理!B119「分類コードの重複登録は出来ないように制御」。"""
        form = GroupForm(data={"code": "1", "name": "別の分類", "doc_kbn": DocKbn.DOCUMENT})
        self.assertFalse(form.is_valid())

    def test_duplicate_code_rejected_on_update_against_other_record(self):
        """xlsx B161「分類コード変更時の重複更新は出来ないように制御」。"""
        other = Group.objects.create(code="2", name="分類Ｂ", doc_kbn=DocKbn.DOCUMENT)
        form = GroupForm(data={"code": "1", "name": "分類Ｂ改", "doc_kbn": DocKbn.DOCUMENT}, instance=other)
        self.assertFalse(form.is_valid())

    def test_keeping_own_code_on_update_is_allowed(self):
        # show_department=False: これらのテストは分類コードのバリデーションのみを検証する
        # ため、Rev1.2で追加された「部署」フィールド（管理者のみ表示、GroupForm docstring参照）
        # は対象外にする。
        form = GroupForm(
            data={"code": "1", "name": "分類Ａ改名", "doc_kbn": DocKbn.DOCUMENT},
            instance=self.existing,
            show_department=False,
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_deleted_group_code_can_be_reused(self):
        """論理削除(is_deleted)済みの分類コードは重複チェックの対象外とする。"""
        self.existing.is_deleted = True
        self.existing.save()
        form = GroupForm(
            data={"code": "1", "name": "新しい分類Ａ", "doc_kbn": DocKbn.DOCUMENT}, show_department=False
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_fullwidth_code_converted_to_halfwidth(self):
        """xlsx 分類管理!B116(Rev1.1)「半角数字のみ許可する。(全角の場合は登録時に半角へ変換)」。"""
        form = GroupForm(
            data={"code": "３", "name": "分類Ｃ", "doc_kbn": DocKbn.DOCUMENT}, show_department=False
        )
        self.assertTrue(form.is_valid(), form.errors)
        group = form.save()
        self.assertEqual(group.code, "3")

    def test_non_digit_code_rejected(self):
        form = GroupForm(data={"code": "A1", "name": "分類Ｄ", "doc_kbn": DocKbn.DOCUMENT})
        self.assertFalse(form.is_valid())

    def test_doc_kbn_has_no_blank_choice(self):
        """原本index.html:2733-2759の「書類管理区分」selectには空選択肢が無く常に先頭の
        「文書管理」が暗黙選択された状態。Django ModelFormの既定のblank選択肢
        （'---------'）が追加されていないことを確認する（原本フィデリティ監査で発見・修正）。
        """
        form = GroupForm()
        self.assertNotIn(("", "---------"), form.fields["doc_kbn"].choices)

    def test_department_has_no_blank_choice(self):
        """department（Rev1.2追加、管理者のみ表示）もdoc_kbnと同じ理由で空選択肢
        （'---------'）が無いこと。以前はempty_label未指定のまま残っていた
        （コード監査で発見、2026-08-24修正）。"""
        form = GroupForm()
        self.assertIsNone(form.fields["department"].empty_label)


class CategoryFormTests(TestCase):
    def setUp(self):
        self.group = Group.objects.create(code="A", name="分類Ａ", doc_kbn=DocKbn.DOCUMENT)
        self.existing = Category.objects.create(
            code="001", name="カテゴリーＡ", group=self.group, doc_kbn=DocKbn.DOCUMENT
        )

    def test_duplicate_code_rejected(self):
        """xlsx カテゴリー管理!B119「カテゴリーコードの重複登録は出来ないように制御」。"""
        form = CategoryForm(
            data={"code": "001", "name": "別カテゴリー", "group": self.group.pk, "doc_kbn": DocKbn.DOCUMENT}
        )
        self.assertFalse(form.is_valid())

    def test_group_queryset_excludes_deleted(self):
        """xlsx B111「分類管理」で設定した分類名リストを表示。論理削除済みの分類は選べない。"""
        deleted_group = Group.objects.create(code="Z", name="削除済み分類", doc_kbn=DocKbn.DOCUMENT, is_deleted=True)
        form = CategoryForm()
        self.assertNotIn(deleted_group, form.fields["group"].queryset)
        self.assertIn(self.group, form.fields["group"].queryset)

    def test_doc_kbn_and_group_have_no_blank_choice(self):
        """GroupFormTests.test_doc_kbn_has_no_blank_choiceと同じ理由（原本index.html:2890-2923）。"""
        form = CategoryForm()
        self.assertNotIn(("", "---------"), form.fields["doc_kbn"].choices)
        self.assertIsNone(form.fields["group"].empty_label)

    def test_department_has_no_blank_choice(self):
        """GroupFormTests.test_department_has_no_blank_choiceと同じ理由（コード監査で発見、
        2026-08-24修正）。"""
        form = CategoryForm()
        self.assertIsNone(form.fields["department"].empty_label)

    def test_group_queryset_scoped_to_employee_department(self):
        """以前はgroupの選択肢が部署スコープ対象外で、非管理者が自部署では選べない他部署の
        Groupを選択でき、department=自部署・group.department=他部署という部署をまたいだ
        紐付けが作れてしまっていた（コード監査で発見、2026-08-24修正）。"""
        dept_a = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        dept_b = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="02", section_name="経理部"
        )
        group_a = Group.objects.create(code="9001", name="分類Ａ", doc_kbn=DocKbn.DOCUMENT, department=dept_a)
        group_b = Group.objects.create(code="9002", name="分類Ｂ", doc_kbn=DocKbn.DOCUMENT, department=dept_b)
        employee = Employee.objects.create_user(
            employee_no="1", name="テスト太郎", password="x",
            department=dept_a, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        form = CategoryForm(show_department=False, employee=employee)
        self.assertIn(group_a, form.fields["group"].queryset)
        self.assertNotIn(group_b, form.fields["group"].queryset)

    def test_fullwidth_code_converted_to_halfwidth(self):
        """xlsx カテゴリー管理!B113(Rev1.1)「半角数字のみ許可する。(全角の場合は登録時に半角へ変換)」。"""
        # show_department=False: GroupFormTests.test_fullwidth_code_converted_to_halfwidthと同じ理由。
        form = CategoryForm(
            data={"code": "００２", "name": "新カテゴリー", "group": self.group.pk, "doc_kbn": DocKbn.DOCUMENT},
            show_department=False,
        )
        self.assertTrue(form.is_valid(), form.errors)
        category = form.save()
        self.assertEqual(category.code, "002")

    def test_non_digit_code_rejected(self):
        form = CategoryForm(
            data={"code": "CA1", "name": "新カテゴリー", "group": self.group.pk, "doc_kbn": DocKbn.DOCUMENT}
        )
        self.assertFalse(form.is_valid())

    def test_doc_kbn_mismatch_with_group_rejected(self):
        """documents/contractsは書類管理区分ごとにカテゴリー・分類を絞り込む前提のため、
        Category.doc_kbnと選択したGroup.doc_kbnが食い違う組み合わせは登録できない
        （コード監査で発見、2026-08-25追加。原本HTMLにはUI側の選択肢絞り込みJSは無いが、
        バックエンド検証のみ追加する方針をユーザーに確認済み）。"""
        contract_group = Group.objects.create(code="B", name="分類Ｂ", doc_kbn=DocKbn.CONTRACT)
        form = CategoryForm(
            data={
                "code": "002", "name": "新カテゴリー", "group": contract_group.pk, "doc_kbn": DocKbn.DOCUMENT,
            },
            show_department=False,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("group", form.errors)

    def test_doc_kbn_matching_group_accepted(self):
        form = CategoryForm(
            data={"code": "002", "name": "新カテゴリー", "group": self.group.pk, "doc_kbn": DocKbn.DOCUMENT},
            show_department=False,
        )
        self.assertTrue(form.is_valid(), form.errors)


class CategorySearchFormTests(TestCase):
    """CategorySearchForm.__init__のemployee引数によるgroup選択肢の部署スコープ絞り込み
    （検索パネルの「分類」プルダウン自体を自部署のグループのみに絞る処理）。CategoryForm側の
    同種ロジック（CategoryFormTests.test_group_queryset_scoped_to_employee_department）は
    検証済みだが検索フォーム側は未検証だった（テストカバレッジ棚卸しで発見、2026-08-26追加）。
    """

    def test_group_queryset_scoped_to_employee_department(self):
        from masters.forms import CategorySearchForm

        dept_a = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        dept_b = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="02", section_name="経理部"
        )
        group_a = Group.objects.create(code="9001", name="分類Ａ", doc_kbn=DocKbn.DOCUMENT, department=dept_a)
        group_b = Group.objects.create(code="9002", name="分類Ｂ", doc_kbn=DocKbn.DOCUMENT, department=dept_b)
        employee = Employee.objects.create_user(
            employee_no="1", name="テスト太郎", password="x",
            department=dept_a, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        form = CategorySearchForm(employee=employee)
        self.assertIn(group_a, form.fields["group"].queryset)
        self.assertNotIn(group_b, form.fields["group"].queryset)

    def test_group_queryset_unscoped_without_employee(self):
        """employee未指定時（実際は使われないが、CategorySearchForm(request.GET)単体テストと
        しての防御的確認）は絞り込みが適用されないこと。"""
        from masters.forms import CategorySearchForm

        dept = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        group = Group.objects.create(code="9003", name="分類Ｃ", doc_kbn=DocKbn.DOCUMENT, department=dept)
        form = CategorySearchForm()
        self.assertIn(group, form.fields["group"].queryset)


class RetentionPeriodModelTests(TestCase):
    """RetentionPeriod.__str__ の永年/通常の2分岐（従来は audit_services.log 経由で
    間接的に文字列化されるのみで、直接検証するテストが無かった）。"""

    def test_str_permanent_ignores_period_value(self):
        rp = RetentionPeriod(
            kbn=RetentionKbn.DOCUMENT, period_value=None,
            period_unit=RetentionPeriodUnit.PERMANENT, display_order=1,
        )
        self.assertEqual(str(rp), "永年")

    def test_str_year_and_month_use_unit_display(self):
        year = RetentionPeriod(
            kbn=RetentionKbn.DOCUMENT, period_value=5,
            period_unit=RetentionPeriodUnit.YEAR, display_order=1,
        )
        month = RetentionPeriod(
            kbn=RetentionKbn.DOCUMENT, period_value=6,
            period_unit=RetentionPeriodUnit.MONTH, display_order=2,
        )
        self.assertEqual(str(year), "5年")
        self.assertEqual(str(month), "6ヵ月")


class RetentionPeriodFormTests(TestCase):
    def setUp(self):
        self.existing = RetentionPeriod.objects.create(
            kbn=RetentionKbn.DOCUMENT, period_value=1, period_unit=RetentionPeriodUnit.YEAR, display_order=1
        )

    def _data(self, **overrides):
        data = {
            "kbn": RetentionKbn.DOCUMENT,
            "doc_name": "",
            "period_value": "3",
            "period_unit": RetentionPeriodUnit.YEAR,
            "display_order": "2",
        }
        data.update(overrides)
        return data

    def test_duplicate_display_order_within_same_kbn_rejected(self):
        """xlsx 保存期間設定!B77「保存期間や表示順の重複登録は出来ないように制御」。"""
        form = RetentionPeriodForm(data=self._data(display_order="1"))
        self.assertFalse(form.is_valid())

    def test_same_display_order_in_different_kbn_allowed(self):
        """区分(kbn)が違えば表示順は重複してよい（同一区分内のみ一意）。"""
        form = RetentionPeriodForm(
            data=self._data(kbn=RetentionKbn.EAPPROVAL, doc_name="ringisho", display_order="1")
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_permanent_clears_period_value(self):
        """xlsx B73「「永年」を選択した場合「保存期間」の数値をクリアし、数値を入力出来ないようにする」。"""
        form = RetentionPeriodForm(data=self._data(period_value="5", period_unit=RetentionPeriodUnit.PERMANENT))
        self.assertTrue(form.is_valid(), form.errors)
        period = form.save()
        self.assertIsNone(period.period_value)
        self.assertEqual(period.period_unit, RetentionPeriodUnit.PERMANENT)

    def test_non_permanent_without_value_rejected(self):
        form = RetentionPeriodForm(data=self._data(period_value="", period_unit=RetentionPeriodUnit.YEAR))
        self.assertFalse(form.is_valid())

    def test_period_unit_has_no_blank_choice(self):
        """原本index.html:3058-3099の「期間単位」selectには空選択肢が無く常に先頭の「ヵ月」が
        暗黙選択された状態（原本フィデリティ監査で発見・修正）。"""
        form = RetentionPeriodForm()
        self.assertNotIn(("", "---------"), form.fields["period_unit"].choices)


class MasterSettingsMenuAccessControlTests(TestCase):
    """設定メニュー「分類管理」は管理者/所属長、「保存期間設定」は管理者のみ表示・利用可
    （xlsx 設定メニュー!B46以降）。「カテゴリー管理」は全ロールに表示され制限なし。
    以前はcore.views.SettingsMenuViewでのボタン非表示のみで、URLを直接開けば範囲外のロールでも
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

    def test_staff_cannot_access_class_list(self):
        self._login_as(PermissionRole.STAFF)
        response = self.client.get("/masters/class/")
        self.assertEqual(response.status_code, 403)

    def test_manager_can_access_class_list(self):
        self._login_as(PermissionRole.MANAGER)
        response = self.client.get("/masters/class/")
        self.assertEqual(response.status_code, 200)

    def test_manager_cannot_access_retention_list(self):
        self._login_as(PermissionRole.MANAGER)
        response = self.client.get("/masters/retention/")
        self.assertEqual(response.status_code, 403)

    def test_staff_can_access_category_list(self):
        """カテゴリー管理はxlsx表で全ロール(管理者/所属長/一般)に○のため制限なし。"""
        self._login_as(PermissionRole.STAFF)
        response = self.client.get("/masters/cat/")
        self.assertEqual(response.status_code, 200)

    def test_admin_can_access_retention_list(self):
        self._login_as(PermissionRole.ADMIN)
        response = self.client.get("/masters/retention/")
        self.assertEqual(response.status_code, 200)

    def test_category_views_actually_enforce_settings_menu_role_check(self):
        """CategoryListView/CategoryRegistView/CategoryEditView/CategoryDeleteViewは
        以前SettingsMenuAccessMixinを一切参照しておらず、category_managementキーの
        ロール制限がView側で実質チェックされていなかった（現状は全ロール許可のため
        実害は無いが、将来ロール制限を絞った際に反映されない潜在バグだった。コード監査で
        発見、2026-08-24修正）。SETTINGS_MENU_VISIBLE_ROLESを一時的に管理者限定へ差し替えて
        実際にチェックが働くことを確認する。
        """
        from unittest.mock import patch as mock_patch

        employee = self._login_as(PermissionRole.STAFF)
        group = Group.objects.create(code="1", name="分類Ａ", doc_kbn=DocKbn.DOCUMENT, department=self.department)
        category = Category.objects.create(
            code="001", name="カテゴリーＡ", group=group, doc_kbn=DocKbn.DOCUMENT, department=self.department
        )
        with mock_patch.dict(
            "permissions.services.SETTINGS_MENU_VISIBLE_ROLES", {"category_management": {PermissionRole.ADMIN}}
        ):
            self.assertEqual(self.client.get("/masters/cat/").status_code, 403)
            self.assertEqual(self.client.get("/masters/cat/regist/").status_code, 403)
            self.assertEqual(self.client.get(f"/masters/cat/{category.pk}/edit/").status_code, 403)
            self.assertEqual(self.client.get(f"/masters/cat/{category.pk}/delete/").status_code, 403)


class MasterDeleteViewTests(TestCase):
    """screen-class-delete/screen-cat-delete: 文書件数0件の場合のみ削除できる（xlsx分類管理!B68）。"""

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
        self.group_with_docs = Group.objects.create(code="A", name="分類Ａ", doc_kbn=DocKbn.DOCUMENT)
        self.group_empty = Group.objects.create(code="B", name="分類Ｂ", doc_kbn=DocKbn.DOCUMENT)
        self.category = Category.objects.create(
            code="001", name="カテゴリーＡ", group=self.group_with_docs, doc_kbn=DocKbn.DOCUMENT
        )
        self.retention_period = RetentionPeriod.objects.create(
            kbn=RetentionKbn.DOCUMENT, period_value=1, period_unit=RetentionPeriodUnit.YEAR, display_order=1
        )

        from django.core.files.base import ContentFile
        from django.utils import timezone

        from documents.models import Document

        self.document = Document(
            title="テスト文書",
            department=self.department,
            group=self.group_with_docs,
            category=self.category,
            year=2026,
            retention_period=self.retention_period,
            uploader=self.employee,
            expiry_date=timezone.localdate(),
        )
        self.document.file.save("test.pdf", ContentFile(b"dummy"), save=False)
        self.document.save()

    def test_group_with_documents_cannot_be_deleted(self):
        response = self.client.get(f"/masters/class/{self.group_with_docs.pk}/delete/")
        token = response.context["token"]
        self.client.post(f"/masters/class/{self.group_with_docs.pk}/delete/", {"token": token})
        self.group_with_docs.refresh_from_db()
        self.assertFalse(self.group_with_docs.is_deleted)

    def test_group_without_documents_can_be_deleted(self):
        response = self.client.get(f"/masters/class/{self.group_empty.pk}/delete/")
        token = response.context["token"] if response.context else None
        # トークン取得はレンダリング結果からではなくissue_tokenの仕組み上セッションからも取れるが、
        # ここではGETレスポンスのcontextを使う（テストクライアントはcontext保持）。
        response2 = self.client.post(f"/masters/class/{self.group_empty.pk}/delete/", {"token": token})
        self.group_empty.refresh_from_db()
        self.assertTrue(self.group_empty.is_deleted)

    def test_retention_period_referenced_by_document_can_be_logically_deleted(self):
        """論理削除（is_deleted=True）は行を消さないため、documents.Document.retention_period
        （on_delete=PROTECT）から参照中でも削除できる。既存文書は参照を維持したまま残る。
        """
        response = self.client.get(f"/masters/retention/{self.retention_period.pk}/delete/")
        token = response.context["token"]
        self.client.post(f"/masters/retention/{self.retention_period.pk}/delete/", {"token": token})
        self.retention_period.refresh_from_db()
        self.assertTrue(self.retention_period.is_deleted)
        self.document.refresh_from_db()
        self.assertEqual(self.document.retention_period_id, self.retention_period.pk)


class ContractSideMasterCountTests(TestCase):
    """masters/views.pyのGroupListView/CategoryListView/GroupDeleteView/CategoryDeleteViewの
    契約書管理側(doc_kbn=contract)のitem_count/blocking_count集計（Case文のdefault分岐、
    contract_count使用）は文書管理側でしか検証されておらず丸ごと無テストだった
    （テストカバレッジ棚卸しで発見、2026-08-26追加）。
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

    def _create_contract(self, group, category):
        from django.core.files.base import ContentFile
        from django.utils import timezone

        from contracts.models import Contract

        contract = Contract(
            title="テスト契約書", department=self.department, group=group, category=category,
            year=2026, uploader=self.employee, expiry_date=timezone.localdate(),
        )
        contract.file.save("test.pdf", ContentFile(b"dummy"), save=False)
        contract.save()
        return contract

    def test_group_list_counts_contracts_for_contract_doc_kbn(self):
        group = Group.objects.create(
            code="C1", name="契約分類", doc_kbn=DocKbn.CONTRACT, department=self.department
        )
        category = Category.objects.create(
            code="CC1", name="契約カテゴリ", group=group, doc_kbn=DocKbn.CONTRACT, department=self.department
        )
        self._create_contract(group, category)
        self._create_contract(group, category)
        response = self.client.get("/masters/class/", {"doc_kbn": DocKbn.CONTRACT})
        item = list(response.context["page_obj"])[0]
        self.assertEqual(item.item_count, 2)

    def test_category_list_counts_contracts_for_contract_doc_kbn(self):
        group = Group.objects.create(
            code="C2", name="契約分類2", doc_kbn=DocKbn.CONTRACT, department=self.department
        )
        category = Category.objects.create(
            code="CC2", name="契約カテゴリ2", group=group, doc_kbn=DocKbn.CONTRACT, department=self.department
        )
        self._create_contract(group, category)
        response = self.client.get("/masters/cat/", {"doc_kbn": DocKbn.CONTRACT})
        item = list(response.context["page_obj"])[0]
        self.assertEqual(item.item_count, 1)

    def test_group_with_contracts_cannot_be_deleted(self):
        group = Group.objects.create(
            code="C3", name="契約分類3", doc_kbn=DocKbn.CONTRACT, department=self.department
        )
        category = Category.objects.create(
            code="CC3", name="契約カテゴリ3", group=group, doc_kbn=DocKbn.CONTRACT, department=self.department
        )
        self._create_contract(group, category)
        token = self.client.get(f"/masters/class/{group.pk}/delete/").context["token"]
        self.client.post(f"/masters/class/{group.pk}/delete/", {"token": token})
        group.refresh_from_db()
        self.assertFalse(group.is_deleted)

    def test_category_with_contracts_cannot_be_deleted(self):
        group = Group.objects.create(
            code="C4", name="契約分類4", doc_kbn=DocKbn.CONTRACT, department=self.department
        )
        category = Category.objects.create(
            code="CC4", name="契約カテゴリ4", group=group, doc_kbn=DocKbn.CONTRACT, department=self.department
        )
        self._create_contract(group, category)
        token = self.client.get(f"/masters/cat/{category.pk}/delete/").context["token"]
        self.client.post(f"/masters/cat/{category.pk}/delete/", {"token": token})
        category.refresh_from_db()
        self.assertFalse(category.is_deleted)


class MasterListSortTests(TestCase):
    """screen-class-list/screen-cat-listの列見出しソート（xlsx 分類管理!B55-58、
    カテゴリー管理!B57-61「下記項目に▲▼ボタンにて昇順/降順切替が可能なようにする。
    (文書検索画面の一覧表示部と機能同等)」）を、ユーザー指示（2026-08-17）により追加した
    回帰テスト。
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
        self.retention_period = RetentionPeriod.objects.create(
            kbn=RetentionKbn.DOCUMENT, period_value=1, period_unit=RetentionPeriodUnit.YEAR, display_order=1
        )

    def _attach_documents(self, group, category, count):
        from django.core.files.base import ContentFile
        from django.utils import timezone

        from documents.models import Document

        for _ in range(count):
            document = Document(
                title="テスト文書", department=self.department, group=group, category=category,
                year=2026, retention_period=self.retention_period, uploader=self.employee,
                expiry_date=timezone.localdate(),
            )
            document.file.save("test.pdf", ContentFile(b"dummy"), save=False)
            document.save()

    def test_group_list_sorts_by_code_name_and_count(self):
        group_a = Group.objects.create(code="A1", name="Zグループ", doc_kbn=DocKbn.DOCUMENT)
        group_b = Group.objects.create(code="B2", name="Aグループ", doc_kbn=DocKbn.DOCUMENT)
        # group_bのカテゴリーは削除ボタン有効化条件（文書件数0件）検証に関係しないダミー。
        category_a = Category.objects.create(code="CA1", name="カテゴリA", group=group_a, doc_kbn=DocKbn.DOCUMENT)
        category_b = Category.objects.create(code="CB2", name="カテゴリB", group=group_b, doc_kbn=DocKbn.DOCUMENT)
        self._attach_documents(group_a, category_a, 1)
        self._attach_documents(group_b, category_b, 3)

        code_asc = self.client.get("/masters/class/", {"sort": "code", "dir": "asc"})
        self.assertEqual(list(code_asc.context["page_obj"]), [group_a, group_b])

        name_asc = self.client.get("/masters/class/", {"sort": "name", "dir": "asc"})
        self.assertEqual(list(name_asc.context["page_obj"]), [group_b, group_a])

        count_asc = self.client.get("/masters/class/", {"sort": "count", "dir": "asc"})
        self.assertEqual(list(count_asc.context["page_obj"]), [group_a, group_b])

        count_desc = self.client.get("/masters/class/", {"sort": "count", "dir": "desc"})
        self.assertEqual(list(count_desc.context["page_obj"]), [group_b, group_a])

    def test_group_list_name_is_partial_match_search(self):
        """xlsx 分類管理!B35-36(Rev1.1)「分類名はプルダウン選択からテキスト部分一致検索に変更」。"""
        group_a = Group.objects.create(code="A1", name="総務分類", doc_kbn=DocKbn.DOCUMENT)
        group_b = Group.objects.create(code="B2", name="経理分類", doc_kbn=DocKbn.DOCUMENT)
        response = self.client.get("/masters/class/", {"name": "総務"})
        self.assertEqual(list(response.context["page_obj"]), [group_a])
        self.assertNotIn(group_b, list(response.context["page_obj"]))

    def test_category_list_sorts_by_code_group_and_count(self):
        """「分類」列は分類名のみを表示する単一列だが、xlsxが分類コード・分類名の2項目を
        挙げているため分類コード→分類名の複合ソートにしている（masters.views.CategoryListView
        docstring参照）。分類コードの順序が分類の並びと逆になるよう意図的に組んで、
        カテゴリー自身のcodeではなく分類(group)の側でソートされていることを検証する。
        """
        group_x = Group.objects.create(code="X1", name="Xグループ", doc_kbn=DocKbn.DOCUMENT)
        group_y = Group.objects.create(code="Y2", name="Yグループ", doc_kbn=DocKbn.DOCUMENT)
        category_a = Category.objects.create(code="C1", name="カテゴリA", group=group_y, doc_kbn=DocKbn.DOCUMENT)
        category_b = Category.objects.create(code="C2", name="カテゴリB", group=group_x, doc_kbn=DocKbn.DOCUMENT)
        self._attach_documents(group_y, category_a, 1)
        self._attach_documents(group_x, category_b, 3)

        code_asc = self.client.get("/masters/cat/", {"sort": "code", "dir": "asc"})
        self.assertEqual(list(code_asc.context["page_obj"]), [category_a, category_b])

        group_asc = self.client.get("/masters/cat/", {"sort": "group", "dir": "asc"})
        self.assertEqual(list(group_asc.context["page_obj"]), [category_b, category_a])

        count_asc = self.client.get("/masters/cat/", {"sort": "count", "dir": "asc"})
        self.assertEqual(list(count_asc.context["page_obj"]), [category_a, category_b])

        count_desc = self.client.get("/masters/cat/", {"sort": "count", "dir": "desc"})
        self.assertEqual(list(count_desc.context["page_obj"]), [category_b, category_a])

    def test_group_list_doc_kbn_filter(self):
        """GroupSearchForm.doc_kbnによる絞り込み自体が未テストだった
        （テストカバレッジ棚卸しで発見、2026-08-26追加）。"""
        group_doc = Group.objects.create(code="D1", name="文書分類", doc_kbn=DocKbn.DOCUMENT)
        group_contract = Group.objects.create(code="C1", name="契約分類", doc_kbn=DocKbn.CONTRACT)
        response = self.client.get("/masters/class/", {"doc_kbn": DocKbn.CONTRACT})
        self.assertEqual(list(response.context["page_obj"]), [group_contract])
        self.assertNotIn(group_doc, list(response.context["page_obj"]))

    def test_category_list_doc_kbn_filter(self):
        group = Group.objects.create(code="G1", name="共通分類", doc_kbn=DocKbn.DOCUMENT)
        cat_doc = Category.objects.create(code="CD1", name="文書カテゴリ", group=group, doc_kbn=DocKbn.DOCUMENT)
        cat_contract = Category.objects.create(
            code="CC1", name="契約カテゴリ", group=group, doc_kbn=DocKbn.CONTRACT
        )
        response = self.client.get("/masters/cat/", {"doc_kbn": DocKbn.CONTRACT})
        self.assertEqual(list(response.context["page_obj"]), [cat_contract])
        self.assertNotIn(cat_doc, list(response.context["page_obj"]))

    def test_category_list_name_is_partial_match_search(self):
        """MasterListSortTests.test_group_list_name_is_partial_match_searchと同じ理由だが、
        Category側の対応するテストが無かった（テストカバレッジ棚卸しで発見、2026-08-26追加）。"""
        group = Group.objects.create(code="G2", name="共通分類2", doc_kbn=DocKbn.DOCUMENT)
        cat_a = Category.objects.create(code="CA1", name="総務カテゴリ", group=group, doc_kbn=DocKbn.DOCUMENT)
        cat_b = Category.objects.create(code="CB1", name="経理カテゴリ", group=group, doc_kbn=DocKbn.DOCUMENT)
        response = self.client.get("/masters/cat/", {"name": "総務"})
        self.assertEqual(list(response.context["page_obj"]), [cat_a])
        self.assertNotIn(cat_b, list(response.context["page_obj"]))

    def test_category_list_group_filter(self):
        group_x = Group.objects.create(code="GX", name="Xグループ", doc_kbn=DocKbn.DOCUMENT)
        group_y = Group.objects.create(code="GY", name="Yグループ", doc_kbn=DocKbn.DOCUMENT)
        cat_x = Category.objects.create(code="CX1", name="カテゴリX", group=group_x, doc_kbn=DocKbn.DOCUMENT)
        cat_y = Category.objects.create(code="CY1", name="カテゴリY", group=group_y, doc_kbn=DocKbn.DOCUMENT)
        response = self.client.get("/masters/cat/", {"group": group_x.pk})
        self.assertEqual(list(response.context["page_obj"]), [cat_x])
        self.assertNotIn(cat_y, list(response.context["page_obj"]))


class RetentionListViewContentTests(TestCase):
    """RetentionListViewはアクセス制御のみ検証されており、`kbn`/`doc_name`クエリパラメータが
    不正値の場合のフォールバック、および3つのqueryset（doc_periods/ringisho_periods/
    keihi_periods）の内容自体が一度も検証されていなかった（テストカバレッジ棚卸しで発見、
    2026-08-26追加）。
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

    def test_invalid_kbn_falls_back_to_document(self):
        response = self.client.get("/masters/retention/", {"kbn": "bogus"})
        self.assertEqual(response.context["selected_kbn"], RetentionKbn.DOCUMENT)

    def test_invalid_doc_name_falls_back_to_ringisho(self):
        response = self.client.get(
            "/masters/retention/", {"kbn": RetentionKbn.EAPPROVAL, "doc_name": "bogus"}
        )
        self.assertEqual(response.context["selected_doc_name"], "ringisho")

    def test_querysets_filtered_by_kbn_and_doc_name(self):
        doc_period = RetentionPeriod.objects.create(
            kbn=RetentionKbn.DOCUMENT, period_value=1, period_unit=RetentionPeriodUnit.YEAR, display_order=1
        )
        ringisho_period = RetentionPeriod.objects.create(
            kbn=RetentionKbn.EAPPROVAL, doc_name="ringisho", period_value=2,
            period_unit=RetentionPeriodUnit.YEAR, display_order=1,
        )
        keihi_period = RetentionPeriod.objects.create(
            kbn=RetentionKbn.EAPPROVAL, doc_name="keihi", period_value=3,
            period_unit=RetentionPeriodUnit.YEAR, display_order=1,
        )
        # 論理削除済みは各querysetから除外される（is_deleted=Falseフィルタ）ことも併せて確認する。
        deleted_doc_period = RetentionPeriod.objects.create(
            kbn=RetentionKbn.DOCUMENT, period_value=9, period_unit=RetentionPeriodUnit.YEAR,
            display_order=2, is_deleted=True,
        )
        response = self.client.get("/masters/retention/")
        self.assertEqual(list(response.context["doc_periods"]), [doc_period])
        self.assertEqual(list(response.context["ringisho_periods"]), [ringisho_period])
        self.assertEqual(list(response.context["keihi_periods"]), [keihi_period])
        self.assertNotIn(deleted_doc_period, list(response.context["doc_periods"]))


class MasterDoubleSubmitTokenTests(TestCase):
    """二重送信対策トークン不正時の分岐が両アプリの全regist/edit/delete Viewで一貫して
    未テストだった（2026-08-25付permissions/accounts棚卸しの中優先度7と同一パターン。
    テストカバレッジ棚卸しで発見、2026-08-26追加）。GroupRegistView/GroupEditView/
    GroupDeleteViewはcore.master_views.BaseScopedMaster*Viewの共通実装をCategory側と
    完全に共有しているため、Group側で検証すれば実装の妥当性としては十分と判断し、Category側は
    重複テストとして省略する。RetentionRegistView/RetentionEditView/RetentionDeleteViewは
    独立した実装のため個別に検証する。
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

    def test_group_regist_invalid_token_shows_error_and_does_not_save(self):
        response = self.client.post(
            "/masters/class/regist/",
            {
                "token": "invalid-token", "code": "1", "name": "分類Ａ", "doc_kbn": DocKbn.DOCUMENT,
                "department": self.department.pk,
            },
            follow=True,
        )
        messages = [str(m) for m in response.context["messages"]]
        self.assertTrue(any("二重に送信された可能性" in m for m in messages))
        self.assertFalse(Group.objects.filter(code="1").exists())

    def test_group_edit_invalid_token_shows_error_and_does_not_save(self):
        group = Group.objects.create(code="1", name="分類Ａ", doc_kbn=DocKbn.DOCUMENT, department=self.department)
        response = self.client.post(
            f"/masters/class/{group.pk}/edit/",
            {
                "token": "invalid-token", "code": "1", "name": "分類Ａ改", "doc_kbn": DocKbn.DOCUMENT,
                "department": self.department.pk,
            },
            follow=True,
        )
        messages = [str(m) for m in response.context["messages"]]
        self.assertTrue(any("二重に送信された可能性" in m for m in messages))
        group.refresh_from_db()
        self.assertEqual(group.name, "分類Ａ")

    def test_group_delete_invalid_token_shows_error_and_does_not_delete(self):
        group = Group.objects.create(code="1", name="分類Ａ", doc_kbn=DocKbn.DOCUMENT, department=self.department)
        response = self.client.post(
            f"/masters/class/{group.pk}/delete/", {"token": "invalid-token"}, follow=True
        )
        messages = [str(m) for m in response.context["messages"]]
        self.assertTrue(any("二重に送信された可能性" in m for m in messages))
        group.refresh_from_db()
        self.assertFalse(group.is_deleted)

    def test_retention_regist_invalid_token_shows_error_and_does_not_save(self):
        response = self.client.post(
            "/masters/retention/regist/",
            {
                "token": "invalid-token", "kbn": RetentionKbn.DOCUMENT, "doc_name": "",
                "period_value": "3", "period_unit": RetentionPeriodUnit.YEAR, "display_order": "1",
            },
            follow=True,
        )
        messages = [str(m) for m in response.context["messages"]]
        self.assertTrue(any("二重に送信された可能性" in m for m in messages))
        self.assertFalse(RetentionPeriod.objects.filter(kbn=RetentionKbn.DOCUMENT, display_order=1).exists())

    def test_retention_edit_invalid_token_shows_error_and_does_not_save(self):
        period = RetentionPeriod.objects.create(
            kbn=RetentionKbn.DOCUMENT, period_value=1, period_unit=RetentionPeriodUnit.YEAR, display_order=1
        )
        response = self.client.post(
            f"/masters/retention/{period.pk}/edit/",
            {
                "token": "invalid-token", "kbn": RetentionKbn.DOCUMENT, "doc_name": "",
                "period_value": "9", "period_unit": RetentionPeriodUnit.YEAR, "display_order": "1",
            },
            follow=True,
        )
        messages = [str(m) for m in response.context["messages"]]
        self.assertTrue(any("二重に送信された可能性" in m for m in messages))
        period.refresh_from_db()
        self.assertEqual(period.period_value, 1)

    def test_retention_delete_invalid_token_shows_error_and_does_not_delete(self):
        period = RetentionPeriod.objects.create(
            kbn=RetentionKbn.DOCUMENT, period_value=1, period_unit=RetentionPeriodUnit.YEAR, display_order=1
        )
        response = self.client.post(
            f"/masters/retention/{period.pk}/delete/", {"token": "invalid-token"}, follow=True
        )
        messages = [str(m) for m in response.context["messages"]]
        self.assertTrue(any("二重に送信された可能性" in m for m in messages))
        period.refresh_from_db()
        self.assertFalse(period.is_deleted)


class MasterDefaultOrderByTests(TestCase):
    """GroupListView/CategoryListViewの`default_order_by`（sortパラメータ省略時の
    部課コード→コード順の初期表示）が直接検証されていなかった（明示的なsort指定時の
    並び替えのみ検証されていた。テストカバレッジ棚卸しで発見、2026-08-26追加）。

    doc_kbnはorder_byの最終キー（_DOC_KBN_ORDER）だが、code自体がis_deleted=False同士で
    グローバルに一意（models.Group/Category Meta.constraints）のため、同一部署・同一コードで
    doc_kbnのみ異なる2件は作成できず、doc_kbnタイブレークが実際に効く場面は事実上無い。
    そのため本テストは部課コード→コードの複合キー部分のみを検証する。
    """

    def setUp(self):
        self.dept_a = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.dept_b = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="02", section_name="経理部"
        )
        self.admin = Employee.objects.create_user(
            employee_no="1", name="管理者", password="pass1234",
            department=self.dept_a, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        PermissionProfile.objects.create(employee=self.admin, role=PermissionRole.ADMIN)
        self.client.login(username="1", password="pass1234")

    def test_group_list_default_order_is_department_then_code(self):
        # 作成順をあえて並び順と逆にし、DBの挿入順ではなくdefault_order_byが効いていることを
        # 確認する。
        g_b2 = Group.objects.create(code="9", name="G-B2", doc_kbn=DocKbn.DOCUMENT, department=self.dept_b)
        g_a2 = Group.objects.create(code="8", name="G-A2", doc_kbn=DocKbn.DOCUMENT, department=self.dept_a)
        g_a1 = Group.objects.create(code="1", name="G-A1", doc_kbn=DocKbn.DOCUMENT, department=self.dept_a)
        response = self.client.get("/masters/class/")
        self.assertEqual(list(response.context["page_obj"]), [g_a1, g_a2, g_b2])

    def test_category_list_default_order_is_department_then_code(self):
        group = Group.objects.create(code="G", name="共通分類", doc_kbn=DocKbn.DOCUMENT)
        c_b2 = Category.objects.create(
            code="9", name="C-B2", group=group, doc_kbn=DocKbn.DOCUMENT, department=self.dept_b
        )
        c_a2 = Category.objects.create(
            code="8", name="C-A2", group=group, doc_kbn=DocKbn.DOCUMENT, department=self.dept_a
        )
        c_a1 = Category.objects.create(
            code="1", name="C-A1", group=group, doc_kbn=DocKbn.DOCUMENT, department=self.dept_a
        )
        response = self.client.get("/masters/cat/")
        self.assertEqual(list(response.context["page_obj"]), [c_a1, c_a2, c_b2])


def _noop_validate_constraints(self, exclude=None):
    """テスト専用のno-op。Django 5.2はModelForm.is_valid()の中でModel.full_clean()経由の
    validate_constraints()を自動的に呼び、Meta.constraints（条件付きUniqueConstraintを含む）の
    重複を検出してフォームエラーにしてしまう。これはGroupForm.clean_code等のアプリ層チェックとは
    別の経路でform.save()に到達する前に重複を弾いてしまうため、「検証後・保存前のTOCTOU競合で
    IntegrityErrorが発生するケース」を再現するには、アプリ層チェック（clean_code等）に加えて
    このモデル層の自動チェックも無効化する必要がある。
    """
    return None


class MasterIntegrityErrorViewTests(TestCase):
    """GroupRegistView/CategoryRegistView/RetentionRegistView(および対応するEditView)は、
    GroupForm.clean_code等のアプリ層チェックに加えてform.save()をtry/except IntegrityErrorで
    囲んでいる（コード監査での指摘を受けて追加）。アプリ層チェック（clean_code等）とDjangoの
    ModelForm自動検証（Model.validate_constraints()、Django 4.1以降でMeta.constraintsの
    UniqueConstraintも自動チェック対象になった）の両方を無効化することで「検証後・保存前」の
    同時送信（TOCTOU競合）でDBのUniqueConstraint違反(IntegrityError)が発生するケースを再現し、
    生の例外が漏れず利用者にわかるエラーメッセージ付きでフォームが再表示されることを確認する。
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

    def test_group_regist_integrity_error_shows_friendly_message(self):
        Group.objects.create(code="A", name="分類Ａ", doc_kbn=DocKbn.DOCUMENT)
        response = self.client.get("/masters/class/regist/")
        token = response.context["token"]
        with (
            patch.object(GroupForm, "clean_code", lambda self: self.cleaned_data["code"]),
            patch.object(Group, "validate_constraints", _noop_validate_constraints),
        ):
            response = self.client.post(
                "/masters/class/regist/",
                {
                    "token": token, "code": "A", "name": "重複分類", "doc_kbn": DocKbn.DOCUMENT,
                    "department": self.department.pk,
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "この分類コードは既に登録されています。")
        # DBには重複登録されておらず、既存の1件のみが残っていること。
        self.assertEqual(Group.objects.filter(code="A").count(), 1)

    def test_category_regist_integrity_error_shows_friendly_message(self):
        group = Group.objects.create(code="A", name="分類Ａ", doc_kbn=DocKbn.DOCUMENT)
        Category.objects.create(code="001", name="カテゴリーＡ", group=group, doc_kbn=DocKbn.DOCUMENT)
        response = self.client.get("/masters/cat/regist/")
        token = response.context["token"]
        with (
            patch.object(CategoryForm, "clean_code", lambda self: self.cleaned_data["code"]),
            patch.object(Category, "validate_constraints", _noop_validate_constraints),
        ):
            response = self.client.post(
                "/masters/cat/regist/",
                {
                    "token": token, "code": "001", "name": "重複カテゴリー",
                    "group": group.pk, "doc_kbn": DocKbn.DOCUMENT, "department": self.department.pk,
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "このカテゴリーコードは既に登録されています。")
        self.assertEqual(Category.objects.filter(code="001").count(), 1)

    def test_retention_regist_integrity_error_shows_friendly_message(self):
        RetentionPeriod.objects.create(
            kbn=RetentionKbn.DOCUMENT, period_value=1, period_unit=RetentionPeriodUnit.YEAR, display_order=1
        )
        response = self.client.get("/masters/retention/regist/?kbn=document")
        token = response.context["token"]
        with (
            patch.object(
                RetentionPeriodForm, "clean_display_order", lambda self: self.cleaned_data["display_order"]
            ),
            patch.object(RetentionPeriod, "validate_constraints", _noop_validate_constraints),
        ):
            response = self.client.post(
                "/masters/retention/regist/",
                {
                    "token": token,
                    "kbn": RetentionKbn.DOCUMENT,
                    "doc_name": "",
                    "period_value": "3",
                    "period_unit": RetentionPeriodUnit.YEAR,
                    "display_order": "1",
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "この表示順は既に使用されています。")
        self.assertEqual(
            RetentionPeriod.objects.filter(kbn=RetentionKbn.DOCUMENT, display_order=1).count(), 1
        )


class MasterAuditLogContentTests(TestCase):
    """masters/views.py全体の操作履歴ログ(audit_services.log)は、分類の新規登録1件を除いて
    内容が一切検証されていなかった（GroupEditView/GroupDeleteView/CategoryRegistView/
    CategoryEditView/CategoryDeleteView/RetentionRegistView/RetentionEditView/
    RetentionDeleteViewの計8箇所、テストカバレッジ棚卸しで発見、2026-08-26追加）。
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

    def test_group_edit_creates_audit_log_with_content(self):
        """xlsx 操作履歴ログ!B69-70＜職員マスタ更新　例＞と同じ「更新した項目名：更新前データ ->
        更新後データ」形式（原本フィデリティ監査で発見・2026-08-27対応：以前は更新後の値の
        スナップショットのみで、何がどう変わったか記録していなかった）。実際に変更した
        分類名・部署のみが列挙され、変更していないdoc_kbnは列挙されないことを確認する。
        """
        from audit.models import AuditLog

        other_department = Department.objects.create(
            branch_code="999", branch_name="別支店", section_code="", section_name=""
        )
        group = Group.objects.create(code="1", name="分類Ａ", doc_kbn=DocKbn.DOCUMENT, department=self.department)
        token = self.client.get(f"/masters/class/{group.pk}/edit/").context["token"]
        self.client.post(
            f"/masters/class/{group.pk}/edit/",
            {
                "token": token, "code": "1", "name": "分類Ａ改", "doc_kbn": DocKbn.DOCUMENT,
                "department": other_department.pk,
            },
        )
        entry = AuditLog.objects.get(action="分類管理 更新")
        self.assertEqual(
            entry.event_message,
            f"No.1,分類名：分類Ａ改,分類名：分類Ａ -> 分類Ａ改,部署：{self.department} -> {other_department}",
        )
        self.assertNotIn("書類管理区分", entry.event_message)

    def test_group_delete_creates_audit_log_with_content(self):
        from audit.models import AuditLog

        group = Group.objects.create(code="2", name="分類Ｂ", doc_kbn=DocKbn.DOCUMENT, department=self.department)
        token = self.client.get(f"/masters/class/{group.pk}/delete/").context["token"]
        self.client.post(f"/masters/class/{group.pk}/delete/", {"token": token})
        entry = AuditLog.objects.get(action="分類管理 削除")
        self.assertIn("No.2", entry.event_message)
        self.assertIn("分類Ｂ", entry.event_message)

    def test_category_regist_creates_audit_log_with_content(self):
        from audit.models import AuditLog

        group = Group.objects.create(code="A", name="分類Ａ", doc_kbn=DocKbn.DOCUMENT, department=self.department)
        token = self.client.get("/masters/cat/regist/").context["token"]
        self.client.post(
            "/masters/cat/regist/",
            {
                "token": token, "code": "001", "name": "新カテゴリー", "group": group.pk,
                "doc_kbn": DocKbn.DOCUMENT, "department": self.department.pk,
            },
        )
        entry = AuditLog.objects.get(action="カテゴリー管理 新規登録")
        self.assertIn("新カテゴリー", entry.event_message)
        self.assertIn("分類Ａ", entry.event_message)
        self.assertIn(str(self.department), entry.event_message)

    def test_category_edit_creates_audit_log_with_content(self):
        from audit.models import AuditLog

        group = Group.objects.create(code="A", name="分類Ａ", doc_kbn=DocKbn.DOCUMENT, department=self.department)
        category = Category.objects.create(
            code="001", name="カテゴリーＡ", group=group, doc_kbn=DocKbn.DOCUMENT, department=self.department
        )
        token = self.client.get(f"/masters/cat/{category.pk}/edit/").context["token"]
        self.client.post(
            f"/masters/cat/{category.pk}/edit/",
            {
                "token": token, "code": "001", "name": "カテゴリーＡ改", "group": group.pk,
                "doc_kbn": DocKbn.DOCUMENT, "department": self.department.pk,
            },
        )
        entry = AuditLog.objects.get(action="カテゴリー管理 更新")
        self.assertIn("カテゴリーＡ改", entry.event_message)

    def test_category_delete_creates_audit_log_with_content(self):
        from audit.models import AuditLog

        group = Group.objects.create(code="A", name="分類Ａ", doc_kbn=DocKbn.DOCUMENT, department=self.department)
        category = Category.objects.create(
            code="002", name="カテゴリーＢ", group=group, doc_kbn=DocKbn.DOCUMENT, department=self.department
        )
        token = self.client.get(f"/masters/cat/{category.pk}/delete/").context["token"]
        self.client.post(f"/masters/cat/{category.pk}/delete/", {"token": token})
        entry = AuditLog.objects.get(action="カテゴリー管理 削除")
        self.assertIn("No.002", entry.event_message)
        self.assertIn("カテゴリーＢ", entry.event_message)

    def test_retention_regist_creates_audit_log_with_content(self):
        from audit.models import AuditLog

        token = self.client.get("/masters/retention/regist/?kbn=document").context["token"]
        self.client.post(
            "/masters/retention/regist/",
            {
                "token": token, "kbn": RetentionKbn.DOCUMENT, "doc_name": "",
                "period_value": "5", "period_unit": RetentionPeriodUnit.YEAR, "display_order": "1",
            },
        )
        entry = AuditLog.objects.get(action="保存期間設定 新規登録")
        self.assertIn("文書", entry.event_message)
        self.assertIn("5年", entry.event_message)

    def test_retention_edit_creates_audit_log_with_content(self):
        from audit.models import AuditLog

        period = RetentionPeriod.objects.create(
            kbn=RetentionKbn.DOCUMENT, period_value=1, period_unit=RetentionPeriodUnit.YEAR, display_order=1
        )
        token = self.client.get(f"/masters/retention/{period.pk}/edit/").context["token"]
        self.client.post(
            f"/masters/retention/{period.pk}/edit/",
            {
                "token": token, "kbn": RetentionKbn.DOCUMENT, "doc_name": "",
                "period_value": "7", "period_unit": RetentionPeriodUnit.YEAR, "display_order": "1",
            },
        )
        entry = AuditLog.objects.get(action="保存期間設定 更新")
        self.assertIn("7年", entry.event_message)

    def test_retention_delete_creates_audit_log_with_content(self):
        from audit.models import AuditLog

        period = RetentionPeriod.objects.create(
            kbn=RetentionKbn.DOCUMENT, period_value=3, period_unit=RetentionPeriodUnit.YEAR, display_order=1
        )
        token = self.client.get(f"/masters/retention/{period.pk}/delete/").context["token"]
        self.client.post(f"/masters/retention/{period.pk}/delete/", {"token": token})
        entry = AuditLog.objects.get(action="保存期間設定 削除")
        self.assertIn("3年", entry.event_message)


class MasterEditIntegrityErrorViewTests(TestCase):
    """GroupEditView/CategoryEditView/RetentionEditViewはRegist側と同じtry/exceptパターン
    （clean_code等のアプリ層チェック＋save_or_noneでのIntegrityError捕捉）を持つが、Regist側の
    3画面（MasterIntegrityErrorViewTests）とは異なりEdit側の対応するテストが無かった
    （テストカバレッジ棚卸しで発見、2026-08-26追加）。MasterIntegrityErrorViewTestsと同じ手法
    （アプリ層チェック＋Model.validate_constraints()の両方を無効化してTOCTOU競合を再現）を使う。
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

    def test_group_edit_integrity_error_shows_friendly_message(self):
        Group.objects.create(code="A", name="分類Ａ", doc_kbn=DocKbn.DOCUMENT)
        target = Group.objects.create(code="B", name="分類Ｂ", doc_kbn=DocKbn.DOCUMENT)
        response = self.client.get(f"/masters/class/{target.pk}/edit/")
        token = response.context["token"]
        with (
            patch.object(GroupForm, "clean_code", lambda self: self.cleaned_data["code"]),
            patch.object(Group, "validate_constraints", _noop_validate_constraints),
        ):
            response = self.client.post(
                f"/masters/class/{target.pk}/edit/",
                {
                    "token": token, "code": "A", "name": "分類Ｂ改", "doc_kbn": DocKbn.DOCUMENT,
                    "department": self.department.pk,
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "この分類コードは既に登録されています。")
        target.refresh_from_db()
        self.assertEqual(target.code, "B")

    def test_category_edit_integrity_error_shows_friendly_message(self):
        group = Group.objects.create(code="A", name="分類Ａ", doc_kbn=DocKbn.DOCUMENT)
        Category.objects.create(code="001", name="カテゴリーＡ", group=group, doc_kbn=DocKbn.DOCUMENT)
        target = Category.objects.create(code="002", name="カテゴリーＢ", group=group, doc_kbn=DocKbn.DOCUMENT)
        response = self.client.get(f"/masters/cat/{target.pk}/edit/")
        token = response.context["token"]
        with (
            patch.object(CategoryForm, "clean_code", lambda self: self.cleaned_data["code"]),
            patch.object(Category, "validate_constraints", _noop_validate_constraints),
        ):
            response = self.client.post(
                f"/masters/cat/{target.pk}/edit/",
                {
                    "token": token, "code": "001", "name": "カテゴリーＢ改", "group": group.pk,
                    "doc_kbn": DocKbn.DOCUMENT, "department": self.department.pk,
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "このカテゴリーコードは既に登録されています。")
        target.refresh_from_db()
        self.assertEqual(target.code, "002")

    def test_retention_edit_integrity_error_shows_friendly_message(self):
        RetentionPeriod.objects.create(
            kbn=RetentionKbn.DOCUMENT, period_value=1, period_unit=RetentionPeriodUnit.YEAR, display_order=1
        )
        target = RetentionPeriod.objects.create(
            kbn=RetentionKbn.DOCUMENT, period_value=2, period_unit=RetentionPeriodUnit.YEAR, display_order=2
        )
        response = self.client.get(f"/masters/retention/{target.pk}/edit/")
        token = response.context["token"]
        with (
            patch.object(
                RetentionPeriodForm, "clean_display_order", lambda self: self.cleaned_data["display_order"]
            ),
            patch.object(RetentionPeriod, "validate_constraints", _noop_validate_constraints),
        ):
            response = self.client.post(
                f"/masters/retention/{target.pk}/edit/",
                {
                    "token": token, "kbn": RetentionKbn.DOCUMENT, "doc_name": "",
                    "period_value": "2", "period_unit": RetentionPeriodUnit.YEAR, "display_order": "1",
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "この表示順は既に使用されています。")
        target.refresh_from_db()
        self.assertEqual(target.display_order, 2)


class MasterDeleteDatabaseErrorFallbackTests(TestCase):
    """core.master_views.BaseScopedMasterDeleteView.post()のobj.save(update_fields=[...])が
    DBError（DB接続断・制約違反等）を送出した場合のフォールバック（品質レビューで発見・
    2026-08-26に追加された最も新しい例外処理）に、Group/Categoryいずれの削除確認画面にも
    回帰テストが伴っていなかった（テストカバレッジ棚卸しで発見、2026-08-26追加）。
    兄弟のBaseScopedMasterEditView側（MasterEditIntegrityErrorViewTests）と異なりsave_or_none
    を経由しない直接のobj.save()呼び出しのため、Group.saveを直接patchして再現する。
    MasterDoubleSubmitTokenTestsと同じ判断（GroupDeleteView/CategoryDeleteViewは
    core.master_views.BaseScopedMasterDeleteViewの共通実装を完全共有）により、Group側のみ検証し
    Category側は重複テストとして省略する。
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

    def test_group_delete_db_error_shows_friendly_message_and_does_not_delete(self):
        from django.db import DatabaseError

        group = Group.objects.create(code="1", name="分類Ａ", doc_kbn=DocKbn.DOCUMENT, department=self.department)
        token = self.client.get(f"/masters/class/{group.pk}/delete/").context["token"]
        with patch.object(Group, "save", side_effect=DatabaseError("simulated db error")):
            response = self.client.post(
                f"/masters/class/{group.pk}/delete/", {"token": token}, follow=True
            )
        messages = [str(m) for m in response.context["messages"]]
        self.assertTrue(any("削除に失敗しました" in m for m in messages))
        group.refresh_from_db()
        self.assertFalse(group.is_deleted)


class RetentionRedirectPreservesSelectionTests(TestCase):
    """RetentionRegistView/RetentionEditView/RetentionDeleteViewは、登録・更新・削除完了後の
    リダイレクト先(_retention_list_url)に選択中のkbn/doc_nameを引き継ぐ。ユーザー指摘で
    修正された「編集画面から戻ると選択が解除される」不具合の再発防止として追加した回帰テスト
    （テストカバレッジ棚卸しで発見、2026-08-26追加）。電子決裁(稟議書)区分を使うことで、
    kbn=documentのデフォルト値へのフォールバックと区別できるようにしている。
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

    def test_regist_redirect_preserves_eapproval_selection(self):
        token = self.client.get(
            "/masters/retention/regist/", {"kbn": RetentionKbn.EAPPROVAL, "doc_name": "ringisho"}
        ).context["token"]
        response = self.client.post(
            "/masters/retention/regist/",
            {
                "token": token, "kbn": RetentionKbn.EAPPROVAL, "doc_name": "ringisho",
                "period_value": "3", "period_unit": RetentionPeriodUnit.YEAR, "display_order": "1",
            },
        )
        self.assertIn("kbn=eapproval", response.url)
        self.assertIn("doc_name=ringisho", response.url)

    def test_edit_redirect_preserves_eapproval_selection(self):
        period = RetentionPeriod.objects.create(
            kbn=RetentionKbn.EAPPROVAL, doc_name="ringisho", period_value=1,
            period_unit=RetentionPeriodUnit.YEAR, display_order=1,
        )
        token = self.client.get(f"/masters/retention/{period.pk}/edit/").context["token"]
        response = self.client.post(
            f"/masters/retention/{period.pk}/edit/",
            {
                "token": token, "kbn": RetentionKbn.EAPPROVAL, "doc_name": "ringisho",
                "period_value": "4", "period_unit": RetentionPeriodUnit.YEAR, "display_order": "1",
            },
        )
        self.assertIn("kbn=eapproval", response.url)
        self.assertIn("doc_name=ringisho", response.url)

    def test_delete_redirect_preserves_eapproval_selection(self):
        period = RetentionPeriod.objects.create(
            kbn=RetentionKbn.EAPPROVAL, doc_name="ringisho", period_value=1,
            period_unit=RetentionPeriodUnit.YEAR, display_order=1,
        )
        token = self.client.get(f"/masters/retention/{period.pk}/delete/").context["token"]
        response = self.client.post(f"/masters/retention/{period.pk}/delete/", {"token": token})
        self.assertIn("kbn=eapproval", response.url)
        self.assertIn("doc_name=ringisho", response.url)


class DepartmentScopingTests(TestCase):
    """Rev1.2（xlsx 分類管理!B35,B73-75、カテゴリー管理!B35,B78-80、2026-08-24反映）で追加された
    分類・カテゴリーマスタの部署スコープ。管理者は全部署、それ以外は自部署のみ閲覧・編集できる
    （masters.services.department_scope_ids）。
    """

    def setUp(self):
        self.dept_a = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.dept_b = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="02", section_name="経理部"
        )
        self.group_a = Group.objects.create(
            code="A", name="分類Ａ", doc_kbn=DocKbn.DOCUMENT, department=self.dept_a
        )
        self.group_b = Group.objects.create(
            code="B", name="分類Ｂ", doc_kbn=DocKbn.DOCUMENT, department=self.dept_b
        )

    def _login_as(self, department, role):
        employee = Employee.objects.create_user(
            employee_no="1", name="ログイン太郎", password="pass1234",
            department=department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        PermissionProfile.objects.create(employee=employee, role=role)
        self.client.login(username="1", password="pass1234")
        return employee

    def test_manager_sees_only_own_department_groups(self):
        self._login_as(self.dept_a, PermissionRole.MANAGER)
        response = self.client.get("/masters/class/")
        self.assertContains(response, "分類Ａ")
        self.assertNotContains(response, "分類Ｂ")
        # xlsx 分類管理!B75「一覧の「部署」を非表示」＝部署検索プルダウン・部署列とも
        # 管理者以外には出さない。
        self.assertNotContains(response, 'name="department"')

    def test_admin_sees_all_departments_groups_and_department_filter(self):
        self._login_as(self.dept_a, PermissionRole.ADMIN)
        response = self.client.get("/masters/class/")
        self.assertContains(response, "分類Ａ")
        self.assertContains(response, "分類Ｂ")
        self.assertContains(response, 'name="department"')

    def test_manager_cannot_reach_other_department_group_edit(self):
        """xlsx記載は無いが、一覧が自部署に絞られる以上、編集アクセスもサーバー側で
        同じ範囲に制限する（URL直叩き対策、GroupEditView._get_object参照）。"""
        self._login_as(self.dept_a, PermissionRole.MANAGER)
        response = self.client.get(f"/masters/class/{self.group_b.pk}/edit/")
        self.assertEqual(response.status_code, 404)

    def test_manager_cross_department_access_logs_warning(self):
        """部署スコープ外へのURL直叩きは、GroupDeleteView.post等の他の拒否パスと同じく
        セキュリティ上意味のある事象としてlogger.warningに残す（以前は404のみでログが
        無かった。コード監査で発見、2026-08-24修正）。masters.services.scoped_get_object_or_404は
        2026-08-25にcore.scoping_services側へ委譲する形に集約されたため、ログの出所も
        そちらのロガーになる（documents/contracts側と同じ実装・同じログ文言に統一された）。"""
        employee = self._login_as(self.dept_a, PermissionRole.MANAGER)
        with self.assertLogs("core.scoping_services", level="WARNING") as cm:
            response = self.client.get(f"/masters/class/{self.group_b.pk}/edit/")
        self.assertEqual(response.status_code, 404)
        self.assertTrue(any(employee.employee_no in message for message in cm.output))

    def test_manager_cannot_reach_other_department_group_delete_confirmation(self):
        """GroupEditViewの他部署404はカバーされているが、削除確認画面
        （GroupDeleteView.scoped_lookup）側のURL直叩き404は未検証だった
        （テストカバレッジ棚卸しで発見、2026-08-26追加）。"""
        self._login_as(self.dept_a, PermissionRole.MANAGER)
        response = self.client.get(f"/masters/class/{self.group_b.pk}/delete/")
        self.assertEqual(response.status_code, 404)

    def test_manager_cannot_reach_other_department_category_edit(self):
        """CategoryEditView._get_objectでも同じ部署スコープが効くことを確認する
        （GroupEditViewと同じ方針）。"""
        category_b = Category.objects.create(
            code="B01", name="経理部カテゴリー", group=self.group_b, doc_kbn=DocKbn.DOCUMENT,
            department=self.dept_b,
        )
        self._login_as(self.dept_a, PermissionRole.MANAGER)
        response = self.client.get(f"/masters/cat/{category_b.pk}/edit/")
        self.assertEqual(response.status_code, 404)

    def test_manager_cannot_reach_other_department_category_delete_confirmation(self):
        """GroupDeleteView側と同じ理由（テストカバレッジ棚卸しで発見、2026-08-26追加）。"""
        category_b = Category.objects.create(
            code="B02", name="経理部カテゴリー2", group=self.group_b, doc_kbn=DocKbn.DOCUMENT,
            department=self.dept_b,
        )
        self._login_as(self.dept_a, PermissionRole.MANAGER)
        response = self.client.get(f"/masters/cat/{category_b.pk}/delete/")
        self.assertEqual(response.status_code, 404)

    def test_non_admin_sort_by_department_is_ignored(self):
        """部署列自体が非管理者には非表示のため、?sort=department直指定でも
        並び替えを適用しない（以前はis_adminガードが無かった。コード監査で発見、
        2026-08-24修正）。デフォルトソート（部課コード順）にフォールバックすることを確認する。"""
        self._login_as(self.dept_a, PermissionRole.MANAGER)
        response = self.client.get("/masters/class/", {"sort": "department", "dir": "desc"})
        self.assertEqual(response.status_code, 200)
        # 自部署のみが見える（デフォルトソートに落ちても分類Ａだけが表示される）。
        self.assertContains(response, "分類Ａ")

    def test_group_regist_audit_log_includes_department(self):
        """分類登録の監査ログに部署が記録されること（以前はNo./分類名/書類管理区分のみで、
        Rev1.2で新設された権限境界に関わるdepartmentが抜けていた。コード監査で発見、
        2026-08-24修正）。"""
        from audit.models import AuditLog

        employee = self._login_as(self.dept_a, PermissionRole.ADMIN)
        response = self.client.get("/masters/class/regist/")
        token = response.context["token"]
        self.client.post(
            "/masters/class/regist/",
            {
                "token": token, "code": "9", "name": "新分類", "doc_kbn": DocKbn.DOCUMENT,
                "department": self.dept_b.pk,
            },
        )
        entry = AuditLog.objects.get(action="分類管理 新規登録")
        self.assertIn(str(self.dept_b), entry.event_message)

    def test_manager_registered_group_is_auto_assigned_own_department(self):
        """xlsx 分類管理!B116「「部署」プルダウン ※権限：管理者のみ表示」。非管理者の登録画面には
        部署プルダウンが無く、作成した分類は自動的にログイン者の自部署が設定される
        （GroupRegistView.post参照）。"""
        employee = self._login_as(self.dept_a, PermissionRole.MANAGER)
        response = self.client.get("/masters/class/regist/")
        token = response.context["token"]
        self.assertNotIn(b'name="department"', response.content)

        self.client.post(
            "/masters/class/regist/",
            {"token": token, "code": "9", "name": "所属長作成分類", "doc_kbn": DocKbn.DOCUMENT},
        )
        created = Group.objects.get(code="9")
        self.assertEqual(created.department_id, employee.department_id)

    def test_admin_registered_group_requires_department_selection(self):
        employee = self._login_as(self.dept_a, PermissionRole.ADMIN)
        response = self.client.get("/masters/class/regist/")
        token = response.context["token"]

        response = self.client.post(
            "/masters/class/regist/",
            {"token": token, "code": "9", "name": "管理者作成分類", "doc_kbn": DocKbn.DOCUMENT},
        )
        self.assertFalse(Group.objects.filter(code="9").exists())
        self.assertContains(response, "このフィールドは必須です。")

        token = response.context["token"]
        self.client.post(
            "/masters/class/regist/",
            {
                "token": token, "code": "9", "name": "管理者作成分類", "doc_kbn": DocKbn.DOCUMENT,
                "department": self.dept_b.pk,
            },
        )
        created = Group.objects.get(code="9")
        self.assertEqual(created.department_id, self.dept_b.pk)

    def test_null_department_legacy_group_visible_to_non_admin(self):
        """department未設定（Rev1.2移行前の既存データ想定）は、非管理者にも見える
        （masters.services.scope_queryset_by_department docstring参照。全く見えなくなる・
        編集できなくなる退行を避けるための意図的な仕様）。"""
        legacy = Group.objects.create(code="Z", name="移行前分類", doc_kbn=DocKbn.DOCUMENT)
        self._login_as(self.dept_a, PermissionRole.MANAGER)
        response = self.client.get("/masters/class/")
        self.assertContains(response, "移行前分類")
        response = self.client.get(f"/masters/class/{legacy.pk}/edit/")
        self.assertEqual(response.status_code, 200)

    def test_admin_list_department_column_is_leftmost(self):
        """Rev1.2の埋め込み画像モック（分類管理シート、セル文字列では検出できず画像ハッシュ
        突き合わせで発見）は「部署」列が分類コード列より左にある。当初は分類コードの直後に
        実装してしまっていたため、モック通りの列順に修正した（2026-08-24）。"""
        self._login_as(self.dept_a, PermissionRole.ADMIN)
        response = self.client.get("/masters/class/")
        content = response.content.decode("utf-8")
        self.assertLess(content.index(">部署<"), content.index("分類コード"))

    def test_delete_confirmation_shows_department(self):
        """Rev1.2の埋め込み画像モック（分類管理削除シート）はテキストセルの内容こそ変化が
        無かったが、画像だけ差し替わっており「部署」の表示行が追加されていた
        （openpyxlでのセル単位diffでは検出できず、画像ハッシュ突き合わせで発見）。"""
        self._login_as(self.dept_a, PermissionRole.ADMIN)
        response = self.client.get(f"/masters/class/{self.group_a.pk}/delete/")
        self.assertContains(response, "総務部")


class CategoryFormFieldErrorRenderingTests(TestCase):
    """CategoryForm.clean()が書類管理区分の不整合を`add_error("group", ...)`で
    groupフィールドに付けるが、cat_regist.html/cat_edit.htmlの「分類」行が
    ウィジェットのみ描画しエラーループを持たなかったため、メッセージが画面に
    一切表示されず握りつぶされていた（フォームは弾かれるがユーザーには無反応に見える）
    バグの回帰テスト（2026-09-03ユーザー報告）。
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
        # 文書管理の分類に対して、契約書管理のカテゴリーを紐付けようとする不整合な組み合わせ。
        self.doc_group = Group.objects.create(code="100", name="文書分類", doc_kbn=DocKbn.DOCUMENT)
        self.category = Category.objects.create(
            code="001", name="既存カテゴリー", group=self.doc_group, doc_kbn=DocKbn.DOCUMENT
        )

    def _mismatch_payload(self, token):
        return {
            "token": token, "code": "900", "name": "不整合カテゴリー",
            "group": self.doc_group.pk, "doc_kbn": DocKbn.CONTRACT,
            "department": self.department.pk,
        }

    def test_regist_shows_doc_kbn_mismatch_message(self):
        response = self.client.get("/masters/cat/regist/")
        response = self.client.post(
            "/masters/cat/regist/", self._mismatch_payload(response.context["token"])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "書類管理区分")
        self.assertContains(response, "一致しません")
        self.assertFalse(Category.objects.filter(code="900").exists())

    def test_edit_shows_doc_kbn_mismatch_message(self):
        response = self.client.get(f"/masters/cat/{self.category.pk}/edit/")
        payload = self._mismatch_payload(response.context["token"])
        payload["code"] = "001"
        response = self.client.post(f"/masters/cat/{self.category.pk}/edit/", payload)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "一致しません")
        self.category.refresh_from_db()
        self.assertEqual(self.category.doc_kbn, DocKbn.DOCUMENT)
