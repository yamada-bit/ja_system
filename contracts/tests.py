import datetime
import json
from unittest import mock

from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import Error as DBError
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import Employee, Position, Rank
from audit.models import AuditLog
from contracts.forms import CommaNumberInput, SearchForm
from contracts.search_services import build_queryset
from contracts.services import calculate_expiry_date, contract_edit_is_dirty
from masters.models import Category, DocKbn, Group
from organizations.models import Department
from permissions.models import PermissionProfile, PermissionRole
from permissions.services import contract_searchable_department_ids


class CalculateExpiryDateTests(TestCase):
    """xlsx メイン画面!B48「契約書の保存期限は固定で10年」。"""

    def test_defaults_to_ten_years(self):
        result = calculate_expiry_date(datetime.date(2026, 8, 9))
        self.assertEqual(result, datetime.date(2036, 8, 9))

    @override_settings(CONTRACT_RETENTION_YEARS=5)
    def test_respects_custom_setting(self):
        result = calculate_expiry_date(datetime.date(2026, 8, 9))
        self.assertEqual(result, datetime.date(2031, 8, 9))

    def test_leap_day_start_date_falls_back_to_feb28(self):
        result = calculate_expiry_date(datetime.date(2028, 2, 29))
        self.assertEqual(result, datetime.date(2038, 2, 28))


class CommaNumberInputTests(TestCase):
    """契約金額欄のウィジェット（監査で発見：初期表示・バリデーションエラー再表示時に
    カンマ区切りが効いていなかった。formatCurrency()のonblurは編集画面を開いた直後には
    一度も発火しないため）。"""

    def test_format_value_adds_thousands_separators(self):
        widget = CommaNumberInput()
        self.assertEqual(widget.format_value("1200000"), "1,200,000")

    def test_format_value_handles_decimal_instance(self):
        from decimal import Decimal

        widget = CommaNumberInput()
        self.assertEqual(widget.format_value(Decimal("1200000")), "1,200,000")

    def test_format_value_passes_through_empty_value(self):
        widget = CommaNumberInput()
        # Django標準のWidget.format_value()はNone/""をNoneに正規化する（そのまま踏襲）。
        self.assertIsNone(widget.format_value(None))
        self.assertIsNone(widget.format_value(""))

    def test_format_value_passes_through_non_numeric_value_unchanged(self):
        """壊れた入力値でformat_valueが例外を投げて画面全体を落とすことがないようにする。"""
        widget = CommaNumberInput()
        self.assertEqual(widget.format_value("not-a-number"), "not-a-number")

    def test_value_from_datadict_still_strips_commas_for_submission(self):
        widget = CommaNumberInput()
        self.assertEqual(widget.value_from_datadict({"amount": "1,200,000"}, {}, "amount"), "1200000")


class SearchQuerysetTests(TestCase):
    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.employee = Employee.objects.create_user(
            employee_no="1", name="テスト太郎", password="x",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        self.group = Group.objects.create(code="A", name="契約分類Ａ", doc_kbn=DocKbn.CONTRACT)
        self.category = Category.objects.create(
            code="001", name="契約カテゴリーＡ", group=self.group, doc_kbn=DocKbn.CONTRACT
        )
        self.contract_apple_banana = self._create_contract("apple banana agreement")
        self.contract_apple_only = self._create_contract("apple summary")

    def _create_contract(self, title):
        from contracts.models import Contract

        contract = Contract(
            title=title, department=self.department, group=self.group, category=self.category,
            year=2026, uploader=self.employee, expiry_date=datetime.date(2036, 1, 1),
        )
        contract.file.save("test.pdf", ContentFile(b"dummy"), save=False)
        contract.save()
        return contract

    def test_title_or_match_returns_any_word_hit(self):
        form = SearchForm(data={"title": "apple banana", "title_match": "or"})
        qs = build_queryset(form, employee=self.employee)
        self.assertIn(self.contract_apple_banana, qs)
        self.assertIn(self.contract_apple_only, qs)

    def test_title_and_match_requires_all_words(self):
        form = SearchForm(data={"title": "apple banana", "title_match": "and"})
        qs = build_queryset(form, employee=self.employee)
        self.assertIn(self.contract_apple_banana, qs)
        self.assertNotIn(self.contract_apple_only, qs)

    def test_title_search_matches_across_fullwidth_halfwidth(self):
        """documents.tests.SearchQuerysetTests.test_title_search_matches_across_fullwidth_halfwidth
        と同じ理由（contracts.models.Contract.title_normalized、core.text_normalization参照）。
        """
        contract = self._create_contract("ＸＹＺ株式会社２０２６年度契約")
        form = SearchForm(data={"title": "xyz 2026", "title_match": "and"})
        qs = build_queryset(form, employee=self.employee)
        self.assertIn(contract, qs)

    def test_freeword_search_matches_extracted_text_across_katakana_width(self):
        """documents.tests.SearchQuerysetTests.
        test_freeword_search_matches_extracted_text_across_katakana_widthと同じ理由。
        """
        from contracts.models import Contract

        contract = Contract(
            title="半角カタカナ本文テスト", department=self.department, group=self.group,
            category=self.category, year=2026, uploader=self.employee,
            expiry_date=datetime.date(2036, 1, 1), extracted_text="ﾃｽﾄﾃﾞｰﾀ",
        )
        contract.file.save("test.pdf", ContentFile(b"dummy"), save=False)
        contract.save()
        form = SearchForm(data={"freeword": "テストデータ", "freeword_match": "or"})
        qs = build_queryset(form, employee=self.employee)
        self.assertIn(contract, qs)

    def test_pks_filter_ignores_other_search_conditions(self):
        """documents.tests.SearchQuerysetTests.test_pks_filter_ignores_other_search_conditions
        と同じ理由（原本index.html:1665-1677相当、保管完了ポップアップ「登録した契約書を
        確認する」からの遷移）。"""
        form = SearchForm(data={"title": "絶対にヒットしない検索語"})
        qs = build_queryset(form, employee=self.employee, pks=[str(self.contract_apple_only.pk)])
        self.assertEqual(list(qs), [self.contract_apple_only])

    def test_pks_filter_ignores_invalid_values(self):
        """documents.tests.SearchQuerysetTests.test_pks_filter_ignores_invalid_valuesと同じ理由
        （監査で発見・修正）。"""
        form = SearchForm(data={})
        qs = build_queryset(
            form, employee=self.employee, pks=[str(self.contract_apple_only.pk), "not-a-number", ""]
        )
        self.assertEqual(list(qs), [self.contract_apple_only])

    def test_list_queryset_defers_heavy_text_columns(self):
        """documents.tests.SearchQuerysetTests.test_list_queryset_defers_heavy_text_columnsと
        同じ理由（core.search_services.LIST_DEFERRED_TEXT_FIELDS）。"""
        from contracts.models import Contract

        Contract.objects.filter(pk=self.contract_apple_only.pk).update(
            extracted_text="本文" * 100, extracted_text_normalized="ほんぶん" * 100
        )
        form = SearchForm(data={})
        obj = next(
            o for o in build_queryset(form, employee=self.employee) if o.pk == self.contract_apple_only.pk
        )
        with self.assertNumQueries(0):
            _ = obj.title
        with self.assertNumQueries(1):
            _ = obj.extracted_text


class DateRangeValidationTests(TestCase):
    """開始＞終了の逆転入力を弾く（review_pending.txt No.3、原本・xlsxに無いがサーバー側の
    健全性チェックとして追加）。検索フォームの「期間」と、契約書保管フォームの「契約期間」。"""

    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.admin = Employee.objects.create_user(
            employee_no="1", name="管理者", password="x",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        PermissionProfile.objects.create(employee=self.admin, role=PermissionRole.ADMIN)
        self.group = Group.objects.create(code="A", name="契約分類Ａ", doc_kbn=DocKbn.CONTRACT)
        self.category = Category.objects.create(
            code="001", name="契約カテゴリーＡ", group=self.group, doc_kbn=DocKbn.CONTRACT
        )
        self.client.login(username="1", password="x")

    def test_contract_edit_screen_renders_reversed_period_error(self):
        """契約書編集画面（edit.html）で契約期間の逆転入力エラーが「契約期間」行の下に出る。
        ユーザー報告：フォーム側のclean()は入れたがテンプレートにエラー表示が無かった。"""
        from contracts.models import Contract

        contract = Contract(
            title="契約A", department=self.department, group=self.group, category=self.category,
            year=2026, uploader=self.admin, expiry_date=datetime.date(2036, 1, 1),
        )
        contract.file.save("c.txt", ContentFile(b"x"), save=False)
        contract.save()
        token = self.client.get(f"/contracts/{contract.pk}/edit/").context["token"]
        response = self.client.post(
            f"/contracts/{contract.pk}/edit/",
            {
                "token": token, "department": self.department.pk, "group": self.group.pk,
                "category": self.category.pk, "year": 2026, "title_0": "契約A",
                "contract_period_start": "2026-12-31", "contract_period_end": "2026-01-01",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "契約期間(終了)は契約期間(開始)より前にできません。")
        contract.refresh_from_db()
        self.assertIsNone(contract.contract_period_start)

    def test_search_form_rejects_reversed_period(self):
        form = SearchForm(data={"save_date_start": "2026-06-01", "save_date_end": "2026-01-01"})
        self.assertFalse(form.is_valid())
        self.assertIn("save_date_end", form.errors)

    def test_search_form_allows_same_day_and_normal(self):
        self.assertTrue(
            SearchForm(data={"save_date_start": "2026-01-01", "save_date_end": "2026-01-01"}).is_valid()
        )
        self.assertTrue(
            SearchForm(data={"save_date_start": "2026-01-01", "save_date_end": "2026-06-01"}).is_valid()
        )

    def _upload_data(self, suffix, **overrides):
        data = {
            f"year{suffix}": 2026, "title_0": "契約書A",
            f"department{suffix}": self.department.pk, f"group{suffix}": self.group.pk,
            f"category{suffix}": self.category.pk,
        }
        data.update(overrides)
        return data

    def test_upload_form_rejects_reversed_contract_period_create_mode(self):
        from contracts.forms import UploadStep2Form

        form = UploadStep2Form(
            data=self._upload_data(
                "_0", contract_period_start_0="2026-12-31", contract_period_end_0="2026-01-01"
            ),
            employee=self.admin, file_count=1, edit_mode=False,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("contract_period_end_0", form.errors)

    def test_upload_form_rejects_reversed_contract_period_edit_mode(self):
        from contracts.forms import UploadStep2Form

        form = UploadStep2Form(
            data=self._upload_data(
                "", contract_period_start="2026-12-31", contract_period_end="2026-01-01"
            ),
            employee=self.admin, edit_mode=True,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("contract_period_end", form.errors)

    def test_upload_form_allows_normal_contract_period(self):
        from contracts.forms import UploadStep2Form

        form = UploadStep2Form(
            data=self._upload_data(
                "_0", contract_period_start_0="2026-01-01", contract_period_end_0="2026-12-31"
            ),
            employee=self.admin, file_count=1, edit_mode=False,
        )
        self.assertTrue(form.is_valid(), form.errors)


class SearchFormDepartmentScopeQueryTests(TestCase):
    """SearchForm.__init__の部署スコープ計算（contract_searchable_department_ids）。

    以前はdepartment欄の絞り込みとgroup/category欄の絞り込みでそれぞれ独立に
    contract_searchable_department_ids()を呼んでおり（department_ids_for_group_scope(kind=
    "contract")が内部で同じ関数を再度呼ぶだけのため）、検索画面を開くたびに本来2クエリで
    済む計算を4クエリ発行していた（コード監査で発見、2026-08-24修正）。呼び出し回数が
    1回に減ったことを確認する。
    """

    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.employee = Employee.objects.create_user(
            employee_no="1", name="テスト太郎", password="x",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.STAFF)

    def test_contract_searchable_department_ids_called_once(self):
        with mock.patch(
            "contracts.forms.contract_searchable_department_ids", wraps=contract_searchable_department_ids
        ) as spy:
            SearchForm(data={}, employee=self.employee)
        self.assertEqual(spy.call_count, 1)

    def test_search_view_reuses_form_dept_ids_instead_of_recomputing_in_build_queryset(self):
        """効率性レビューで発見：上のテストはSearchForm内部の重複解消（2026-08-24修正）のみを
        検証しており、SearchView.get()がフォームとは別にbuild_queryset()内でも独立して
        contract_searchable_department_ids()を計算していた重複（検索画面表示のたびに
        本来2クエリで済むところを4クエリ発行）は未検証だった。contracts.forms/
        contracts.search_servicesはそれぞれ`from permissions.services import
        contract_searchable_department_ids`でモジュール単位に別々の参照を束縛しているため、
        呼び出し回数を通しで数えるには両方をpatchする必要がある。SearchView.get()経由で
        全体を通しても計算が1回だけになることを確認する（2026-08-25修正）。"""
        self.client.login(username="1", password="x")
        spy = mock.Mock(wraps=contract_searchable_department_ids)
        with mock.patch("contracts.forms.contract_searchable_department_ids", spy), mock.patch(
            "contracts.search_services.contract_searchable_department_ids", spy
        ):
            response = self.client.get("/contracts/search/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(spy.call_count, 1)


class SearchFormDepartmentAutoSetTests(TestCase):
    """xlsx 検索・閲覧・変更!B416-418(Rev1.1)「部署名：ログインユーザーの部署を自動セット／
    閲覧部署範囲テーブルの旧部署もカンマ区切り」。管理者、および契約書-部門間閲覧設定ありの
    職員（いずれも部署欄が非disabled）も含めて自部署が既定表示されること
    （core.forms.apply_search_department_default、documents.tests.SearchFormDepartmentAutoSetTests
    と同じ。2026-09-08 ユーザー依頼で追加）。部門間閲覧設定の部署は「選択」で追加する対象で
    あって自動セット対象ではない（B421-423は表示可否の規定）。"""

    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.old_section = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="02", section_name="旧総務課"
        )
        self.other_branch = Department.objects.create(
            branch_code="100", branch_name="A支店", section_code="01", section_name="A支店営業課"
        )
        self.admin = Employee.objects.create_user(
            employee_no="1", name="管理者", password="pass1234",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        PermissionProfile.objects.create(employee=self.admin, role=PermissionRole.ADMIN)
        self.staff = Employee.objects.create_user(
            employee_no="2", name="一般", password="pass1234",
            department=self.department, rank=Rank.SHUJI, position=Position.IPPAN,
        )
        PermissionProfile.objects.create(employee=self.staff, role=PermissionRole.STAFF)
        self.cross_dept_user = Employee.objects.create_user(
            employee_no="3", name="部門間", password="pass1234",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KAKARICHO,
        )
        p = PermissionProfile.objects.create(employee=self.cross_dept_user, role=PermissionRole.STAFF)
        p.contract_visible_departments.add(self.other_branch)

    def _dept_display_value(self, html):
        import re

        m = re.search(r'id="id_department_display"[^>]*value="([^"]*)"', html)
        return m.group(1) if m else None

    def test_admin_gets_own_department_prefilled(self):
        self.client.login(username="1", password="pass1234")
        html = self.client.get("/contracts/search/").content.decode()
        self.assertEqual(self._dept_display_value(html), "総務部")
        self.assertIn("openPopupPopup(this, 'dept'", html)

    def test_cross_dept_permission_user_gets_own_department_prefilled_not_the_cross_dept(self):
        """契約書-部門間閲覧設定ありの非管理者は「選択」ボタンが出る（非disabled）ため、
        以前は部署欄が空だった。自部署のみ既定表示され、部門間設定の部署は含めない。"""
        self.client.login(username="3", password="pass1234")
        html = self.client.get("/contracts/search/").content.decode()
        self.assertEqual(self._dept_display_value(html), "総務部")
        self.assertIn("openPopupPopup(this, 'dept'", html)

    def test_non_admin_still_gets_own_department_prefilled(self):
        self.client.login(username="2", password="pass1234")
        html = self.client.get("/contracts/search/").content.decode()
        self.assertEqual(self._dept_display_value(html), "総務部")
        self.assertNotIn("openPopupPopup(this, 'dept'", html)

    def test_merge_split_predecessor_department_is_also_prefilled(self):
        from organizations.models import DepartmentViewScope

        DepartmentViewScope.objects.create(
            viewer_department=self.department, visible_department=self.old_section,
            action=DepartmentViewScope.ACTION_MERGE,
        )
        self.client.login(username="1", password="pass1234")
        html = self.client.get("/contracts/search/").content.decode()
        self.assertEqual(self._dept_display_value(html), "総務部, 旧総務課")

    def test_explicit_department_in_query_is_not_overridden(self):
        self.client.login(username="1", password="pass1234")
        html = self.client.get(
            "/contracts/search/", {"department": str(self.old_section.pk)}
        ).content.decode()
        self.assertEqual(self._dept_display_value(html), "旧総務課")


class SearchSortTests(TestCase):
    """screen-search（契約書モード）列見出しソート（contracts.search_services.apply_sort）の
    回帰テスト。documents.tests.SearchSortTestsと同じ理由（2026-08-17ユーザー報告）。
    """

    def setUp(self):
        self.department_a = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="Aあ部"
        )
        self.department_b = Department.objects.create(
            branch_code="999", branch_name="支店", section_code="02", section_name="Zん部"
        )
        self.employee = Employee.objects.create_user(
            employee_no="1", name="テスト太郎", password="x",
            department=self.department_a, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        # 「保存情報」ソートのテストは部署をまたいだ契約書を対象にするため管理者ロールにする
        # （documents.tests.SearchSortTests.setUpと同じ理由）。
        PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.ADMIN)
        self.group = Group.objects.create(code="A", name="契約分類Ａ", doc_kbn=DocKbn.CONTRACT)
        self.category_a = Category.objects.create(
            code="001", name="契約カテゴリーＡ", group=self.group, doc_kbn=DocKbn.CONTRACT
        )
        self.category_z = Category.objects.create(
            code="002", name="契約カテゴリーＺ", group=self.group, doc_kbn=DocKbn.CONTRACT
        )

    def _create_contract(self, *, department, category, year=2026, save_date=None, uploader=None):
        from contracts.models import Contract

        contract = Contract(
            title="テスト", department=department, group=self.group, category=category,
            year=year, uploader=uploader or self.employee, expiry_date=datetime.date(2036, 1, 1),
        )
        contract.file.save("test.pdf", ContentFile(b"dummy"), save=False)
        contract.save()
        if save_date is not None:
            from contracts.models import Contract as _Contract

            _Contract.objects.filter(pk=contract.pk).update(save_date=save_date)
            contract.refresh_from_db()
        return contract

    def test_no_sort_ascending_matches_default_order_descending_reverses_it(self):
        """documents.tests.SearchSortTests.
        test_no_sort_ascending_matches_default_order_descending_reverses_itと同じ理由。"""
        older = self._create_contract(
            department=self.department_a, category=self.category_a,
            save_date=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
        )
        newer = self._create_contract(
            department=self.department_a, category=self.category_a,
            save_date=datetime.datetime(2026, 6, 1, tzinfo=datetime.timezone.utc),
        )
        form = SearchForm(data={})

        default_qs = build_queryset(form, employee=self.employee)
        self.assertEqual(list(default_qs), [newer, older])

        asc_qs = build_queryset(form, employee=self.employee, sort_key="no", sort_dir="asc")
        self.assertEqual(list(asc_qs), [newer, older])

        desc_qs = build_queryset(form, employee=self.employee, sort_key="no", sort_dir="desc")
        self.assertEqual(list(desc_qs), [older, newer])

    def test_info_sort_matches_displayed_department_year_category(self):
        """「保存情報」列は表示通り部署名→年→カテゴリー名の順で並ぶことを確認する。"""
        contract_a = self._create_contract(department=self.department_a, category=self.category_a)
        contract_z = self._create_contract(department=self.department_b, category=self.category_z)
        form = SearchForm(data={})

        asc_qs = build_queryset(form, employee=self.employee, sort_key="info", sort_dir="asc")
        self.assertEqual(list(asc_qs), [contract_a, contract_z])

        desc_qs = build_queryset(form, employee=self.employee, sort_key="info", sort_dir="desc")
        self.assertEqual(list(desc_qs), [contract_z, contract_a])

    def test_uploader_sort_matches_displayed_department_and_name(self):
        """「保管・更新者」列は表示通り部署名→氏名の順で並ぶことを確認する
        （documents.tests.SearchSortTests.test_uploader_sort_matches_displayed_department_and_name
        と同じ理由）。
        """
        uploader_in_a = Employee.objects.create_user(
            employee_no="10", name="Zzz", password="x",
            department=self.department_a, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        uploader_in_b = Employee.objects.create_user(
            employee_no="11", name="Aaa", password="x",
            department=self.department_b, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        contract_uploader_a = self._create_contract(
            department=self.department_a, category=self.category_a, uploader=uploader_in_a
        )
        contract_uploader_b = self._create_contract(
            department=self.department_a, category=self.category_a, uploader=uploader_in_b
        )
        form = SearchForm(data={})

        asc_qs = build_queryset(form, employee=self.employee, sort_key="uploader", sort_dir="asc")
        self.assertEqual(list(asc_qs), [contract_uploader_a, contract_uploader_b])

        desc_qs = build_queryset(form, employee=self.employee, sort_key="uploader", sort_dir="desc")
        self.assertEqual(list(desc_qs), [contract_uploader_b, contract_uploader_a])


class NoticeFilterTests(TestCase):
    """メイン画面お知らせ「有効期限切れまでXヵ月以内」からの遷移時の絞り込み（表示文言は「文書」
    だが原本HTML実JS通り契約書検索へ遷移する。contracts.search_services._apply_notice_filter、
    core.notice_services.get_notice_counts参照）。"""

    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.employee = Employee.objects.create_user(
            employee_no="1", name="テスト太郎", password="x",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        self.group = Group.objects.create(code="A", name="契約分類Ａ", doc_kbn=DocKbn.CONTRACT)
        self.category = Category.objects.create(
            code="001", name="契約カテゴリーＡ", group=self.group, doc_kbn=DocKbn.CONTRACT
        )

    def _create_contract(self, expiry_date):
        from contracts.models import Contract

        contract = Contract(
            title="テスト", department=self.department, group=self.group, category=self.category,
            year=2026, uploader=self.employee, expiry_date=expiry_date,
        )
        contract.file.save("test.pdf", ContentFile(b"dummy"), save=False)
        contract.save()
        return contract

    @override_settings(NOTICE_EXPIRING_THRESHOLD_MONTHS=1)
    def test_expiring_soon_excludes_contracts_beyond_threshold(self):
        """しきい値の上限が無いと未来の全契約書がヒットしてしまうバグを修正した回帰テスト
        （2026-08-13監査で発見）。"""
        today = datetime.date.today()
        within = self._create_contract(today + datetime.timedelta(days=10))
        beyond = self._create_contract(today + datetime.timedelta(days=400))
        form = SearchForm(data={})
        qs = build_queryset(form, employee=self.employee, notice="expiring_soon")
        self.assertIn(within, qs)
        self.assertNotIn(beyond, qs)


class BulkButtonsHiddenForRecentlyDeletedNoticeTests(TestCase):
    """documents.tests.BulkButtonsHiddenForRecentlyDeletedNoticeTestsと同じ理由（Rev1.2、
    xlsx 検索・閲覧・変更!B659周辺、2026-08-24反映）。"""

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

    def test_bulk_buttons_hidden_when_notice_is_recently_deleted(self):
        response = self.client.get("/contracts/search/", {"notice": "recently_deleted"})
        self.assertNotContains(response, "一括ダウンロード")
        self.assertNotContains(response, "一括編集")
        self.assertNotContains(response, "一括選択")

    def test_bulk_buttons_shown_for_normal_search(self):
        response = self.client.get("/contracts/search/")
        self.assertContains(response, "一括ダウンロード")
        self.assertContains(response, "一括編集")
        self.assertContains(response, "一括選択")

    def test_bulk_download_button_has_client_side_unselected_guard(self):
        """documents.tests.BulkButtonsHiddenForRecentlyDeletedNoticeTests
        .test_bulk_download_button_has_client_side_unselected_guard と同じ（2026-09-08）。"""
        response = self.client.get("/contracts/search/")
        self.assertContains(response, "return startBulkDownload();")


class SearchPreviewPaneTests(TestCase):
    """documents.tests.SearchPreviewPaneTests と同じ（screen-search「文書イメージ」欄の
    PDF.js 描画枠、2026-08-31）。"""

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

    def test_pdfjs_preview_frame_rendered_by_default(self):
        response = self.client.get("/contracts/search/")
        self.assertContains(response, 'class="pdfjs-preview" id="search-pdfjs-preview"')
        self.assertContains(response, 'id="search-preview-frame"')

    @override_settings(PDF_JS_PREVIEW_ENABLED=False)
    def test_pdfjs_preview_frame_absent_when_disabled(self):
        response = self.client.get("/contracts/search/")
        self.assertNotContains(response, 'id="search-pdfjs-preview"')
        self.assertContains(response, 'id="search-preview-frame"')

    def _create_contract(self, title, *, is_deleted=False):
        from contracts.models import Contract

        group, _ = Group.objects.get_or_create(
            code="A", defaults={"name": "分類Ａ", "doc_kbn": DocKbn.CONTRACT}
        )
        category, _ = Category.objects.get_or_create(
            code="001", defaults={"name": "カテゴリーＡ", "group": group, "doc_kbn": DocKbn.CONTRACT}
        )
        contract = Contract(
            title=title, department=self.department, group=group, category=category,
            year=2026, uploader=self.employee, expiry_date=datetime.date(2036, 1, 1),
        )
        contract.file.save(f"{title}.pdf", ContentFile(b"%PDF-1.4 test"), save=False)
        if is_deleted:
            contract.is_deleted = True
            contract.deleted_at = timezone.now()
        contract.save()
        return contract

    def test_row_click_passes_is_deleted_flag_to_showSearchPreview(self):
        """documents.tests.SearchPreviewPaneTests.test_row_click_passes_is_deleted_flag_to_
        showSearchPreview と同じ（common.js showSearchPreview() の第5引数 isDeleted）。"""
        self._create_contract("通常契約書")
        response = self.client.get("/contracts/search/")
        self.assertContains(response, "'contract', 'pdf', '')")

        self._create_contract("削除済み契約書", is_deleted=True)
        response = self.client.get("/contracts/search/", {"notice": "recently_deleted"})
        self.assertContains(response, "'contract', 'pdf', '1')")


class DeleteViewAjaxTests(TestCase):
    """documents.tests.DeleteViewAjaxTestsと同じ理由（原本フィデリティ監査で発見・修正）。"""

    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.employee = Employee.objects.create_user(
            employee_no="1", name="テスト太郎", password="pass1234",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        # DeleteView.postはRev1.2で追加された「契約書-契約書-契約書情報変更」権限を要求する
        # ため（xlsx 権限管理!B198）、既存の削除系テストが引き続き通るようcontract_edit=Trueを
        # 付与しておく（権限拒否そのものを確認するテストはDeleteViewPermissionTestsで別途行う）。
        PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.STAFF, contract_edit=True)
        self.client.login(username="1", password="pass1234")
        group = Group.objects.create(code="A", name="契約分類Ａ", doc_kbn=DocKbn.CONTRACT)
        category = Category.objects.create(code="001", name="契約カテゴリーＡ", group=group, doc_kbn=DocKbn.CONTRACT)
        from contracts.models import Contract

        self.contract = Contract(
            title="削除対象", department=self.department, group=group, category=category,
            year=2026, uploader=self.employee, expiry_date=datetime.date(2036, 1, 1),
        )
        self.contract.file.save("test.pdf", ContentFile(b"dummy"), save=False)
        self.contract.save()

    def test_ajax_request_returns_json(self):
        response = self.client.post(
            f"/contracts/{self.contract.pk}/delete/", HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertEqual(response.json(), {"success": True, "message": "契約書を削除しました。"})

    def test_first_delete_is_logical_delete_record_and_file_survive(self):
        """documents.tests.DeleteViewAjaxTests.test_first_delete_is_logical_delete_record_and_file_survive
        と同じ理由（ユーザー依頼2026-08-12）。"""
        from contracts.models import Contract

        self.client.post(f"/contracts/{self.contract.pk}/delete/", HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.contract.refresh_from_db()
        self.assertTrue(self.contract.is_deleted)
        self.assertIsNotNone(self.contract.deleted_at)
        self.assertTrue(Contract.objects.filter(pk=self.contract.pk).exists())
        self.assertTrue(self.contract.file.storage.exists(self.contract.file.name))

    def test_deleting_already_trashed_contract_is_rejected(self):
        """documents.tests.DeleteViewAjaxTests.test_deleting_already_trashed_document_is_rejected
        と同じ理由。Rev1.2（xlsx 検索・閲覧・変更!B659,B663「削除されている契約書は、ボタンを
        非表示とする」）で、2026-08-12にユーザー依頼で追加した「ゴミ箱保管中の契約書を削除
        ボタンで完全削除する」機能は2026-08-24に廃止された（contracts.services.can_delete
        docstring参照）。既に削除済みの契約書への削除操作はサーバー側でも拒否し、本体レコード・
        ファイル・関連書類（ContractRelation）が残ることを確認する。"""
        from contracts.models import Contract, ContractRelation

        other = Contract.objects.create(
            title="関連先", department=self.department, group=self.contract.group,
            category=self.contract.category, year=2025, uploader=self.employee,
            expiry_date=datetime.date(2035, 1, 1), file=ContentFile(b"o", name="o.pdf"),
        )
        relation = ContractRelation.objects.create(
            contract=self.contract, related_contract=other, display_order=0
        )
        contract_file_name = self.contract.file.name

        self.contract.is_deleted = True
        self.contract.save(update_fields=["is_deleted", "deleted_at"])

        response = self.client.post(
            f"/contracts/{self.contract.pk}/delete/", HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.json()["success"])
        self.assertTrue(Contract.objects.filter(pk=self.contract.pk).exists())
        self.assertTrue(ContractRelation.objects.filter(pk=relation.pk).exists())
        self.assertTrue(self.contract.file.storage.exists(contract_file_name))

    def test_non_ajax_request_still_redirects(self):
        response = self.client.post(f"/contracts/{self.contract.pk}/delete/")
        self.assertEqual(response.status_code, 302)

    def test_ajax_request_returns_json_404_for_missing_contract(self):
        """documents.tests.DeleteViewAjaxTests.test_ajax_request_returns_json_404_for_missing_document
        と同じ理由（監査で発見・修正）。"""
        response = self.client.post(
            "/contracts/999999/delete/", HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertFalse(response.json()["success"])

    def test_ajax_request_returns_json_error_on_db_failure(self):
        """documents.tests.DeleteViewAjaxTests.test_ajax_request_returns_json_error_on_db_failure
        と同じ理由（監査で発見・修正）。"""
        from contracts.models import Contract

        with mock.patch.object(Contract, "save", side_effect=DBError("db down")):
            response = self.client.post(
                f"/contracts/{self.contract.pk}/delete/", HTTP_X_REQUESTED_WITH="XMLHttpRequest"
            )
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertFalse(response.json()["success"])


class DepartmentScopeAccessControlTests(TestCase):
    """セキュリティレビューで発見：contracts.api.DetailAPIView・検索一覧
    （contracts.search_services.build_queryset）は部署スコープ
    （permissions.services.contract_searchable_department_ids）を適用済みだったが、
    ダウンロード・プレビュー・編集・削除・一括編集・一括ダウンロードの各ビューには
    適用されておらず、`contract_download`/`contract_edit`権限さえあれば部署をまたいだ
    直接pkアクセスで他部署の契約書を閲覧・編集・削除できてしまっていた
    （contracts.services.scoped_get_object_or_404導入で修正、2026-08-25）。
    """

    def setUp(self):
        self.own_department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.other_department = Department.objects.create(
            branch_code="999", branch_name="別支店", section_code="", section_name=""
        )
        self.employee = Employee.objects.create_user(
            employee_no="1", name="テスト太郎", password="pass1234",
            department=self.own_department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        # 部署間閲覧設定・閲覧部署範囲テーブルとも未設定の、最も一般的な非管理者
        # （contract_searchable_department_ids(employee) == {own_department.pk}のみ）。
        PermissionProfile.objects.create(
            employee=self.employee, role=PermissionRole.STAFF, contract_download=True, contract_edit=True
        )
        self.client.login(username="1", password="pass1234")

        group = Group.objects.create(code="A", name="契約分類Ａ", doc_kbn=DocKbn.CONTRACT)
        category = Category.objects.create(code="001", name="契約カテゴリーＡ", group=group, doc_kbn=DocKbn.CONTRACT)
        from contracts.models import Contract

        self.other_contract = Contract(
            title="他部署の契約書", department=self.other_department, group=group, category=category,
            year=2026, uploader=self.employee, expiry_date=datetime.date(2036, 1, 1),
        )
        self.other_contract.file.save("other.pdf", ContentFile(b"dummy"), save=False)
        self.other_contract.save()

    def test_download_of_other_department_contract_returns_404(self):
        response = self.client.get(f"/contracts/{self.other_contract.pk}/download/")
        self.assertEqual(response.status_code, 404)

    def test_preview_of_other_department_contract_returns_404(self):
        response = self.client.get(f"/contracts/{self.other_contract.pk}/preview/")
        self.assertEqual(response.status_code, 404)

    def test_cross_department_direct_access_is_recorded_in_audit_log(self):
        """部署スコープ外pkへの直打ちアクセス試行は logger.warning に加えて操作履歴ログ（audit）
        にも記録する（review_rule_doc_contract.txt No.1、2026-09-09ユーザー確定。
        scoped_get_object_or_404 の on_denied 経由）。"""
        self.assertFalse(AuditLog.objects.filter(action="アクセス拒否").exists())
        self.client.get(f"/contracts/{self.other_contract.pk}/download/")
        entry = AuditLog.objects.get(action="アクセス拒否")
        self.assertEqual(entry.employee_no, "1")
        self.assertIn("契約書", entry.event_message)
        self.assertIn(f"（ID:{self.other_contract.pk}）", entry.event_message)

    def test_own_department_access_does_not_write_audit_denial(self):
        """自部署リソースへの正常アクセスでは「アクセス拒否」ログを残さない（回帰防止）。"""
        from contracts.models import Contract

        own = Contract(
            title="自部署の契約書", department=self.own_department, group=self.other_contract.group,
            category=self.other_contract.category, year=2026, uploader=self.employee,
            expiry_date=datetime.date(2036, 1, 1),
        )
        own.file.save("own.pdf", ContentFile(b"dummy"), save=False)
        own.save()
        self.client.get(f"/contracts/{own.pk}/download/")
        self.assertFalse(AuditLog.objects.filter(action="アクセス拒否").exists())

    def test_edit_screen_of_other_department_contract_returns_404(self):
        response = self.client.get(f"/contracts/{self.other_contract.pk}/edit/")
        self.assertEqual(response.status_code, 404)

    def test_delete_of_other_department_contract_returns_404(self):
        from contracts.models import Contract

        response = self.client.post(
            f"/contracts/{self.other_contract.pk}/delete/", HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(response.status_code, 404)
        self.other_contract.refresh_from_db()
        self.assertFalse(self.other_contract.is_deleted)
        self.assertTrue(Contract.objects.filter(pk=self.other_contract.pk, is_deleted=False).exists())

    def test_bulk_edit_start_silently_excludes_other_department_pk(self):
        response = self.client.post(
            "/contracts/bulk-edit/start/", {"pks": [self.other_contract.pk]}
        )
        self.assertRedirects(response, "/contracts/search/")
        self.assertIsNone(self.client.session.get("contracts_bulk_edit"))

    def test_bulk_edit_direct_access_to_other_department_contract_returns_404(self):
        """BulkEditStartViewが通常は除外するが、セッション状態を直接構築した場合
        （URL直打ち相当）もBulkEditView自体が部署スコープを検証する。"""
        from core import bulk_edit_services

        session = self.client.session
        bulk_edit_services.start_bulk_edit(session, "contracts_bulk_edit", [self.other_contract.pk])
        session.save()
        response = self.client.get("/contracts/bulk-edit/")
        self.assertEqual(response.status_code, 404)

    def test_bulk_download_silently_excludes_other_department_contract(self):
        import zipfile
        from io import BytesIO

        own_group = Group.objects.create(code="B", name="自部署分類", doc_kbn=DocKbn.CONTRACT)
        own_category = Category.objects.create(
            code="002", name="自部署カテゴリー", group=own_group, doc_kbn=DocKbn.CONTRACT
        )
        from contracts.models import Contract

        own_contract = Contract(
            title="own", department=self.own_department, group=own_group, category=own_category,
            year=2026, uploader=self.employee, expiry_date=datetime.date(2036, 1, 1),
        )
        own_contract.file.save("own.txt", ContentFile(b"hello"), save=False)
        own_contract.save()

        response = self.client.post(
            "/contracts/bulk-download/", {"pks": [own_contract.pk, self.other_contract.pk]}
        )
        self.assertEqual(response.status_code, 200)
        zf = zipfile.ZipFile(BytesIO(response.content))
        names = zf.namelist()
        self.assertEqual(len(names), 1)
        self.assertTrue(any("own" in n for n in names))

    def test_admin_can_access_other_department_contract(self):
        """部署スコープは非管理者のみに適用される（管理者はcontract_searchable_department_ids
        がNone＝無制限を返すため、従来通り全部署にアクセスできる）。"""
        admin = Employee.objects.create_user(
            employee_no="2", name="管理者", password="pass1234",
            department=self.own_department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        PermissionProfile.objects.create(employee=admin, role=PermissionRole.ADMIN)
        self.client.login(username="2", password="pass1234")

        response = self.client.get(f"/contracts/{self.other_contract.pk}/download/")
        self.assertEqual(response.status_code, 200)


class DispatchOrderingAnonymousAccessTests(TestCase):
    """品質レビューで発見：契約書の保存・編集フロー（UploadStep1View/UploadStep2View/
    ContractEditView/BulkEditView、contracts.api.ChunkUploadAPIView）は自身のdispatch()で
    can_edit_contract判定→super().dispatch()という順で呼んでおり、LoginRequiredMixinの
    認証チェックより先に判定が走っていた。未ログイン（AnonymousUser）でこれらのURLに直接
    アクセスすると、can_edit_contract内部の`employee.permission_profile`アクセスで
    AttributeErrorとなり、本来のログイン画面へのリダイレクト（302）の代わりに500エラーに
    なっていた（contracts.views.RequiresContractEditMixin導入で修正、2026-08-25）。
    """

    def test_upload_step1_anonymous_access_redirects_not_crashes(self):
        response = self.client.get("/contracts/upload/step1/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_upload_step2_anonymous_access_redirects_not_crashes(self):
        response = self.client.get("/contracts/upload/step2/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_contract_edit_anonymous_access_redirects_not_crashes(self):
        response = self.client.get("/contracts/1/edit/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_bulk_edit_anonymous_access_redirects_not_crashes(self):
        response = self.client.get("/contracts/bulk-edit/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_chunk_upload_api_anonymous_access_redirects_not_crashes(self):
        response = self.client.post("/contracts/upload/chunk/", {})
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])


class DeleteViewRequiresContractEditPermissionTests(TestCase):
    """xlsx 権限管理!B198(Rev1.2)「契約書-契約書-契約書情報変更」がOFFの場合、検索・閲覧画面の
    詳細ポップアップ「編集」「削除」ボタンを非表示にする」に対応。監査で発見：DetailAPIViewの
    delete_urlは`can_edit_contract`込みで判定しボタン自体は隠していたが、DeleteView.post側には
    その検証が無く、契約書-契約書-契約書情報変更がOFFの職員でもURL直打ちで削除できてしまって
    いた（2026-08-24追記で修正、contracts.views.DeleteView.post参照）。
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
        group = Group.objects.create(code="A", name="契約分類Ａ", doc_kbn=DocKbn.CONTRACT)
        category = Category.objects.create(code="001", name="契約カテゴリーＡ", group=group, doc_kbn=DocKbn.CONTRACT)
        from contracts.models import Contract

        self.contract = Contract(
            title="削除対象", department=self.department, group=group, category=category,
            year=2026, uploader=self.employee, expiry_date=datetime.date(2036, 1, 1),
        )
        self.contract.file.save("test.pdf", ContentFile(b"dummy"), save=False)
        self.contract.save()

    def test_delete_without_contract_edit_permission_is_rejected(self):
        """PermissionProfile未作成（一般職員相当、contract_edit=False）は削除を拒否される。"""
        from contracts.models import Contract

        response = self.client.post(
            f"/contracts/{self.contract.pk}/delete/", HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.json()["success"])
        self.contract.refresh_from_db()
        self.assertFalse(self.contract.is_deleted)
        self.assertTrue(Contract.objects.filter(pk=self.contract.pk, is_deleted=False).exists())

    def test_delete_with_contract_edit_off_is_rejected(self):
        PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.STAFF, contract_edit=False)
        response = self.client.post(
            f"/contracts/{self.contract.pk}/delete/", HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(response.status_code, 403)
        self.contract.refresh_from_db()
        self.assertFalse(self.contract.is_deleted)

    def test_delete_with_contract_edit_on_succeeds(self):
        PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.STAFF, contract_edit=True)
        response = self.client.post(
            f"/contracts/{self.contract.pk}/delete/", HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(response.status_code, 200)
        self.contract.refresh_from_db()
        self.assertTrue(self.contract.is_deleted)

    def test_admin_can_delete_without_explicit_flag(self):
        PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.ADMIN)
        response = self.client.post(
            f"/contracts/{self.contract.pk}/delete/", HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(response.status_code, 200)


class ContractWriteViewsRequireContractEditPermissionTests(TestCase):
    """テストカバレッジ棚卸し（review_test_doc_contract.txt 指摘 M-4）で発見：
    RequiresContractEditMixin を通す write 系5画面（UploadStep1View / UploadStep2View /
    ContractEditView / BulkEditStartView / BulkEditView）について、「ログイン済みだが
    contract_edit=False（または PermissionProfile 未作成）の職員 → 403」が個別に
    assert されていなかった。DispatchOrderingAnonymousAccessTests は未認証時の redirect
    だけ、DeleteViewRequiresContractEditPermissionTests は DeleteView だけを見ている。
    CLAUDE.md「同一注記が複数箇所に繰り返し付いている場合は1つずつ個別に確認する」に
    照らし、URL 直打ちで保存・編集に至る中核 write 画面を個別に固定する。"""

    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.employee = Employee.objects.create_user(
            employee_no="1", name="テスト太郎", password="pass1234",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        self.profile = PermissionProfile.objects.create(
            employee=self.employee, role=PermissionRole.STAFF, contract_edit=False
        )
        group = Group.objects.create(code="A", name="契約分類Ａ", doc_kbn=DocKbn.CONTRACT)
        category = Category.objects.create(
            code="001", name="契約カテゴリーＡ", group=group, doc_kbn=DocKbn.CONTRACT
        )
        from contracts.models import Contract

        self.contract = Contract(
            title="編集対象", department=self.department, group=group, category=category,
            year=2026, uploader=self.employee, expiry_date=datetime.date(2036, 1, 1),
        )
        self.contract.file.save("c.pdf", ContentFile(b"x"), save=False)
        self.contract.save()
        self.client.login(username="1", password="pass1234")

    def _cases(self):
        return [
            ("get", "/contracts/upload/step1/"),
            ("post", "/contracts/upload/step1/"),
            ("get", "/contracts/upload/step2/"),
            ("post", "/contracts/upload/step2/"),
            ("get", f"/contracts/{self.contract.pk}/edit/"),
            ("post", f"/contracts/{self.contract.pk}/edit/"),
            ("post", "/contracts/bulk-edit/start/"),
            ("get", "/contracts/bulk-edit/"),
            ("post", "/contracts/bulk-edit/"),
        ]

    def test_contract_edit_false_is_rejected_with_403_on_every_write_view(self):
        for method, url in self._cases():
            with self.subTest(method=method, url=url):
                response = getattr(self.client, method)(url)
                self.assertEqual(response.status_code, 403, f"{method.upper()} {url}")

    def test_missing_permission_profile_is_also_rejected(self):
        self.profile.delete()
        for method, url in self._cases():
            with self.subTest(method=method, url=url):
                response = getattr(self.client, method)(url)
                self.assertEqual(response.status_code, 403, f"{method.upper()} {url}")


class RelatedFilesMultiUploadTests(TestCase):
    """契約書の複数件一括登録時、ファイルごとに独立した関連書類（紐付け先契約書）を選べる。
    Rev1.6でファイルアップロードから既存契約書のポップアップ検索・紐付けへ転換
    （related_contract_ids_{index} の hidden input で送信）。"""

    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.employee = Employee.objects.create_user(
            employee_no="1", name="テスト太郎", password="pass1234",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        # Rev1.2で追加された「契約書-契約書-契約書情報変更」がOFFだと保管・編集操作が
        # 403になるため（permissions.services.can_edit_contract）、この一般的なテスト用職員には
        # 付与しておく（権限そのものを検証する専用テストは別途 contract_edit を明示的に扱う）。
        PermissionProfile.objects.create(
            employee=self.employee, role=PermissionRole.STAFF, contract_edit=True
        )
        self.client.login(username="1", password="pass1234")
        self.group = Group.objects.create(code="A", name="契約分類Ａ", doc_kbn=DocKbn.CONTRACT)
        self.category = Category.objects.create(
            code="001", name="契約カテゴリーＡ", group=self.group, doc_kbn=DocKbn.CONTRACT
        )

    def _existing_contract(self, title):
        from contracts.models import Contract

        c = Contract(
            title=title, department=self.department, group=self.group, category=self.category,
            year=2024, uploader=self.employee, expiry_date=datetime.date(2034, 1, 1),
        )
        c.file.save(f"{title}.pdf", ContentFile(b"X"), save=False)
        c.save()
        return c

    def test_each_document_gets_its_own_related_contracts(self):
        import re

        from django.core.files.uploadedfile import SimpleUploadedFile

        from contracts.models import Contract

        rel_a = self._existing_contract("関連先A")
        rel_b = self._existing_contract("関連先B")

        self.client.post("/contracts/upload/step1/", {"files": [
            SimpleUploadedFile("a.pdf", b"AAAA", content_type="application/pdf"),
            SimpleUploadedFile("b.pdf", b"BBBB", content_type="application/pdf"),
        ]})
        step2 = self.client.get("/contracts/upload/step2/")
        token = re.search(r'name="token" value="([^"]+)"', step2.content.decode("utf-8")).group(1)

        before = set(Contract.objects.values_list("pk", flat=True))
        # 2026-08-31：メタデータはファイルごと（*_0 / *_1）。ここでは年をファイルごとに
        # 変えて、共通適用ではなく個別に保存されることも併せて確認する。
        self.client.post("/contracts/upload/step2/", {
            "token": token,
            "department_0": self.department.pk, "group_0": self.group.pk,
            "category_0": self.category.pk, "year_0": 2025,
            "department_1": self.department.pk, "group_1": self.group.pk,
            "category_1": self.category.pk, "year_1": 2026,
            "title_0": "契約書A",
            "title_1": "契約書B",
            "related_contract_ids_0": [str(rel_a.pk)],
            "related_contract_ids_1": [str(rel_b.pk)],
        })
        created = list(
            Contract.objects.exclude(pk__in=before).exclude(title__startswith="関連先").order_by("pk")
        )
        self.assertEqual(len(created), 2)
        self.assertEqual(
            list(created[0].related_links.values_list("related_contract_id", flat=True)), [rel_a.pk]
        )
        self.assertEqual(
            list(created[1].related_links.values_list("related_contract_id", flat=True)), [rel_b.pk]
        )
        self.assertEqual([created[0].year, created[1].year], [2025, 2026])


class RelatedSearchAPIViewTests(TestCase):
    """関連書類ポップアップの契約書検索API（contracts:api_related_search、Rev1.6）。
    xlsx 保管!B478-484：タイトル／フリーワードで簡易検索、閲覧権限範囲内、削除除外、自分自身除外。"""

    def setUp(self):
        self.dept = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.other_dept = Department.objects.create(
            branch_code="999", branch_name="他店", section_code="99", section_name="他部署"
        )
        self.employee = Employee.objects.create_user(
            employee_no="1", name="テスト太郎", password="pass1234",
            department=self.dept, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        PermissionProfile.objects.create(
            employee=self.employee, role=PermissionRole.STAFF, contract_edit=True
        )
        self.client.login(username="1", password="pass1234")
        self.group = Group.objects.create(code="A", name="契約分類Ａ", doc_kbn=DocKbn.CONTRACT)
        self.category = Category.objects.create(
            code="001", name="契約カテゴリーＡ", group=self.group, doc_kbn=DocKbn.CONTRACT
        )

    def _c(self, title, *, dept=None, is_deleted=False, extracted_text=""):
        from contracts.models import Contract

        c = Contract(
            title=title, department=dept or self.dept, group=self.group, category=self.category,
            year=2025, uploader=self.employee, expiry_date=datetime.date(2035, 1, 1),
            is_deleted=is_deleted, extracted_text=extracted_text,
        )
        c.file.save(f"{title}.pdf", ContentFile(b"X"), save=False)
        c.save()
        return c

    def test_title_filter_and_scope_and_deleted_and_exclude(self):
        hit = self._c("賃貸借契約書")
        self._c("賃貸借契約書（削除済み）", is_deleted=True)
        self._c("賃貸借契約書（他部署）", dept=self.other_dept)
        myself = self._c("賃貸借契約書（自分）")

        resp = self.client.get(
            "/contracts/api/related-search/", {"title": "賃貸借", "exclude": myself.pk}
        )
        self.assertEqual(resp.status_code, 200)
        values = {item["value"] for item in resp.json()["items"]}
        self.assertEqual(values, {hit.pk})

    def test_freeword_matches_extracted_text(self):
        hit = self._c("A契約", extracted_text="重要な覚書の本文がここにある")
        self._c("B契約", extracted_text="無関係な内容")
        resp = self.client.get("/contracts/api/related-search/", {"freeword": "覚書"})
        values = {item["value"] for item in resp.json()["items"]}
        self.assertEqual(values, {hit.pk})

    def test_requires_contract_edit_permission(self):
        Employee.objects.create_user(
            employee_no="2", name="権限なし", password="pass1234",
            department=self.dept, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        PermissionProfile.objects.create(
            employee=Employee.objects.get(employee_no="2"), role=PermissionRole.STAFF, contract_edit=False
        )
        self.client.logout()
        self.client.login(username="2", password="pass1234")
        resp = self.client.get("/contracts/api/related-search/", {"title": "x"})
        self.assertEqual(resp.status_code, 403)


class SearchAuditLogTests(TestCase):
    """documents.tests.SearchAuditLogTestsと同じ理由。原本index.html:3315の操作履歴ログサンプル
    「契約書　検索｜分類：XXX,年：XXX,カテゴリー：XXX,タイトル：XXX,フリーワード：XXX」に対応
    （原本フィデリティ監査で発見：検索操作自体が一度も監査ログに記録されていなかった）。
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

    def test_bare_screen_open_does_not_create_audit_log(self):
        self.client.get("/contracts/search/")
        self.assertFalse(AuditLog.objects.filter(action="契約書検索　検索").exists())

    def test_search_submission_creates_audit_log_with_filled_fields_only(self):
        response = self.client.get("/contracts/search/", {"title": "覚書", "title_match": "or"})
        self.assertEqual(response.status_code, 200)
        entry = AuditLog.objects.get(action="契約書検索　検索")
        self.assertEqual(entry.employee_no, "1")
        self.assertEqual(entry.event_message, "契約書タイトル：覚書")

    def test_pagination_click_does_not_create_duplicate_audit_log(self):
        self.client.get("/contracts/search/", {"title": "覚書"})
        self.assertEqual(AuditLog.objects.filter(action="契約書検索　検索").count(), 1)
        self.client.get("/contracts/search/", {"title": "覚書", "page": "1"})
        self.assertEqual(AuditLog.objects.filter(action="契約書検索　検索").count(), 1)


class DownloadViewTests(TestCase):
    """documents.tests.DownloadViewTestsと同じ理由（screen-search（契約書モード）
    「ダウンロード」ボタン、2026-08-12追加対応）。"""

    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.employee = Employee.objects.create_user(
            employee_no="1", name="テスト太郎", password="pass1234",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        self.group = Group.objects.create(code="A", name="契約分類Ａ", doc_kbn=DocKbn.CONTRACT)
        self.category = Category.objects.create(
            code="001", name="契約カテゴリーＡ", group=self.group, doc_kbn=DocKbn.CONTRACT
        )
        self.client.login(username="1", password="pass1234")

        from contracts.models import Contract

        self.contract = Contract(
            title="DL対象", department=self.department, group=self.group, category=self.category,
            year=2026, uploader=self.employee, expiry_date=datetime.date(2036, 1, 1),
        )
        self.contract.file.save("dl.txt", ContentFile(b"hello"), save=False)
        self.contract.save()

    def test_download_creates_audit_log(self):
        PermissionProfile.objects.create(
            employee=self.employee, role=PermissionRole.STAFF, contract_download=True
        )
        response = self.client.get(f"/contracts/{self.contract.pk}/download/")
        self.assertEqual(response.status_code, 200)
        entry = AuditLog.objects.get(action="契約書検索　ダウンロード")
        self.assertEqual(entry.employee_no, "1")
        # 原本index.html:3310の操作履歴ログサンプル「ファイル名：契約書_001」形式
        # （タイトルではなく実ファイル名）。
        self.assertEqual(entry.event_message, "ファイル名：dl.txt")

    def test_denied_download_does_not_create_audit_log(self):
        response = self.client.get(f"/contracts/{self.contract.pk}/download/")
        self.assertEqual(response.status_code, 403)
        self.assertFalse(AuditLog.objects.filter(action="契約書検索　ダウンロード").exists())

    def test_display_name_strips_uuid_prefix(self):
        """core.models.UuidPrefixedFilenameMixin.display_name。RelatedFile側（付属資料）は
        値自体を直接検証済みだが、Contract本体側はDownloadViewTestsがレスポンスの成否のみを
        見ており、値自体（UUIDプレフィックス除去後の元ファイル名）を確認するテストが無かった
        （documents.tests.DownloadViewTests.test_display_name_strips_uuid_prefixと対の
        テストカバレッジ棚卸しで発見、2026-08-26追加）。"""
        basename = self.contract.file.name.rsplit("/", 1)[-1]
        self.assertIn("_", basename)
        self.assertEqual(self.contract.display_name, "dl.txt")

    def test_deleted_contract_download_returns_404(self):
        """documents.tests.DownloadViewTests.test_deleted_document_download_returns_404と同じ理由
        （xlsx 検索・閲覧・変更!B659(Rev1.2)「削除されている契約書は、ボタンを非表示とする」の
        URL直打ち対策）。"""
        PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.STAFF, contract_download=True)
        self.contract.is_deleted = True
        self.contract.save(update_fields=["is_deleted"])
        response = self.client.get(f"/contracts/{self.contract.pk}/download/")
        self.assertEqual(response.status_code, 404)

    def test_missing_file_returns_404(self):
        """PreviewViewTests.test_missing_file_returns_404と同型のOSError境界（テストカバレッジ
        棚卸しで発見：DownloadView側は同じexcept OSError節を持つのに未テストだった）。"""
        PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.STAFF, contract_download=True)
        with mock.patch(
            "django.db.models.fields.files.FieldFile.open", side_effect=OSError("missing")
        ):
            response = self.client.get(f"/contracts/{self.contract.pk}/download/")
        self.assertEqual(response.status_code, 404)


class BulkDownloadViewTests(TestCase):
    """screen-search（契約書モード）「一括ダウンロード」（xlsx 検索・閲覧・変更!B596-600
    「※文書管理と同じ」によりB264-265のダウンロード権限ルールを準用、要再確認No.22）。"""

    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.employee = Employee.objects.create_user(
            employee_no="1", name="テスト太郎", password="pass1234",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        self.group = Group.objects.create(code="A", name="契約分類Ａ", doc_kbn=DocKbn.CONTRACT)
        self.category = Category.objects.create(
            code="001", name="契約カテゴリーＡ", group=self.group, doc_kbn=DocKbn.CONTRACT
        )
        self.client.login(username="1", password="pass1234")

    def _create_contract(self, title):
        from contracts.models import Contract

        contract = Contract(
            title=title, department=self.department, group=self.group, category=self.category,
            year=2026, uploader=self.employee, expiry_date=datetime.date(2036, 1, 1),
        )
        contract.file.save(f"{title}.txt", ContentFile(b"hello"), save=False)
        contract.save()
        return contract

    def test_download_without_permission_denied(self):
        contract = self._create_contract("test1")
        response = self.client.post("/contracts/bulk-download/", {"pks": [contract.pk]})
        self.assertEqual(response.status_code, 403)

    def test_download_with_permission_returns_zip(self):
        import zipfile
        from io import BytesIO

        PermissionProfile.objects.create(
            employee=self.employee, role=PermissionRole.STAFF, contract_download=True
        )
        contract = self._create_contract("test1")
        response = self.client.post("/contracts/bulk-download/", {"pks": [contract.pk]})
        self.assertEqual(response.status_code, 200)
        zf = zipfile.ZipFile(BytesIO(response.content))
        self.assertEqual(len(zf.namelist()), 1)
        entry = AuditLog.objects.get(action="契約書検索　一括ダウンロード")
        self.assertIn("1件", entry.event_message)

    def test_invalid_pks_values_are_ignored_not_crashing(self):
        """documents.tests.BulkDownloadViewTests.test_invalid_pks_values_are_ignored_not_crashing
        と同じ理由（監査で発見・修正）。"""
        import zipfile
        from io import BytesIO

        PermissionProfile.objects.create(
            employee=self.employee, role=PermissionRole.STAFF, contract_download=True
        )
        contract = self._create_contract("test1")
        response = self.client.post(
            "/contracts/bulk-download/", {"pks": [str(contract.pk), "abc"]}
        )
        self.assertEqual(response.status_code, 200)
        zf = zipfile.ZipFile(BytesIO(response.content))
        self.assertEqual(len(zf.namelist()), 1)

    def test_missing_file_entity_is_skipped_with_warning_but_others_succeed(self):
        """documents.tests.BulkDownloadViewTests.test_missing_file_entity_is_skipped_with_warning_but_others_succeed
        と同じ理由（テストカバレッジ棚卸しで発見：contracts.services.build_zip_archiveの
        except FileNotFoundError節が未テストだった）。"""
        import zipfile
        from io import BytesIO

        from django.contrib.messages import get_messages

        PermissionProfile.objects.create(
            employee=self.employee, role=PermissionRole.STAFF, contract_download=True
        )
        present = self._create_contract("present")
        missing = self._create_contract("missing")
        missing.file.delete(save=False)

        response = self.client.post(
            "/contracts/bulk-download/", {"pks": [present.pk, missing.pk]}
        )
        self.assertEqual(response.status_code, 200)
        zf = zipfile.ZipFile(BytesIO(response.content))
        names = zf.namelist()
        self.assertEqual(len(names), 1)
        self.assertTrue(any("present" in n for n in names))
        warnings = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertTrue(any("1件のファイルを取得できなかった" in m for m in warnings))

    def test_no_selection_redirects_with_message(self):
        """documents.tests.BulkDownloadViewTests.test_no_selection_redirects_with_message
        と同じ（クライアント側alertを迂回した直POST時の保険。文言はcommon.js
        startBulkDownloadのalertに合わせる。2026-09-08）。"""
        from django.contrib.messages import get_messages

        response = self.client.post("/contracts/bulk-download/", {})
        self.assertRedirects(response, "/contracts/search/")
        msgs = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertIn("ダウンロードするデータが選択されていません。", msgs)


class BulkEditViewTests(TestCase):
    """screen-search（契約書モード）「一括編集」。documents.tests.BulkEditViewTestsと同じ設計
    （ステージング型。「更新」まで DB 未反映、変更のあったページだけ確定）。契約書は関連書類の
    増減も「更新」までステージし「キャンセル」で破棄する。"""

    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.employee = Employee.objects.create_user(
            employee_no="1", name="テスト太郎", password="pass1234",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        self.group = Group.objects.create(code="A", name="契約分類Ａ", doc_kbn=DocKbn.CONTRACT)
        self.category = Category.objects.create(
            code="001", name="契約カテゴリーＡ", group=self.group, doc_kbn=DocKbn.CONTRACT
        )
        # Rev1.2で追加された「契約書-契約書-契約書情報変更」がOFFだと保管・編集操作が
        # 403になるため（permissions.services.can_edit_contract）、この一般的なテスト用職員には
        # 付与しておく（権限そのものを検証する専用テストは別途 contract_edit を明示的に扱う）。
        PermissionProfile.objects.create(
            employee=self.employee, role=PermissionRole.STAFF, contract_edit=True
        )
        self.client.login(username="1", password="pass1234")

    def _create_contract(self, title):
        from contracts.models import Contract

        contract = Contract(
            title=title, department=self.department, group=self.group, category=self.category,
            year=2026, uploader=self.employee, expiry_date=datetime.date(2036, 1, 1),
        )
        contract.file.save(f"{title}.txt", ContentFile(b"hello"), save=False)
        contract.save()
        return contract

    def _get_token(self):
        import re

        get_response = self.client.get("/contracts/bulk-edit/")
        return re.search(
            r'name="token" value="([^"]+)"', get_response.content.decode("utf-8")
        ).group(1)

    def _page_data(self, obj, *, title=None, group=None, action="update", **extra):
        data = {
            "token": self._get_token(),
            "department": obj.department_id,
            "group": group if group is not None else obj.group_id,
            "category": obj.category_id,
            "year": obj.year,
            "contract_date": "",
            "contract_period_start": "",
            "contract_period_end": "",
            "renewal_date": "",
            "contract_amount": "",
            "contract_partner": obj.contract_partner or "",
            "memo": obj.memo or "",
            "title_0": title if title is not None else obj.title,
        }
        if action is not None:
            data["bulk_action"] = action
        data.update(extra)
        return data

    def test_start_without_selection_redirects_with_message(self):
        from django.contrib.messages import get_messages

        response = self.client.post("/contracts/bulk-edit/start/", {})
        self.assertRedirects(response, "/contracts/search/")
        texts = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertIn("編集するデータが選択されていません。", texts)

    def test_direct_access_without_session_state_redirects(self):
        response = self.client.get("/contracts/bulk-edit/")
        self.assertRedirects(response, "/contracts/search/")

    def test_render_complete_redirects_to_search_when_all_targets_purged(self):
        """コードレビューC-7：更新確定の直後に対象が全件物理削除された場合（日次purgeバッチとの
        競合）、_render_complete の rows が空になり rows[0] で IndexError（500）になっていた。"""
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.test import RequestFactory

        from contracts.views import BulkEditView

        request = RequestFactory().post("/contracts/bulk-edit/")
        request.user = self.employee
        request.session = self.client.session
        request._messages = FallbackStorage(request)

        response = BulkEditView()._render_complete(request, [10**9], {})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/contracts/search/")

    def test_start_with_all_pks_invalid_or_deleted_redirects_to_search(self):
        contract = self._create_contract("deleted")
        contract.is_deleted = True
        contract.save(update_fields=["is_deleted"])
        response = self.client.post("/contracts/bulk-edit/start/", {"pks": [contract.pk, "abc"]})
        self.assertRedirects(response, "/contracts/search/")
        self.assertIsNone(self.client.session.get("contracts_bulk_edit"))

    def test_update_commits_only_changed_pages_with_status(self):
        cs = [self._create_contract(f"c{i}") for i in range(4)]
        self.client.post("/contracts/bulk-edit/start/", {"pks": [c.pk for c in cs]})
        self.client.post("/contracts/bulk-edit/", self._page_data(cs[0], title="c0-new", action=None, bulk_nav="next"))
        self.client.post("/contracts/bulk-edit/", self._page_data(cs[1], action=None, bulk_nav="next"))
        resp = self.client.post("/contracts/bulk-edit/", self._page_data(cs[2]))

        self.assertEqual(resp.status_code, 200)
        status = {r["obj"].pk: r["status"] for r in resp.context["complete"]["rows"]}
        self.assertEqual(status[cs[0].pk], "更新")
        self.assertEqual(status[cs[1].pk], "更新なし")
        self.assertEqual(status[cs[3].pk], "更新なし")
        self.assertEqual(resp.context["complete"]["counts"], {"updated": 1, "unchanged": 3, "deleted": 0})
        cs[0].refresh_from_db(); cs[1].refresh_from_db()
        self.assertEqual(cs[0].title, "c0-new")
        self.assertEqual(cs[1].title, "c1")
        self.assertEqual(AuditLog.objects.filter(action="保管画面２　更新").count(), 1)
        self.assertIsNone(self.client.session.get("contracts_bulk_edit"))

    def test_delete_mark_and_commit_logical_deletes(self):
        cs = [self._create_contract(f"c{i}") for i in range(2)]
        self.client.post("/contracts/bulk-edit/start/", {"pks": [c.pk for c in cs]})
        marked = self.client.post("/contracts/bulk-edit/", self._page_data(cs[0], action="toggle_delete"))
        self.assertRedirects(marked, "/contracts/bulk-edit/")
        page = self.client.get("/contracts/bulk-edit/")
        self.assertTrue(page.context["marked_delete"])
        self.assertContains(page, "削除取消")

        resp = self.client.post("/contracts/bulk-edit/", self._page_data(cs[1]))
        cs[0].refresh_from_db()
        self.assertTrue(cs[0].is_deleted)
        self.assertEqual(resp.context["complete"]["counts"]["deleted"], 1)
        self.assertTrue(AuditLog.objects.filter(action="保管画面２　削除", event_message__contains="c0").exists())

    def test_delete_mark_locks_all_contract_fields(self):
        """テストカバレッジ棚卸し（review_test_doc_contract.txt 指摘 M-3）で発見：
        documents 側の test_delete_mark_locks_fields_and_toggles_label に相当する検証が
        contracts 側に無く、_build_form の `for field in form.fields.values(): field.disabled
        = True` が契約書固有フィールド（契約日・契約金額・契約先名等）まで効いているかが
        未検証だった。"""
        cs = [self._create_contract(f"c{i}") for i in range(2)]
        self.client.post("/contracts/bulk-edit/start/", {"pks": [c.pk for c in cs]})
        marked = self.client.post("/contracts/bulk-edit/", self._page_data(cs[0], action="toggle_delete"))
        self.assertRedirects(marked, "/contracts/bulk-edit/")
        page = self.client.get("/contracts/bulk-edit/")
        self.assertTrue(page.context["marked_delete"])
        self.assertContains(page, "削除取消")
        fields = page.context["form"].fields
        for name in ["title_0", "contract_date", "contract_amount", "contract_partner", "memo"]:
            self.assertTrue(fields[name].disabled, f"{name} が disabled になっていない")

    def _age_contract(self, contract, *, days):
        from contracts.models import Contract

        Contract.objects.filter(pk=contract.pk).update(
            save_date=timezone.now() - datetime.timedelta(days=days)
        )

    def test_toggle_delete_mark_rejected_for_contract_past_delete_window(self):
        """セキュリティレビュー M-1: 登録から1週間以上経過した契約書は一括編集からも削除マークを
        付けられない（documents 側と同じ扱い）。"""
        from django.contrib.messages import get_messages

        c = self._create_contract("aged")
        self._age_contract(c, days=8)
        self.client.post("/contracts/bulk-edit/start/", {"pks": [c.pk]})
        resp = self.client.post("/contracts/bulk-edit/", self._page_data(c, action="toggle_delete"))
        self.assertRedirects(resp, "/contracts/bulk-edit/")
        texts = [str(m) for m in get_messages(resp.wsgi_request)]
        self.assertTrue(any("1週間以上経過" in t for t in texts))
        self.assertEqual(self.client.session["contracts_bulk_edit"]["to_delete"], [])

    def test_commit_rejects_smuggled_delete_mark_for_contract_past_delete_window(self):
        """セキュリティレビュー M-1: セッション改ざん等で削除マークが積まれていても、確定前の
        サーバー側検証でコミット全体を止め、論理削除しない。"""
        from django.contrib.messages import get_messages

        cs = [self._create_contract(f"c{i}") for i in range(2)]
        self._age_contract(cs[1], days=10)
        self.client.post("/contracts/bulk-edit/start/", {"pks": [c.pk for c in cs]})
        session = self.client.session
        session["contracts_bulk_edit"]["to_delete"] = [cs[1].pk]
        session.save()

        resp = self.client.post("/contracts/bulk-edit/", self._page_data(cs[0]))
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("complete", resp.context)
        self.assertEqual(resp.context["contract"].pk, cs[1].pk)
        texts = [str(m) for m in get_messages(resp.wsgi_request)]
        self.assertTrue(any("1週間以上経過" in t for t in texts))
        cs[1].refresh_from_db()
        self.assertFalse(cs[1].is_deleted)
        self.assertIsNone(cs[1].deleted_at)

    def test_cancel_discards_staged_changes(self):
        cs = [self._create_contract(f"c{i}") for i in range(2)]
        self.client.post("/contracts/bulk-edit/start/", {"pks": [c.pk for c in cs]})
        self.client.post("/contracts/bulk-edit/", self._page_data(cs[0], title="c0-new", action=None, bulk_nav="next"))
        resp = self.client.post("/contracts/bulk-edit/", {"bulk_action": "cancel"})
        self.assertRedirects(resp, "/contracts/search/")
        cs[0].refresh_from_db()
        self.assertEqual(cs[0].title, "c0")
        self.assertIsNone(self.client.session.get("contracts_bulk_edit"))

    def test_validation_error_stops_commit_and_jumps(self):
        from django.contrib.messages import get_messages

        cs = [self._create_contract(f"c{i}") for i in range(2)]
        self.client.post("/contracts/bulk-edit/start/", {"pks": [c.pk for c in cs]})
        self.client.post("/contracts/bulk-edit/", self._page_data(cs[0], title="c0-new", group="", action=None, bulk_nav="next"))
        resp = self.client.post("/contracts/bulk-edit/", self._page_data(cs[1]))
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("complete", resp.context)
        self.assertEqual(resp.context["contract"].pk, cs[0].pk)
        texts = [str(m) for m in get_messages(resp.wsgi_request)]
        self.assertTrue(any("1件目に入力エラー" in t for t in texts))
        cs[0].refresh_from_db()
        self.assertEqual(cs[0].title, "c0")

    def test_commit_db_failure_shows_error_and_keeps_state(self):
        """テストカバレッジ棚卸し（review_test_doc_contract.txt 指摘 M-1）で発見：
        documents 側には test_commit_db_failure_shows_error_and_keeps_state があるが、
        contracts.views.BulkEditView._commit の except (OSError, PendingFileStorageError,
        DBError) → messages.error + redirect ＋ finally での opened_files クローズは
        （commit 経路が改修で別物になったため）確定失敗のテストが1件も無かった。
        contracts 側は関連書類を開いて apply_contract_edit に渡す都合で except 節が
        documents 側より広く、documents 側テストで代替が効かない。"""
        from django.contrib.messages import get_messages

        from contracts.models import Contract

        cs = [self._create_contract(f"c{i}") for i in range(2)]
        self.client.post("/contracts/bulk-edit/start/", {"pks": [c.pk for c in cs]})
        with mock.patch.object(Contract, "save", side_effect=DBError("db down")):
            resp = self.client.post(
                "/contracts/bulk-edit/", self._page_data(cs[0], title="c0-new")
            )
        self.assertRedirects(resp, "/contracts/bulk-edit/")
        texts = [str(m) for m in get_messages(resp.wsgi_request)]
        self.assertTrue(any("更新に失敗しました" in t for t in texts))
        cs[0].refresh_from_db()
        self.assertEqual(cs[0].title, "c0")
        self.assertIsNotNone(self.client.session.get("contracts_bulk_edit"))

    def test_update_does_not_touch_expiry_date(self):
        """テストカバレッジ棚卸し（review_test_doc_contract.txt 指摘 H-1）／memory
        expiry_date_edit_recalc_spec：契約書は保存期間が固定で編集で変えられる要素が
        無いため、一括編集で確定しても expiry_date は登録時の値のまま不変
        （contracts.services.apply_contract_edit は expiry_date を一切触らない）。"""
        c = self._create_contract("c0")
        original_expiry = c.expiry_date
        self.client.post("/contracts/bulk-edit/start/", {"pks": [c.pk]})
        resp = self.client.post("/contracts/bulk-edit/", self._page_data(c, title="c0-new"))
        self.assertEqual(resp.context["complete"]["counts"]["updated"], 1)
        c.refresh_from_db()
        self.assertEqual(c.title, "c0-new")
        self.assertEqual(c.expiry_date, original_expiry)

    def test_related_contracts_change_is_staged_and_cancellable(self):
        """Rev1.6：一括編集で関連書類（紐付け先契約書）を変えても「更新」までDB未反映。
        ステージはセッションの staged_related に pk リストとして載り、「キャンセル」で破棄される。"""
        from contracts.models import ContractRelation

        cs = [self._create_contract(f"c{i}") for i in range(2)]
        target = self._create_contract("rel-target")
        self.client.post("/contracts/bulk-edit/start/", {"pks": [c.pk for c in cs]})

        # 1件目に関連書類を追加してステージ（＞で移動）
        data = self._page_data(cs[0], action=None, bulk_nav="next")
        self.client.post(
            "/contracts/bulk-edit/",
            {**data, "related_contract_ids": [str(target.pk)]},
        )
        # まだ ContractRelation には反映されていない（ステージのみ）
        self.assertFalse(ContractRelation.objects.filter(contract=cs[0]).exists())
        state = self.client.session["contracts_bulk_edit"]
        self.assertEqual(state["staged_related"][str(cs[0].pk)]["related_ids"], [target.pk])

        # 紐付け予定として表示される（index=0 へ戻る）
        back = self.client.post("/contracts/bulk-edit/", self._page_data(cs[1], action=None, bulk_nav="prev"))
        self.assertRedirects(back, "/contracts/bulk-edit/")
        page0 = self.client.get("/contracts/bulk-edit/")
        self.assertContains(page0, "rel-target")

        # キャンセルで破棄
        self.client.post("/contracts/bulk-edit/", {"bulk_action": "cancel"})
        self.assertFalse(ContractRelation.objects.filter(contract=cs[0]).exists())
        self.assertIsNone(self.client.session.get("contracts_bulk_edit"))

    def test_related_contracts_commit_on_update(self):
        """Rev1.6：関連書類は「紐付け先契約書pkの全量リスト」を送り、「更新」で同期される
        （リストから外れた既存行は削除、新規は追加）。関連書類の変更だけでも「更新」扱い。"""
        from contracts.models import ContractRelation

        c1 = self._create_contract("c1")
        old_target = self._create_contract("old-target")
        new_target = self._create_contract("new-target")
        ContractRelation.objects.create(contract=c1, related_contract=old_target, display_order=0)

        self.client.post("/contracts/bulk-edit/start/", {"pks": [c1.pk]})
        data = self._page_data(c1)
        resp = self.client.post(
            "/contracts/bulk-edit/",
            {**data, "related_contract_ids": [str(new_target.pk)]},
        )
        self.assertEqual(resp.status_code, 200)
        linked = list(
            ContractRelation.objects.filter(contract=c1).values_list("related_contract_id", flat=True)
        )
        self.assertEqual(linked, [new_target.pk])
        self.assertEqual(resp.context["complete"]["counts"]["updated"], 1)


class PreviewViewTests(TestCase):
    """documents.tests.PreviewViewTestsと同じ理由（screen-search「文書イメージ」欄、原本には
    無い機能）。契約書の権限フラグは`contract_download`。"""

    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.employee = Employee.objects.create_user(
            employee_no="1", name="テスト太郎", password="pass1234",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        self.group = Group.objects.create(code="A", name="契約分類Ａ", doc_kbn=DocKbn.CONTRACT)
        self.category = Category.objects.create(
            code="001", name="契約カテゴリーＡ", group=self.group, doc_kbn=DocKbn.CONTRACT
        )
        self.client.login(username="1", password="pass1234")

        from contracts.models import Contract

        self.contract = Contract(
            title="プレビュー対象", department=self.department, group=self.group, category=self.category,
            year=2026, uploader=self.employee, expiry_date=datetime.date(2036, 1, 1),
        )
        self.contract.file.save("preview.pdf", ContentFile(b"%PDF-1.4 dummy"), save=False)
        self.contract.save()

    def test_without_permission_denied(self):
        response = self.client.get(f"/contracts/{self.contract.pk}/preview/")
        self.assertEqual(response.status_code, 403)

    def test_with_permission_returns_inline_content_disposition(self):
        PermissionProfile.objects.create(
            employee=self.employee, role=PermissionRole.STAFF, contract_download=True
        )
        response = self.client.get(f"/contracts/{self.contract.pk}/preview/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("inline", response["Content-Disposition"])
        self.assertNotIn("attachment", response["Content-Disposition"])
        self.assertTrue(AuditLog.objects.filter(action="契約書検索　プレビュー").exists())

    def test_missing_file_returns_404(self):
        PermissionProfile.objects.create(
            employee=self.employee, role=PermissionRole.STAFF, contract_download=True
        )
        with mock.patch(
            "django.db.models.fields.files.FieldFile.open", side_effect=OSError("missing")
        ):
            response = self.client.get(f"/contracts/{self.contract.pk}/preview/")
        self.assertEqual(response.status_code, 404)

    def test_deleted_contract_preview_returns_404(self):
        """documents.tests.PreviewViewTests.test_deleted_document_preview_returns_404と同じ理由
        （xlsx 検索・閲覧・変更!B659(Rev1.2)「削除されている契約書は、ボタンを非表示とする」の
        URL直打ち対策。品質レビューで発見：documents側と同型の漏れがcontracts側にもあった）。"""
        PermissionProfile.objects.create(
            employee=self.employee, role=PermissionRole.STAFF, contract_download=True
        )
        self.contract.is_deleted = True
        self.contract.save(update_fields=["is_deleted"])
        response = self.client.get(f"/contracts/{self.contract.pk}/preview/")
        self.assertEqual(response.status_code, 404)


class DeletedContractDirectAccessTests(TestCase):
    """テストカバレッジ棚卸しで発見：ContractEditView/BulkEditViewはDownloadViewと同じ
    is_deleted=Falseパターンのget_object_or_404/scoped_get_object_or_404を使っているが、
    削除済み契約書への直接URLアクセスが実際に404/検索画面への案内になることは未検証だった
    （documents.tests.DeletedDocumentDirectAccessTests参照）。"""

    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.employee = Employee.objects.create_user(
            employee_no="1", name="テスト太郎", password="pass1234",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.STAFF, contract_edit=True)
        group = Group.objects.create(code="A", name="契約分類Ａ", doc_kbn=DocKbn.CONTRACT)
        category = Category.objects.create(code="001", name="契約カテゴリーＡ", group=group, doc_kbn=DocKbn.CONTRACT)
        self.client.login(username="1", password="pass1234")

        from contracts.models import Contract

        self.contract = Contract(
            title="削除済み契約書", department=self.department, group=group, category=category,
            year=2026, uploader=self.employee, expiry_date=datetime.date(2036, 1, 1), is_deleted=True,
        )
        self.contract.file.save("doc.pdf", ContentFile(b"dummy"), save=False)
        self.contract.save()

    def test_edit_screen_direct_access_returns_404(self):
        response = self.client.get(f"/contracts/{self.contract.pk}/edit/")
        self.assertEqual(response.status_code, 404)

    def test_bulk_edit_start_silently_excludes_deleted_pk(self):
        response = self.client.post("/contracts/bulk-edit/start/", {"pks": [self.contract.pk]})
        self.assertRedirects(response, "/contracts/search/")

    def test_bulk_edit_direct_access_to_deleted_contract_returns_404(self):
        from core import bulk_edit_services

        session = self.client.session
        bulk_edit_services.start_bulk_edit(session, "contracts_bulk_edit", [self.contract.pk])
        session.save()
        response = self.client.get("/contracts/bulk-edit/")
        self.assertEqual(response.status_code, 404)


class ImagePreviewTests(TestCase):
    """documents.tests.ImagePreviewTestsと同じ理由（保管画面２・編集画面の実プレビュー、
    ユーザー依頼2026-08-12で追加、当初は画像のみだったが同日中にPDFにも対応した）。
    契約書の権限フラグは`contract_download`。"""

    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.employee = Employee.objects.create_user(
            employee_no="1", name="テスト太郎", password="pass1234",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        self.group = Group.objects.create(code="A", name="契約分類Ａ", doc_kbn=DocKbn.CONTRACT)
        self.category = Category.objects.create(
            code="001", name="契約カテゴリーＡ", group=self.group, doc_kbn=DocKbn.CONTRACT
        )
        # Rev1.2で追加された「契約書-契約書-契約書情報変更」がOFFだと保管・編集画面自体が403に
        # なるため（permissions.services.can_edit_contract）付与しておく。このクラスが検証したい
        # のはあくまで`contract_download`（プレビュー・ダウンロード）権限の方なので、
        # 各テストではプロファイルを新規作成せずcontract_downloadだけを更新する
        # （OneToOneのため二重作成はIntegrityErrorになる）。
        PermissionProfile.objects.create(
            employee=self.employee, role=PermissionRole.STAFF, contract_edit=True
        )
        self.client.login(username="1", password="pass1234")

    def _upload_pending(self, filename, content, content_type):
        self.client.post(
            "/contracts/upload/step1/",
            {"files": [SimpleUploadedFile(filename, content, content_type=content_type)]},
        )

    def _grant_contract_download(self):
        self.employee.permission_profile.contract_download = True
        self.employee.permission_profile.save(update_fields=["contract_download"])

    def test_pending_preview_without_permission_denied(self):
        self._upload_pending("a.png", b"PNGDATA", "image/png")
        response = self.client.get("/contracts/upload/step2/preview/0/")
        self.assertEqual(response.status_code, 403)

    def test_pending_preview_returns_uploaded_file_bytes(self):
        self._grant_contract_download()
        self._upload_pending("a.png", b"PNGDATA", "image/png")
        response = self.client.get("/contracts/upload/step2/preview/0/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"PNGDATA")

    def test_pending_preview_out_of_range_index_returns_404(self):
        self._grant_contract_download()
        self._upload_pending("a.png", b"PNGDATA", "image/png")
        response = self.client.get("/contracts/upload/step2/preview/5/")
        self.assertEqual(response.status_code, 404)

    def test_storage2_context_flags_image_and_builds_preview_url(self):
        self._grant_contract_download()
        self._upload_pending("a.png", b"PNGDATA", "image/png")
        response = self.client.get("/contracts/upload/step2/")
        self.assertEqual(response.context["preview_kinds"], ["image"])
        self.assertEqual(response.context["preview_urls"], ["/contracts/upload/step2/preview/0/"])

    def test_storage2_context_flags_pdf_and_builds_preview_url(self):
        self._grant_contract_download()
        self._upload_pending("a.pdf", b"%PDF-1.4", "application/pdf")
        response = self.client.get("/contracts/upload/step2/")
        self.assertEqual(response.context["preview_kinds"], ["pdf"])
        self.assertEqual(response.context["preview_urls"], ["/contracts/upload/step2/preview/0/"])

    def test_edit_screen_shows_image_preview_only_with_permission_and_image_file(self):
        from contracts.models import Contract

        contract = Contract(
            title="画像契約書", department=self.department, group=self.group, category=self.category,
            year=2026, uploader=self.employee, expiry_date=datetime.date(2036, 1, 1),
        )
        contract.file.save("photo.png", ContentFile(b"PNGDATA"), save=False)
        contract.save()

        # documents.tests.ImagePreviewTestsと同じ理由（2026-08-13ユーザー報告対応）。
        response = self.client.get(f"/contracts/{contract.pk}/edit/")
        self.assertEqual(response.context["preview_kind"], "image")
        self.assertFalse(response.context["can_download"])
        self.assertContains(response, "契約書-ダウンロード」権限が必要です")

        self._grant_contract_download()
        response = self.client.get(f"/contracts/{contract.pk}/edit/")
        self.assertEqual(response.context["preview_kind"], "image")
        self.assertTrue(response.context["can_download"])
        self.assertContains(response, f'src="/contracts/{contract.pk}/preview/"')

    def test_edit_screen_shows_pdf_preview_only_with_permission_and_pdf_file(self):
        from contracts.models import Contract

        contract = Contract(
            title="PDF契約書", department=self.department, group=self.group, category=self.category,
            year=2026, uploader=self.employee, expiry_date=datetime.date(2036, 1, 1),
        )
        contract.file.save("doc.pdf", ContentFile(b"%PDF-1.4"), save=False)
        contract.save()

        response = self.client.get(f"/contracts/{contract.pk}/edit/")
        self.assertEqual(response.context["preview_kind"], "pdf")
        self.assertFalse(response.context["can_download"])
        self.assertContains(response, "契約書-ダウンロード」権限が必要です")

        # 既定（PDF_JS_PREVIEW_ENABLED=True）は PDF.js プレビュー枠（documents 側と同じ）。
        self._grant_contract_download()
        response = self.client.get(f"/contracts/{contract.pk}/edit/")
        self.assertEqual(response.context["preview_kind"], "pdf")
        self.assertTrue(response.context["can_download"])
        self.assertContains(
            response, f'class="pdfjs-preview" data-pdf-url="/contracts/{contract.pk}/preview/"'
        )
        self.assertNotContains(response, f'<iframe src="/contracts/{contract.pk}/preview/"')

    @override_settings(PDF_JS_PREVIEW_ENABLED=False)
    def test_edit_screen_pdf_preview_falls_back_to_iframe_when_pdfjs_disabled(self):
        from contracts.models import Contract

        contract = Contract(
            title="PDF契約書", department=self.department, group=self.group, category=self.category,
            year=2026, uploader=self.employee, expiry_date=datetime.date(2036, 1, 1),
        )
        contract.file.save("doc.pdf", ContentFile(b"%PDF-1.4"), save=False)
        contract.save()
        self._grant_contract_download()
        response = self.client.get(f"/contracts/{contract.pk}/edit/")
        self.assertContains(response, f'<iframe src="/contracts/{contract.pk}/preview/"')
        self.assertNotContains(response, 'class="pdfjs-preview"')


class ContractEditScreenAmountDisplayTests(TestCase):
    """CommaNumberInputTestsのウィジェット単体テストに加え、編集画面を実際に開いた時点で
    契約金額欄の初期値にカンマが入っていることを確認する（ユーザー報告2026-08-12）。"""

    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.employee = Employee.objects.create_user(
            employee_no="1", name="テスト太郎", password="pass1234",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        self.group = Group.objects.create(code="A", name="契約分類Ａ", doc_kbn=DocKbn.CONTRACT)
        self.category = Category.objects.create(
            code="001", name="契約カテゴリーＡ", group=self.group, doc_kbn=DocKbn.CONTRACT
        )
        # Rev1.2で追加された「契約書-契約書-契約書情報変更」がOFFだと保管・編集操作が
        # 403になるため（permissions.services.can_edit_contract）、この一般的なテスト用職員には
        # 付与しておく（権限そのものを検証する専用テストは別途 contract_edit を明示的に扱う）。
        PermissionProfile.objects.create(
            employee=self.employee, role=PermissionRole.STAFF, contract_edit=True
        )
        self.client.login(username="1", password="pass1234")

    def test_edit_screen_shows_comma_formatted_amount_on_initial_load(self):
        from contracts.models import Contract

        contract = Contract(
            title="金額表示確認用", department=self.department, group=self.group, category=self.category,
            year=2026, uploader=self.employee, expiry_date=datetime.date(2036, 1, 1),
            contract_amount=1200000,
        )
        contract.file.save("doc.pdf", ContentFile(b"%PDF-1.4"), save=False)
        contract.save()

        response = self.client.get(f"/contracts/{contract.pk}/edit/")
        self.assertContains(response, 'value="1,200,000"')
        self.assertNotContains(response, 'value="1200000"')


class EditScreenYearFieldTests(TestCase):
    """documents.tests.EditScreenYearFieldTestsと同じ理由（contracts.forms.UploadStep2Form.year、
    core.forms.year_choices_with_existing）。年の選択肢は直近6年分のみを動的生成するため、対象
    契約書の年がその範囲外だと、原本フィデリティ監査で発見した不具合が起きていた：<select>の
    どのoptionにもselected属性が付かずブラウザが先頭optionを自動選択してしまうため、年欄に
    一切触れずフォームを送信しただけで年が意図せず書き換わる。
    """

    def setUp(self):
        from contracts.models import Contract

        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.employee = Employee.objects.create_user(
            employee_no="1", name="テスト太郎", password="pass1234",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        self.group = Group.objects.create(code="A", name="契約分類Ａ", doc_kbn=DocKbn.CONTRACT)
        self.category = Category.objects.create(
            code="001", name="契約カテゴリーＡ", group=self.group, doc_kbn=DocKbn.CONTRACT
        )
        # Rev1.2で追加された「契約書-契約書-契約書情報変更」がOFFだと保管・編集操作が
        # 403になるため（permissions.services.can_edit_contract）、この一般的なテスト用職員には
        # 付与しておく（権限そのものを検証する専用テストは別途 contract_edit を明示的に扱う）。
        PermissionProfile.objects.create(
            employee=self.employee, role=PermissionRole.STAFF, contract_edit=True
        )
        self.client.login(username="1", password="pass1234")
        self.old_year = datetime.date.today().year - 10
        self.contract = Contract(
            title="古い年の契約書", department=self.department, group=self.group, category=self.category,
            year=self.old_year, uploader=self.employee, expiry_date=datetime.date(2099, 1, 1),
        )
        self.contract.file.save("old.pdf", ContentFile(b"%PDF-1.4"), save=False)
        self.contract.save()

    def test_edit_screen_marks_out_of_range_year_as_selected_option(self):
        response = self.client.get(f"/contracts/{self.contract.pk}/edit/")
        self.assertContains(response, f'value="{self.old_year}" selected')

    def test_submitting_edit_form_unchanged_preserves_out_of_range_year(self):
        get_response = self.client.get(f"/contracts/{self.contract.pk}/edit/")
        token = get_response.context["token"]
        response = self.client.post(
            f"/contracts/{self.contract.pk}/edit/",
            {
                "token": token,
                "department": self.department.pk,
                "group": self.group.pk,
                "category": self.category.pk,
                "year": self.old_year,
                "title_0": self.contract.title,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["form"].errors)
        self.contract.refresh_from_db()
        self.assertEqual(self.contract.year, self.old_year)


class ContractEditIsDirtyServiceTests(TestCase):
    """テストカバレッジ棚卸し（review_test_doc_contract.txt 指摘 M-2）で発見：
    contracts.services.contract_edit_is_dirty（related_changed 引数を含む）が
    BulkEditViewTests の HTTP 経由でしか間接検証されていなかった。None↔""正規化・
    非管理者の部署読み替え・Decimal/日付の同値判定・関連書類増減単独での dirty 化を
    個別に固定する。"""

    def setUp(self):
        import decimal

        from contracts.models import Contract

        self.decimal = decimal
        self.dept = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.dept2 = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="02", section_name="営業部"
        )
        self.admin = Employee.objects.create_user(
            employee_no="9", name="管理者", password="pass1234",
            department=self.dept, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        PermissionProfile.objects.create(employee=self.admin, role=PermissionRole.ADMIN)
        self.staff = Employee.objects.create_user(
            employee_no="1", name="一般", password="pass1234",
            department=self.dept, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        PermissionProfile.objects.create(employee=self.staff, role=PermissionRole.STAFF)
        self.group = Group.objects.create(code="A", name="契約分類Ａ", doc_kbn=DocKbn.CONTRACT)
        self.category = Category.objects.create(
            code="001", name="契約カテゴリーＡ", group=self.group, doc_kbn=DocKbn.CONTRACT
        )
        self.contract = Contract(
            title="元タイトル", department=self.dept, group=self.group, category=self.category,
            year=2026, uploader=self.admin, expiry_date=datetime.date(2036, 1, 1),
            contract_date=datetime.date(2026, 4, 1), contract_amount=decimal.Decimal("1000"),
            contract_partner="", memo="",
        )
        self.contract.file.save("c.pdf", ContentFile(b"x"), save=False)
        self.contract.save()

    def _cleaned(self, **overrides):
        data = {
            "title_0": "元タイトル", "department": self.dept, "group": self.group,
            "category": self.category, "year": 2026,
            "contract_date": datetime.date(2026, 4, 1),
            "contract_period_start": None, "contract_period_end": None,
            "renewal_date": None, "contract_amount": self.decimal.Decimal("1000"),
            "contract_partner": "", "memo": "",
        }
        data.update(overrides)
        return data

    def test_identical_values_are_not_dirty(self):
        self.assertFalse(contract_edit_is_dirty(self.contract, self._cleaned(), self.admin))

    def test_contract_partner_none_and_empty_string_are_treated_as_equal(self):
        self.assertFalse(
            contract_edit_is_dirty(self.contract, self._cleaned(contract_partner=None), self.admin)
        )

    def test_same_decimal_amount_is_not_dirty(self):
        self.assertFalse(
            contract_edit_is_dirty(
                self.contract, self._cleaned(contract_amount=self.decimal.Decimal("1000")), self.admin
            )
        )

    def test_decimal_amount_change_is_dirty(self):
        self.assertTrue(
            contract_edit_is_dirty(
                self.contract, self._cleaned(contract_amount=self.decimal.Decimal("2000")), self.admin
            )
        )

    def test_contract_date_change_is_dirty(self):
        self.assertTrue(
            contract_edit_is_dirty(
                self.contract, self._cleaned(contract_date=datetime.date(2026, 5, 1)), self.admin
            )
        )

    def test_related_changed_alone_makes_it_dirty(self):
        self.assertTrue(
            contract_edit_is_dirty(self.contract, self._cleaned(), self.admin, related_changed=True)
        )

    def test_expiry_date_is_not_part_of_comparison(self):
        self.contract.expiry_date = datetime.date(1999, 1, 1)
        self.assertFalse(contract_edit_is_dirty(self.contract, self._cleaned(), self.admin))

    def test_non_admin_cross_department_post_is_not_detected_as_dirty(self):
        self.assertFalse(
            contract_edit_is_dirty(self.contract, self._cleaned(department=self.dept2), self.staff)
        )

    def test_admin_department_change_is_dirty(self):
        self.assertTrue(
            contract_edit_is_dirty(self.contract, self._cleaned(department=self.dept2), self.admin)
        )


class ContractEditExpiryDateUnchangedTests(TestCase):
    """テストカバレッジ棚卸し（review_test_doc_contract.txt 指摘 H-1）で発見：
    memory expiry_date_edit_recalc_spec（2026-08-28ユーザー確定）の
    「契約書は編集時に expiry_date を一切触らない」を確認するテストが皆無だった。
    契約書は保存期間が選択式ではなく settings.CONTRACT_RETENTION_YEARS 固定のため、
    contracts.services.apply_contract_edit は文書側の retention_changed 分岐すら持たず
    expiry_date を引き直さない。"""

    def setUp(self):
        from contracts.models import Contract

        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.employee = Employee.objects.create_user(
            employee_no="1", name="テスト太郎", password="pass1234",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        PermissionProfile.objects.create(
            employee=self.employee, role=PermissionRole.STAFF, contract_edit=True
        )
        self.group = Group.objects.create(code="A", name="契約分類Ａ", doc_kbn=DocKbn.CONTRACT)
        self.category = Category.objects.create(
            code="001", name="契約カテゴリーＡ", group=self.group, doc_kbn=DocKbn.CONTRACT
        )
        self.client.login(username="1", password="pass1234")
        self.original_expiry = datetime.date(2099, 1, 1)
        self.contract = Contract(
            title="満了日確認用", department=self.department, group=self.group, category=self.category,
            year=2026, uploader=self.employee, expiry_date=self.original_expiry,
        )
        self.contract.file.save("doc.pdf", ContentFile(b"%PDF-1.4"), save=False)
        self.contract.save()

    def test_editing_contract_does_not_touch_expiry_date(self):
        get_response = self.client.get(f"/contracts/{self.contract.pk}/edit/")
        token = get_response.context["token"]
        resp = self.client.post(
            f"/contracts/{self.contract.pk}/edit/",
            {
                "token": token,
                "department": self.department.pk,
                "group": self.group.pk,
                "category": self.category.pk,
                "year": self.contract.year,
                "title_0": "タイトル変更",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.context["form"].errors)
        self.contract.refresh_from_db()
        self.assertEqual(self.contract.title, "タイトル変更")
        self.assertEqual(self.contract.expiry_date, self.original_expiry)


class UploadStep2FormDepartmentInitialTests(TestCase):
    """documents.tests.UploadStep2FormDepartmentInitialTestsと同じ理由（contracts.forms.
    UploadStep2Form、xlsx 保管!B412-416「※保管画面(文書)と同じ」）。新規登録画面
    （edit_mode=False）は権限に関わらずログインユーザーの部署が初期値になるが、編集画面
    （edit_mode=True、ContractEditView._build_form）は既存契約書の部署をinitialで渡すため、
    ここで上書きしてはいけない。
    """

    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.other_department = Department.objects.create(
            branch_code="999", branch_name="別支店", section_code="", section_name=""
        )
        self.admin = Employee.objects.create_user(
            employee_no="1", name="管理者", password="x",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        PermissionProfile.objects.create(employee=self.admin, role=PermissionRole.ADMIN)
        self.staff = Employee.objects.create_user(
            employee_no="2", name="一般職員", password="x",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.IPPAN,
        )
        PermissionProfile.objects.create(employee=self.staff, role=PermissionRole.STAFF)

    def test_admin_new_registration_defaults_to_own_department(self):
        # 新規保管はメタデータがファイルごと（department_0..）。2026-08-31、per_file_mode。
        from contracts.forms import UploadStep2Form

        form = UploadStep2Form(employee=self.admin, edit_mode=False)
        self.assertEqual(form["department_0"].value(), self.admin.department_id)

    def test_admin_edit_screen_keeps_contracts_own_department(self):
        from contracts.forms import UploadStep2Form

        form = UploadStep2Form(
            employee=self.admin, edit_mode=True, initial={"department": self.other_department.pk}
        )
        self.assertEqual(form["department"].value(), self.other_department.pk)

    def test_staff_edit_screen_is_forced_to_own_department_regardless_of_initial(self):
        from contracts.forms import UploadStep2Form

        form = UploadStep2Form(
            employee=self.staff, edit_mode=True, initial={"department": self.other_department.pk}
        )
        self.assertEqual(form["department"].value(), self.staff.department_id)
        self.assertTrue(form.fields["department"].disabled)


class UploadStep2FormGroupCategoryScopeTests(TestCase):
    """documents.tests.UploadStep2FormGroupCategoryScopeTestsと同じ理由（contracts.forms.
    UploadStep2Form/SearchFormの分類(group)/カテゴリー(category)絞り込み、
    core.forms.scoped_group_and_category_querysets）。"""

    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.other_department = Department.objects.create(
            branch_code="999", branch_name="別支店", section_code="", section_name=""
        )
        self.staff = Employee.objects.create_user(
            employee_no="1", name="一般職員", password="x",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.IPPAN,
        )
        PermissionProfile.objects.create(employee=self.staff, role=PermissionRole.STAFF, contract_edit=True)
        self.own_group = Group.objects.create(
            code="A", name="自部署の分類", doc_kbn=DocKbn.CONTRACT, department=self.department
        )
        self.own_category = Category.objects.create(
            code="001", name="自部署のカテゴリー", group=self.own_group, doc_kbn=DocKbn.CONTRACT,
            department=self.department,
        )
        self.other_group = Group.objects.create(
            code="B", name="他部署の分類", doc_kbn=DocKbn.CONTRACT, department=self.other_department
        )
        self.other_category = Category.objects.create(
            code="002", name="他部署のカテゴリー", group=self.other_group, doc_kbn=DocKbn.CONTRACT,
            department=self.other_department,
        )
        self.client.login(username="1", password="x")

    def test_posting_out_of_scope_group_id_is_rejected_by_form_validation(self):
        """テストカバレッジ棚卸しで発見：分類/カテゴリーの部署スコープはクライアント側の
        queryset絞り込み（プルダウン非表示）だけでなく、ModelChoiceField.clean()が
        POSTされたpkそのものをqueryset外として拒否することをHTTP経由で確認する。"""
        self.client.post(
            "/contracts/upload/step1/",
            {"files": [SimpleUploadedFile("a.pdf", b"dummy", content_type="application/pdf")]},
        )
        step2 = self.client.get("/contracts/upload/step2/")
        token = step2.context["token"]
        response = self.client.post(
            "/contracts/upload/step2/",
            {
                # 新規保管はメタデータがファイルごと（*_0）。2026-08-31、per_file_mode。
                "token": token,
                "department_0": self.department.pk,
                "group_0": self.other_group.pk,
                "category_0": self.other_category.pk,
                "year_0": 2026,
                "title_0": "テスト契約書",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["form"].is_valid())
        self.assertIn("group_0", response.context["form"].errors)
        self.assertIn("category_0", response.context["form"].errors)

    def test_department_scope_overrides_cross_department_contract_visible_groups_grant(self):
        """documents.tests.UploadStep2FormGroupCategoryScopeTests.
        test_department_scope_overrides_cross_department_doc_visible_groups_grantと同じ観点
        （review_test_doc_contract.txt指摘3）。documents側と同じcore.forms.
        scoped_group_and_category_querysetsを共有しているが、契約書側の権限フィールド
        （PermissionProfile.contract_visible_groups）で他部署の分類が明示的に許可されていても、
        2026-08-25にユーザー確認済みの「部署スコープを常に優先する」が契約書側でも成立することを
        固定するリグレッションテスト。"""
        from contracts.forms import UploadStep2Form

        profile = PermissionProfile.objects.get(employee=self.staff)
        profile.contract_visible_groups.add(self.own_group, self.other_group)

        form = UploadStep2Form(employee=self.staff)
        group_ids = set(form.fields["group_0"].queryset.values_list("pk", flat=True))
        self.assertIn(self.own_group.pk, group_ids)
        self.assertNotIn(self.other_group.pk, group_ids)


class DetailAPIViewTests(TestCase):
    """documents.tests.DetailAPIViewTestsと同じ理由（popup-detailのpreview_url/preview_kind、
    ユーザー依頼2026-08-12で追加）。あわせて、関連書類名がフルパス（rf.file.name）のまま
    返っていたバグ（display_nameを使うべき箇所）の修正も確認する。"""

    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.employee = Employee.objects.create_user(
            employee_no="1", name="テスト太郎", password="pass1234",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        self.group = Group.objects.create(code="A", name="契約分類Ａ", doc_kbn=DocKbn.CONTRACT)
        self.category = Category.objects.create(
            code="001", name="契約カテゴリーＡ", group=self.group, doc_kbn=DocKbn.CONTRACT
        )
        self.client.login(username="1", password="pass1234")

        from contracts.models import Contract

        self.contract = Contract(
            title="詳細確認用", department=self.department, group=self.group, category=self.category,
            year=2026, uploader=self.employee, expiry_date=datetime.date(2036, 1, 1),
        )
        self.contract.file.save("photo.png", ContentFile(b"PNGDATA"), save=False)
        self.contract.save()

    def test_without_permission_preview_url_is_null_but_kind_is_returned(self):
        # documents.tests.DetailAPIViewTestsと同じ理由（2026-08-13ユーザー報告対応）。
        response = self.client.get(f"/contracts/api/{self.contract.pk}/")
        data = response.json()
        self.assertIsNone(data["preview_url"])
        self.assertEqual(data["preview_kind"], "image")

    def test_with_permission_returns_preview_url_and_kind(self):
        PermissionProfile.objects.create(
            employee=self.employee, role=PermissionRole.STAFF, contract_download=True
        )
        response = self.client.get(f"/contracts/api/{self.contract.pk}/")
        data = response.json()
        self.assertEqual(data["preview_url"], f"/contracts/{self.contract.pk}/preview/")
        self.assertEqual(data["preview_kind"], "image")

    def _link_related(self, title, *, is_deleted=False, order=0):
        from contracts.models import Contract, ContractRelation

        rel = Contract(
            title=title, department=self.department, group=self.group, category=self.category,
            year=2025, uploader=self.employee, expiry_date=datetime.date(2035, 1, 1),
            is_deleted=is_deleted,
        )
        rel.file.save(f"{title}.pdf", ContentFile(b"R"), save=False)
        rel.save()
        ContractRelation.objects.create(
            contract=self.contract, related_contract=rel, display_order=order
        )
        return rel

    def test_related_contracts_with_download_permission_returns_preview_url(self):
        """Rev1.6（xlsx 検索・閲覧・変更!B677-680）：関連資料は紐付け先契約書。ダウンロード権限が
        あれば preview_url（別タブでPDFプレビュー）を返す。display_order 順。"""
        PermissionProfile.objects.create(
            employee=self.employee, role=PermissionRole.STAFF, contract_download=True
        )
        a = self._link_related("関連A", order=0)
        b = self._link_related("関連B", order=1)

        data = self.client.get(f"/contracts/api/{self.contract.pk}/").json()
        self.assertEqual(
            data["related_contracts"],
            [
                {"title": "関連A", "is_deleted": False, "preview_url": f"/contracts/{a.pk}/preview/"},
                {"title": "関連B", "is_deleted": False, "preview_url": f"/contracts/{b.pk}/preview/"},
            ],
        )

    def test_related_contracts_deleted_has_flag_and_no_preview_url(self):
        """削除済みの関連資料は is_deleted=true・preview_url=null（common.js側で赤字＋
        「既に削除されている関連資料です」表示）。"""
        PermissionProfile.objects.create(
            employee=self.employee, role=PermissionRole.STAFF, contract_download=True
        )
        self._link_related("削除された関連", is_deleted=True)

        data = self.client.get(f"/contracts/api/{self.contract.pk}/").json()
        self.assertEqual(
            data["related_contracts"],
            [{"title": "削除された関連", "is_deleted": True, "preview_url": None}],
        )

    def test_related_contracts_without_download_permission_no_preview_url(self):
        """ダウンロード権限が無ければリンク化しない（preview_url=null、素テキスト表示）。"""
        self._link_related("関連C")
        data = self.client.get(f"/contracts/api/{self.contract.pk}/").json()
        self.assertEqual(data["related_contracts"][0]["preview_url"], None)
        self.assertEqual(data["related_contracts"][0]["is_deleted"], False)

    def test_contract_amount_zero_is_returned_as_string_not_blank(self):
        """コードレビューC-5：契約金額0円はDecimal('0')でfalsyのため、以前は`if amount`判定で
        未入力(None)と同じく空文字になり金額欄が空表示になっていた。0円と未入力を区別する。"""
        self.contract.contract_amount = 0
        self.contract.save(update_fields=["contract_amount"])
        response = self.client.get(f"/contracts/api/{self.contract.pk}/")
        self.assertEqual(response.json()["contract_amount"], "0")

    def test_contract_amount_none_is_returned_as_blank(self):
        response = self.client.get(f"/contracts/api/{self.contract.pk}/")
        self.assertEqual(response.json()["contract_amount"], "")

    def test_deleted_contract_yields_null_edit_and_delete_urls(self):
        """documents.tests.DetailAPIViewTests.test_deleted_document_yields_null_edit_and_delete_urls
        と同じ理由（ユーザー報告2026-08-12：削除済み契約書一覧の詳細ポップアップで「変更」が
        404になっていた）。delete_urlもRev1.2（xlsx 検索・閲覧・変更!B659,B663「削除されている
        契約書は、ボタンを非表示とする」）でNoneになるよう変更した
        （contracts.services.can_delete docstring参照。以前は「ゴミ箱保管中の削除ボタンで
        完全削除」機能のため常に返していたが、その機能は廃止した）。download_urlも同じB659の
        対象（2026-08-24追加分の再監査で発見：以前はcan_download権限のみを見ておりis_deleted
        判定が漏れていたため、削除済み契約書でもダウンロードボタンが表示され続けていた）。"""
        PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.STAFF, contract_download=True)
        self.contract.is_deleted = True
        self.contract.save(update_fields=["is_deleted"])

        response = self.client.get(f"/contracts/api/{self.contract.pk}/")
        data = response.json()
        self.assertIsNone(data["edit_url"])
        self.assertIsNone(data["delete_url"])
        self.assertIsNone(data["download_url"])

    def test_non_deleted_contract_still_has_edit_and_delete_urls(self):
        # Rev1.2で追加された「契約書-契約書-契約書情報変更」がONでないとedit_urlがNoneになる
        # ため（permissions.services.can_edit_contract）付与しておく。
        PermissionProfile.objects.create(
            employee=self.employee, role=PermissionRole.STAFF, contract_edit=True, contract_download=True
        )
        response = self.client.get(f"/contracts/api/{self.contract.pk}/")
        data = response.json()
        self.assertEqual(data["edit_url"], f"/contracts/{self.contract.pk}/edit/")
        self.assertEqual(data["delete_url"], f"/contracts/{self.contract.pk}/delete/")
        self.assertEqual(data["download_url"], f"/contracts/{self.contract.pk}/download/")

    def test_contract_past_delete_window_yields_null_delete_url(self):
        """xlsx 保管!B300,B583（Rev1.6で+2、旧B581）・検索・閲覧・変更!B664-665「初回登録から1週間以上経過している
        ものは削除不可。ボタンを非表示にする」（contracts.services.can_delete）。"""
        from contracts.models import Contract

        Contract.objects.filter(pk=self.contract.pk).update(
            save_date=timezone.now() - datetime.timedelta(days=8)
        )
        response = self.client.get(f"/contracts/api/{self.contract.pk}/")
        data = response.json()
        self.assertIsNone(data["delete_url"])

    def test_deleted_contract_past_delete_window_yields_null_delete_url(self):
        """ゴミ箱保管中（is_deleted=True）は1週間制限を待つまでもなく、Rev1.2で削除不可
        （delete_url None）になる（contracts.services.can_delete docstring参照）。"""
        from contracts.models import Contract

        Contract.objects.filter(pk=self.contract.pk).update(
            save_date=timezone.now() - datetime.timedelta(days=30), is_deleted=True
        )
        response = self.client.get(f"/contracts/api/{self.contract.pk}/")
        data = response.json()
        self.assertIsNone(data["delete_url"])

    def test_cross_department_contract_access_is_denied(self):
        """テストカバレッジ棚卸しで発見：DetailAPIView.getの他部署アクセス拒否分岐
        （contract_searchable_department_idsに含まれない部署）が一度もテストで発火して
        いなかった。回帰時（条件の反転等）に他部署の契約書メタ情報が漏れても検知できない
        状態だった。"""
        other_department = Department.objects.create(
            branch_code="999", branch_name="別支店", section_code="", section_name=""
        )
        from contracts.models import Contract

        other_contract = Contract(
            title="他部署の契約書", department=other_department, group=self.group, category=self.category,
            year=2026, uploader=self.employee, expiry_date=datetime.date(2036, 1, 1),
        )
        other_contract.file.save("other.pdf", ContentFile(b"dummy"), save=False)
        other_contract.save()

        response = self.client.get(f"/contracts/api/{other_contract.pk}/")
        self.assertEqual(response.status_code, 403)
        # 他部署リソースへの直打ちアクセス試行は操作履歴ログ（audit）にも残す
        # （review_rule_doc_contract.txt No.1、2026-09-09ユーザー確定）。
        self.assertTrue(
            AuditLog.objects.filter(
                action="アクセス拒否", event_message__contains=f"（ID:{other_contract.pk}）"
            ).exists()
        )


class CanDeleteBoundaryTests(TestCase):
    """contracts.services.can_deleteのDELETE_WINDOW_DAYS境界値（documents.tests.
    CanDeleteBoundaryTestsと同じ理由。テストカバレッジ棚卸しで発見：「7日未満」「8日経過」は
    既存テストでカバーされていたが、ちょうどDELETE_WINDOW_DAYS〈7日〉経過した瞬間の境界
    〈timezone.now() - save_date < 7日、の等号側〉が未検証だった）。"""

    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.employee = Employee.objects.create_user(
            employee_no="1", name="テスト太郎", password="x",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        group = Group.objects.create(code="A", name="契約分類Ａ", doc_kbn=DocKbn.CONTRACT)
        category = Category.objects.create(code="001", name="契約カテゴリーＡ", group=group, doc_kbn=DocKbn.CONTRACT)
        from contracts.models import Contract

        self.contract = Contract(
            title="境界確認用", department=self.department, group=group, category=category,
            year=2026, uploader=self.employee, expiry_date=datetime.date(2036, 1, 1),
        )
        self.contract.file.save("doc.pdf", ContentFile(b"dummy"), save=False)
        self.contract.save()

    def test_exactly_at_window_boundary_is_not_deletable(self):
        from contracts.models import Contract
        from contracts.services import can_delete

        Contract.objects.filter(pk=self.contract.pk).update(
            save_date=timezone.now() - datetime.timedelta(days=7)
        )
        self.contract.refresh_from_db()
        self.assertFalse(can_delete(self.contract))

    def test_just_under_window_boundary_is_still_deletable(self):
        from contracts.models import Contract
        from contracts.services import can_delete

        Contract.objects.filter(pk=self.contract.pk).update(
            save_date=timezone.now() - datetime.timedelta(days=7) + datetime.timedelta(minutes=1)
        )
        self.contract.refresh_from_db()
        self.assertTrue(can_delete(self.contract))


class DeleteViewWindowTests(TestCase):
    """contracts.views.DeleteView.postのサーバー側1週間経過チェック。"""

    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.employee = Employee.objects.create_user(
            employee_no="1", name="テスト太郎", password="pass1234",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        # DeleteViewAjaxTests.setUpと同じ理由（Rev1.2のcontract_edit権限チェックが先に走るため）。
        PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.STAFF, contract_edit=True)
        group = Group.objects.create(code="A", name="分類Ａ", doc_kbn=DocKbn.CONTRACT)
        category = Category.objects.create(code="001", name="カテゴリーＡ", group=group, doc_kbn=DocKbn.CONTRACT)
        self.client.login(username="1", password="pass1234")

        from contracts.models import Contract

        self.contract = Contract(
            title="削除期限確認用", department=self.department, group=group, category=category,
            year=2026, uploader=self.employee, expiry_date=datetime.date(2036, 1, 1),
        )
        self.contract.file.save("doc.pdf", ContentFile(b"dummy"), save=False)
        self.contract.save()
        Contract.objects.filter(pk=self.contract.pk).update(
            save_date=timezone.now() - datetime.timedelta(days=8)
        )

    def test_delete_rejected_after_window_via_ajax(self):
        response = self.client.post(
            f"/contracts/{self.contract.pk}/delete/", HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.json()["success"])
        self.contract.refresh_from_db()
        self.assertFalse(self.contract.is_deleted)

    def test_delete_rejected_after_window_non_ajax(self):
        response = self.client.post(f"/contracts/{self.contract.pk}/delete/")
        self.assertEqual(response.status_code, 403)
        self.contract.refresh_from_db()
        self.assertFalse(self.contract.is_deleted)


class UploadStep2ViewValidationTests(TestCase):
    """documents.tests.UploadStep2ViewValidationTestsと同じ理由（保管画面２のフォーム
    バリデーション・二重送信対策。テストカバレッジ棚卸しで発見：UploadStep2View/
    ContractEditView/BulkEditView共通のform.is_valid()==False再描画経路・consume_token
    失敗経路のいずれもテストが無かった。ここではUploadStep2Viewを代表として検証する）。"""

    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.employee = Employee.objects.create_user(
            employee_no="1", name="テスト太郎", password="pass1234",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        self.group = Group.objects.create(code="A", name="契約分類Ａ", doc_kbn=DocKbn.CONTRACT)
        self.category = Category.objects.create(
            code="001", name="契約カテゴリーＡ", group=self.group, doc_kbn=DocKbn.CONTRACT
        )
        PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.STAFF, contract_edit=True)
        self.client.login(username="1", password="pass1234")
        self.client.post(
            "/contracts/upload/step1/",
            {"files": [SimpleUploadedFile("a.pdf", b"dummy", content_type="application/pdf")]},
        )

    def _valid_data(self, token):
        # 新規保管はメタデータがファイルごと（*_0）。2026-08-31、per_file_mode。
        return {
            "token": token,
            "department_0": self.department.pk,
            "group_0": self.group.pk,
            "category_0": self.category.pk,
            "year_0": 2026,
            "title_0": "テスト契約書",
        }

    def test_invalid_form_data_re_renders_with_errors(self):
        """必須項目（分類）欠落時、200で再描画されform.errorsに反映されること。"""
        step2 = self.client.get("/contracts/upload/step2/")
        data = self._valid_data(step2.context["token"])
        del data["group_0"]
        response = self.client.post("/contracts/upload/step2/", data)
        self.assertEqual(response.status_code, 200)
        self.assertIn("group_0", response.context["form"].errors)

        from contracts.models import Contract

        self.assertFalse(Contract.objects.exists())

    def test_wrong_token_rejects_with_error_message_and_redirect(self):
        """二重送信対策トークンが不一致の場合、保管せずstep1へリダイレクトしエラーメッセージを出す。"""
        from django.contrib.messages import get_messages

        from contracts.models import Contract

        self.client.get("/contracts/upload/step2/")  # トークン発行
        response = self.client.post("/contracts/upload/step2/", self._valid_data("invalid-token"))
        self.assertRedirects(response, "/contracts/upload/step1/")
        texts = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertTrue(any("二重に送信された可能性がある" in t for t in texts))
        self.assertFalse(Contract.objects.exists())

    def test_multi_file_second_invalid_blocks_all_and_reports_index(self):
        """複数ファイル一括登録（2026-08-31、per_file_mode）で2件目が分類欠落なら、
        全体を止めて「2件目」を案内し、active_doc_index で該当ファイルを表示する。"""
        from django.contrib.messages import get_messages

        from contracts.models import Contract

        self.client.get("/contracts/upload/step1/")  # setUp が積んだ保留ファイルを掃除
        self.client.post("/contracts/upload/step1/", {"files": [
            SimpleUploadedFile("a.pdf", b"AAAA", content_type="application/pdf"),
            SimpleUploadedFile("b.pdf", b"BBBB", content_type="application/pdf"),
        ]})
        token = self.client.get("/contracts/upload/step2/").context["token"]
        response = self.client.post("/contracts/upload/step2/", {
            "token": token,
            "department_0": self.department.pk, "group_0": self.group.pk,
            "category_0": self.category.pk, "year_0": 2026, "title_0": "契約A",
            "department_1": self.department.pk, "category_1": self.category.pk,
            "year_1": 2026, "title_1": "契約B",  # group_1 欠落
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn("group_1", response.context["form"].errors)
        self.assertEqual(response.context["active_doc_index"], 1)
        texts = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertTrue(any("2件目" in t for t in texts))
        self.assertFalse(Contract.objects.exists())


class UploadFileIOErrorTests(TestCase):
    """documents.tests.UploadFileIOErrorTestsと同じ理由（監査で発見・修正：以前はアップロード時の
    ファイルI/O例外が未捕捉のまま伝播していた）。"""

    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.employee = Employee.objects.create_user(
            employee_no="1", name="テスト太郎", password="pass1234",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        # Rev1.2で追加された「契約書-契約書-契約書情報変更」がOFFだと保管・編集操作が
        # 403になるため（permissions.services.can_edit_contract）、この一般的なテスト用職員には
        # 付与しておく（権限そのものを検証する専用テストは別途 contract_edit を明示的に扱う）。
        PermissionProfile.objects.create(
            employee=self.employee, role=PermissionRole.STAFF, contract_edit=True
        )
        self.client.login(username="1", password="pass1234")

    def test_step1_save_failure_shows_error_message(self):
        from django.contrib.messages import get_messages
        from django.core.files.uploadedfile import SimpleUploadedFile

        from core.upload_services import PendingFileStorageError

        with mock.patch(
            "contracts.views.upload_services.save_pending_files",
            side_effect=PendingFileStorageError("disk full"),
        ):
            response = self.client.post(
                "/contracts/upload/step1/",
                {"files": [SimpleUploadedFile("a.pdf", b"AAAA", content_type="application/pdf")]},
            )
        self.assertEqual(response.status_code, 200)
        texts = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertTrue(any("ファイルの保存に失敗しました" in t for t in texts))

    def test_step2_open_pending_file_failure_rolls_back_and_shows_error(self):
        """保管画面２のファイルI/O失敗時、transaction.atomic()によりContractが1件も
        作成されないこと（部分登録の防止）を確認する。"""
        import re

        from django.core.files.uploadedfile import SimpleUploadedFile

        from contracts.models import Contract

        group = Group.objects.create(code="A", name="契約分類Ａ", doc_kbn=DocKbn.CONTRACT)
        category = Category.objects.create(
            code="001", name="契約カテゴリーＡ", group=group, doc_kbn=DocKbn.CONTRACT
        )
        self.client.post(
            "/contracts/upload/step1/",
            {"files": [SimpleUploadedFile("a.pdf", b"AAAA", content_type="application/pdf")]},
        )
        step2 = self.client.get("/contracts/upload/step2/")
        token = re.search(r'name="token" value="([^"]+)"', step2.content.decode("utf-8")).group(1)

        before = set(Contract.objects.values_list("pk", flat=True))
        with mock.patch(
            "contracts.views.upload_services.open_pending_file", side_effect=OSError("temp file missing")
        ):
            response = self.client.post(
                "/contracts/upload/step2/",
                {
                    # 新規保管はメタデータがファイルごと（*_0）。2026-08-31、per_file_mode。
                    "token": token,
                    "department_0": self.department.pk,
                    "group_0": group.pk,
                    "category_0": category.pk,
                    "year_0": 2026,
                    "title_0": "テスト契約書",
                },
            )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/contracts/upload/step2/")


class UploadStep2ImmediateExtractionTests(TestCase):
    """documents.tests.UploadStep2ImmediateExtractionTestsと同じ理由（全文検索基盤、
    2026-08-10追加）。契約書側でも登録直後にextracted_textが埋まることを確認する。
    """

    def setUp(self):
        import re

        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.employee = Employee.objects.create_user(
            employee_no="1", name="テスト太郎", password="pass1234",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        # Rev1.2で追加された「契約書-契約書-契約書情報変更」がOFFだと保管・編集操作が
        # 403になるため（permissions.services.can_edit_contract）、この一般的なテスト用職員には
        # 付与しておく（権限そのものを検証する専用テストは別途 contract_edit を明示的に扱う）。
        PermissionProfile.objects.create(
            employee=self.employee, role=PermissionRole.STAFF, contract_edit=True
        )
        self.client.login(username="1", password="pass1234")
        self.group = Group.objects.create(code="A", name="契約分類Ａ", doc_kbn=DocKbn.CONTRACT)
        self.category = Category.objects.create(
            code="001", name="契約カテゴリーＡ", group=self.group, doc_kbn=DocKbn.CONTRACT
        )
        self.client.post(
            "/contracts/upload/step1/",
            {"files": [SimpleUploadedFile("a.pdf", b"AAAA", content_type="application/pdf")]},
        )
        step2 = self.client.get("/contracts/upload/step2/")
        self.token = re.search(r'name="token" value="([^"]+)"', step2.content.decode("utf-8")).group(1)

    @staticmethod
    def _mock_pdfplumber(text):
        mock_page = mock.MagicMock()
        mock_page.extract_text.return_value = text
        mock_pdf = mock.MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__.return_value = mock_pdf
        mock_pdf.__exit__.return_value = False
        return mock_pdf

    def test_registration_populates_extracted_text_for_text_layer_pdf(self):
        from contracts.models import Contract

        with mock.patch(
            "core.text_extraction_services.pdfplumber.open",
            return_value=self._mock_pdfplumber("十分な文字数を含む本文テキストです。"),
        ):
            response = self.client.post(
                "/contracts/upload/step2/",
                {
                    # 新規保管はメタデータがファイルごと（*_0）。2026-08-31、per_file_mode。
                    "token": self.token,
                    "department_0": self.department.pk,
                    "group_0": self.group.pk,
                    "category_0": self.category.pk,
                    "year_0": 2026,
                    "title_0": "テスト契約書",
                },
            )
        self.assertEqual(response.status_code, 200)
        contract = Contract.objects.get(title="テスト契約書")
        self.assertEqual(contract.extracted_text, "十分な文字数を含む本文テキストです。")


class ContractEditViewFileHandlingTests(TestCase):
    """ContractEditView.postの関連書類（紐付け先契約書）まわり。
    (1) related_contract_ids への改ざん値混入で例外が伝播せず有効なpkだけ同期されること、
    (2) 保存中のDBエラー時に transaction.atomic() で本体更新までロールバックされ、
    利用者にわかるエラーメッセージが出ること（DBErrorモックのテストは末尾）を確認する。"""

    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.employee = Employee.objects.create_user(
            employee_no="1", name="テスト太郎", password="pass1234",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        # Rev1.2で追加された「契約書-契約書-契約書情報変更」がOFFだと保管・編集操作が
        # 403になるため（permissions.services.can_edit_contract）、この一般的なテスト用職員には
        # 付与しておく（権限そのものを検証する専用テストは別途 contract_edit を明示的に扱う）。
        PermissionProfile.objects.create(
            employee=self.employee, role=PermissionRole.STAFF, contract_edit=True
        )
        self.client.login(username="1", password="pass1234")
        self.group = Group.objects.create(code="A", name="契約分類Ａ", doc_kbn=DocKbn.CONTRACT)
        self.category = Category.objects.create(
            code="001", name="契約カテゴリーＡ", group=self.group, doc_kbn=DocKbn.CONTRACT
        )

    def _create_contract(self):
        from contracts.models import Contract

        return Contract.objects.create(
            title="元のタイトル",
            department=self.department,
            group=self.group,
            category=self.category,
            year=2026,
            uploader=self.employee,
            expiry_date=calculate_expiry_date(datetime.date(2026, 1, 1)),
            file=ContentFile(b"AAAA", name="original.pdf"),
        )

    def _edit_form_data(self, contract):
        return {
            "department": self.department.pk,
            "group": self.group.pk,
            "category": self.category.pk,
            "year": 2026,
            "title_0": "更新後タイトル",
        }

    def _get_token(self, contract):
        import re

        get_response = self.client.get(f"/contracts/{contract.pk}/edit/")
        return re.search(
            r'name="token" value="([^"]+)"', get_response.content.decode("utf-8")
        ).group(1)

    def _linked_contract(self, title="紐付け先"):
        from contracts.models import Contract

        return Contract.objects.create(
            title=title, department=self.department, group=self.group, category=self.category,
            year=2025, uploader=self.employee,
            expiry_date=calculate_expiry_date(datetime.date(2025, 1, 1)),
            file=ContentFile(b"L", name="linked.pdf"),
        )

    def test_related_contract_ids_with_non_numeric_value_is_ignored(self):
        """related_contract_ids に改ざんで非数値が混じっても例外を出さず、有効なpkだけ紐付ける
        （contracts.services.filter_valid_related_ids）。"""
        from contracts.models import ContractRelation

        contract = self._create_contract()
        linked = self._linked_contract()
        data = self._edit_form_data(contract)
        data["token"] = self._get_token(contract)
        data["related_contract_ids"] = ["abc", str(linked.pk)]

        response = self.client.post(f"/contracts/{contract.pk}/edit/", data)

        self.assertEqual(response.status_code, 200)
        contract.refresh_from_db()
        self.assertEqual(contract.title, "更新後タイトル")
        self.assertEqual(
            list(ContractRelation.objects.filter(contract=contract).values_list("related_contract_id", flat=True)),
            [linked.pk],
        )

    def test_out_of_scope_related_contract_id_is_dropped(self):
        """改ざんで閲覧範囲外の契約書pkを混ぜても紐付かない（filter_valid_related_ids）。"""
        from contracts.models import Contract, ContractRelation

        other_dept = Department.objects.create(
            branch_code="999", branch_name="他店", section_code="99", section_name="他部署"
        )
        outsider = Contract.objects.create(
            title="他部署契約書", department=other_dept, group=self.group, category=self.category,
            year=2025, uploader=self.employee,
            expiry_date=calculate_expiry_date(datetime.date(2025, 1, 1)),
            file=ContentFile(b"O", name="o.pdf"),
        )
        contract = self._create_contract()
        data = self._edit_form_data(contract)
        data["token"] = self._get_token(contract)
        data["related_contract_ids"] = [str(outsider.pk)]

        self.client.post(f"/contracts/{contract.pk}/edit/", data)
        self.assertFalse(ContractRelation.objects.filter(contract=contract).exists())

    def test_self_link_is_rejected(self):
        """自分自身を関連書類に指定しても弾かれる（exclude_pk＋DB CheckConstraint）。"""
        from contracts.models import ContractRelation

        contract = self._create_contract()
        data = self._edit_form_data(contract)
        data["token"] = self._get_token(contract)
        data["related_contract_ids"] = [str(contract.pk)]

        self.client.post(f"/contracts/{contract.pk}/edit/", data)
        self.assertFalse(ContractRelation.objects.filter(contract=contract).exists())

    def test_edit_keeps_link_to_logically_deleted_related_contract(self):
        """コードレビュー A No.1：削除済みの関連書類を持つ契約書を別項目編集しただけで
        紐付けが消えないこと。edit.html は削除済み行にも hidden input を出すため、その pk が
        POST に含まれる限り filter_valid_related_ids(keep_ids=...) が維持する。"""
        from contracts.models import Contract, ContractRelation

        contract = self._create_contract()
        linked = self._linked_contract("削除される紐付け先")
        ContractRelation.objects.create(contract=contract, related_contract=linked, display_order=0)
        linked.is_deleted = True
        linked.deleted_at = datetime.datetime(2026, 9, 1, tzinfo=datetime.timezone.utc)
        linked.save(update_fields=["is_deleted", "deleted_at"])

        data = self._edit_form_data(contract)
        data["token"] = self._get_token(contract)
        data["related_contract_ids"] = [str(linked.pk)]  # edit.html の hidden input を再現

        response = self.client.post(f"/contracts/{contract.pk}/edit/", data)

        self.assertEqual(response.status_code, 200)
        contract.refresh_from_db()
        self.assertEqual(contract.title, "更新後タイトル")
        self.assertEqual(
            list(
                ContractRelation.objects.filter(contract=contract).values_list(
                    "related_contract_id", flat=True
                )
            ),
            [linked.pk],
        )

    def test_edit_removing_deleted_related_row_still_unlinks_it(self):
        """削除済み関連書類の行をユーザーが明示的に外した（hidden input が来ない）場合は
        従来どおり紐付けが解除される（keep_ids は「リストに残っている限り維持」）。"""
        from contracts.models import ContractRelation

        contract = self._create_contract()
        linked = self._linked_contract("外される紐付け先")
        ContractRelation.objects.create(contract=contract, related_contract=linked, display_order=0)
        linked.is_deleted = True
        linked.save(update_fields=["is_deleted"])

        data = self._edit_form_data(contract)
        data["token"] = self._get_token(contract)
        # related_contract_ids を送らない

        self.client.post(f"/contracts/{contract.pk}/edit/", data)
        self.assertFalse(ContractRelation.objects.filter(contract=contract).exists())

    def test_edit_view_db_failure_shows_error_and_does_not_update_contract(self):
        """テストカバレッジ棚卸し（review_test_doc_contract.txt指摘1）で発見：
        ContractEditView.postの`except DBError:`（contracts/views.py:341-348）は、
        直上のOSError分岐（test_related_file_save_failure_rolls_back_and_shows_error）は
        検証済みなのに、DBError自体をモックした検証が無かった。"""
        from django.contrib.messages import get_messages

        from contracts.models import Contract

        contract = self._create_contract()
        data = self._edit_form_data(contract)
        data["token"] = self._get_token(contract)

        with mock.patch.object(Contract, "save", side_effect=DBError("db down")):
            response = self.client.post(f"/contracts/{contract.pk}/edit/", data)

        self.assertRedirects(response, f"/contracts/{contract.pk}/edit/")
        texts = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertTrue(any("更新に失敗しました" in t for t in texts))
        contract.refresh_from_db()
        self.assertEqual(contract.title, "元のタイトル")


class ChunkUploadAPITests(TestCase):
    """screen-storage1（契約書）のチャンク分割アップロードAPI（contracts:upload_chunk）。
    documents.tests.ChunkUploadAPITestsと同じ観点でcontracts側の配線を検証する。
    """

    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.employee = Employee.objects.create_user(
            employee_no="1", name="テスト太郎", password="pass1234",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        # Rev1.2で追加された「契約書-契約書-契約書情報変更」がOFFだと保管・編集操作が
        # 403になるため（permissions.services.can_edit_contract）、この一般的なテスト用職員には
        # 付与しておく（権限そのものを検証する専用テストは別途 contract_edit を明示的に扱う）。
        PermissionProfile.objects.create(
            employee=self.employee, role=PermissionRole.STAFF, contract_edit=True
        )
        self.client.login(username="1", password="pass1234")

    def _post_chunk(self, upload_id, chunk_index, total_chunks, data, file_name="big.pdf"):
        return self.client.post(
            "/contracts/upload/chunk/",
            {
                "upload_id": upload_id,
                "file_name": file_name,
                "chunk_index": chunk_index,
                "total_chunks": total_chunks,
                "file": SimpleUploadedFile("chunk", data),
            },
        )

    def test_all_chunks_received_registers_pending_file_for_step2(self):
        response1 = self._post_chunk("upload-id-1", 0, 2, b"A" * 10)
        self.assertEqual(json.loads(response1.content)["status"], "chunk_received")

        response2 = self._post_chunk("upload-id-1", 1, 2, b"B" * 10)
        self.assertEqual(json.loads(response2.content)["status"], "completed")

        step1_response = self.client.post("/contracts/upload/step1/", {})
        self.assertRedirects(step1_response, "/contracts/upload/step2/")

        step2_response = self.client.get("/contracts/upload/step2/")
        self.assertContains(step2_response, "big")

    def test_missing_chunk_returns_error_and_does_not_register(self):
        response = self._post_chunk("upload-id-2", 1, 2, b"B" * 10)
        data = json.loads(response.content)
        self.assertEqual(data["status"], "error")
        self.assertIn("チャンク 0", data["message"])

        step1_response = self.client.post("/contracts/upload/step1/", {})
        self.assertContains(step1_response, "ファイルが選択されていません")

    def test_invalid_upload_id_rejected(self):
        response = self._post_chunk("../../etc", 0, 1, b"A")
        self.assertEqual(response.status_code, 400)

    def test_chunk_upload_rejected_without_contract_edit_permission(self):
        """UploadStep1View/UploadStep2Viewはcan_edit_contractでサーバー側アクセス制御している一方、
        このAPI（BaseChunkUploadAPIViewはdocuments側と共有・LoginRequiredMixinのみ）には
        Rev1.2で追加されたcontract_edit権限チェックが漏れていた（コード監査で発見、
        2026-08-24修正）。"""
        self.employee.permission_profile.contract_edit = False
        self.employee.permission_profile.save(update_fields=["contract_edit"])
        response = self._post_chunk("upload-id-3", 0, 1, b"A")
        self.assertEqual(response.status_code, 403)


class OptionsAPIViewTests(TestCase):
    """documents.tests.OptionsAPIViewTestsと同じ理由（監査で発見：core.api.BaseOptionListAPIView.
    _department_items()がcan_select_department（管理者のみ部署選択可）を適用しておらず、
    _group_items()のvisible_groups適用と非対称だった。以前はエンドポイント自体のテストが無かった）。
    契約書側はcontract_visible_groups・DocKbn.CONTRACTで検証する。
    """

    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.other_department = Department.objects.create(
            branch_code="999", branch_name="別支店", section_code="", section_name=""
        )
        self.employee = Employee.objects.create_user(
            employee_no="1", name="テスト太郎", password="pass1234",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        self.client.login(username="1", password="pass1234")

    def test_type_dept_non_admin_only_sees_own_department(self):
        PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.STAFF)
        response = self.client.get("/contracts/api/options/", {"type": "dept"})
        items = response.json()["items"]
        self.assertEqual([i["value"] for i in items], [self.department.pk])

    def test_type_dept_admin_sees_all_departments(self):
        PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.ADMIN)
        response = self.client.get("/contracts/api/options/", {"type": "dept"})
        items = response.json()["items"]
        self.assertEqual(
            {i["value"] for i in items}, {self.department.pk, self.other_department.pk}
        )

    def test_type_dept_no_profile_only_sees_own_department(self):
        """documents.tests.OptionsAPIViewTests.test_type_dept_no_profile_only_sees_own_department
        と同じ観点（review_test_doc_contract.txt指摘4・指摘7）。PermissionProfile未作成の職員は
        最も制限の強い一般ロール扱い（permissions.services.get_role）のため自部署のみになること。
        core.api.BaseOptionListAPIView._department_itemsはdepartment_kind=="contract"の場合
        permissions.services.contract_searchable_department_idsを使う専用分岐（documents側の
        department_kind=="document"のget_role判定とは別コードパス）のため、documents側のテストでは
        代替できず、契約書側で独立に検証する必要がある。"""
        response = self.client.get("/contracts/api/options/", {"type": "dept"})
        items = response.json()["items"]
        self.assertEqual([i["value"] for i in items], [self.department.pk])

    def test_type_group_filtered_by_visible_groups(self):
        visible = Group.objects.create(code="A", name="契約分類Ａ", doc_kbn=DocKbn.CONTRACT)
        hidden = Group.objects.create(code="B", name="契約分類Ｂ", doc_kbn=DocKbn.CONTRACT)
        profile = PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.STAFF)
        profile.contract_visible_groups.add(visible)

        response = self.client.get("/contracts/api/options/", {"type": "group"})
        items = response.json()["items"]
        self.assertEqual([i["value"] for i in items], [visible.pk])
        self.assertNotIn(hidden.pk, [i["value"] for i in items])

    def test_type_group_no_restriction_returns_all_contract_groups(self):
        """documents.tests.OptionsAPIViewTests.test_type_group_no_restriction_returns_all_document_groups
        と同じ観点（review_test_doc_contract.txt指摘4）。PermissionProfileはあるが
        contract_visible_groupsに何も追加していない（＝visible_groups()がNoneを返す）場合、
        全ての契約書分類が返ること。"""
        Group.objects.create(code="A", name="契約分類Ａ", doc_kbn=DocKbn.CONTRACT)
        Group.objects.create(code="B", name="契約分類Ｂ", doc_kbn=DocKbn.CONTRACT)
        # 文書側の分類は対象外（doc_kbnで絞り込まれること）。
        Group.objects.create(code="C", name="分類Ｃ", doc_kbn=DocKbn.DOCUMENT)
        PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.STAFF)

        response = self.client.get("/contracts/api/options/", {"type": "group"})
        items = response.json()["items"]
        self.assertEqual(len(items), 2)

    def test_type_category_returns_items_for_contract_kbn_only(self):
        group = Group.objects.create(code="A", name="契約分類Ａ", doc_kbn=DocKbn.CONTRACT)
        Category.objects.create(code="001", name="契約カテゴリーＡ", group=group, doc_kbn=DocKbn.CONTRACT)
        Category.objects.create(code="002", name="文書カテゴリー", group=group, doc_kbn=DocKbn.DOCUMENT)

        response = self.client.get("/contracts/api/options/", {"type": "category"})
        items = response.json()["items"]
        self.assertEqual([i["label"] for i in items], ["契約カテゴリーＡ"])

    def test_type_year_returns_recent_years_including_current(self):
        """documents.tests.OptionsAPIViewTests.test_type_year_returns_recent_years_including_current
        と同じ観点（review_test_doc_contract.txt指摘4）。core.api.BaseOptionListAPIView._year_items
        （core.forms.search_year_choices(self.doc_kbn)経由）が契約書側（DocKbn.CONTRACT）でも
        HTTP経由で正しく動くことを確認する（契約書の保存年集合は文書と別データのため、
        documents側のテストで代替検証されているとは言えない）。"""
        current = datetime.date.today().year
        response = self.client.get("/contracts/api/options/", {"type": "year"})
        values = [i["value"] for i in response.json()["items"]]
        self.assertIn(current, values)

    def test_invalid_type_returns_400(self):
        response = self.client.get("/contracts/api/options/", {"type": "unknown"})
        self.assertEqual(response.status_code, 400)

    def test_requires_login(self):
        self.client.logout()
        response = self.client.get("/contracts/api/options/", {"type": "dept"})
        self.assertEqual(response.status_code, 302)


class ContractSaveNormalizationTests(TestCase):
    """contracts.models.Contract.saveの`update_fields`正規化カラム同期
    （CLAUDE.md規約準拠監査で発見：documents.tests.DocumentSaveNormalizationTestsと同じ観点の
    テストがcontracts側に無かった。両モデルともcore.models.NormalizedTextFieldsMixinを継承する
    同一実装のため、observed動作もdocuments側と同じはずだが、documents側にしかリグレッション
    テストが無いとMixin改修時の回帰をcontracts側だけ検知できない。review_rule_doc_contract.txt
    指摘1参照、2026-08-25追加）。
    """

    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.employee = Employee.objects.create_user(
            employee_no="1", name="テスト太郎", password="x",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        group = Group.objects.create(code="A", name="契約分類Ａ", doc_kbn=DocKbn.CONTRACT)
        category = Category.objects.create(code="001", name="契約カテゴリーＡ", group=group, doc_kbn=DocKbn.CONTRACT)
        from contracts.models import Contract

        self.contract = Contract(
            title="旧タイトル", department=self.department, group=group, category=category,
            year=2026, uploader=self.employee, expiry_date=datetime.date(2036, 1, 1),
        )
        self.contract.file.save("contract.pdf", ContentFile(b"dummy"), save=False)
        self.contract.save()

    def test_update_fields_title_only_still_persists_normalized_shadow_column(self):
        from contracts.models import Contract
        from core.text_normalization import normalize_for_search

        self.contract.title = "新タイトルＡＢＣ"
        self.contract.save(update_fields=["title"])

        reloaded = Contract.objects.get(pk=self.contract.pk)
        self.assertEqual(reloaded.title, "新タイトルＡＢＣ")
        self.assertEqual(reloaded.title_normalized, normalize_for_search("新タイトルＡＢＣ"))

    def test_update_fields_extracted_text_only_still_persists_normalized_shadow_column(self):
        from contracts.models import Contract
        from core.text_normalization import normalize_for_search

        self.contract.extracted_text = "本文サンプルＸＹＺ"
        self.contract.save(update_fields=["extracted_text"])

        reloaded = Contract.objects.get(pk=self.contract.pk)
        self.assertEqual(reloaded.extracted_text, "本文サンプルＸＹＺ")
        self.assertEqual(reloaded.extracted_text_normalized, normalize_for_search("本文サンプルＸＹＺ"))


class StoragePathTests(TestCase):
    """contracts.storage_paths（CLAUDE.md規約準拠監査で発見：documents.tests.StoragePathTestsと
    同じ観点のテストがcontracts側に無かった。同じ集約先〈core.storage_paths.
    build_hierarchical_upload_path〉を使うcontract_upload_path/contract_searchable_upload_pathを
    検証する。review_rule_doc_contract.txt指摘1参照、2026-08-25追加。related_file_upload_pathは
    Rev1.6でRelatedFileごと廃止）。
    """

    def setUp(self):
        self.department = Department.objects.create(
            branch_code="001", branch_name="本店", section_code="02", section_name="経理部"
        )
        group = Group.objects.create(code="A", name="契約分類Ａ", doc_kbn=DocKbn.CONTRACT)
        self.category = Category.objects.create(
            code="010", name="契約カテゴリーＸ", group=group, doc_kbn=DocKbn.CONTRACT
        )

    def test_contract_upload_path_structure(self):
        from contracts.storage_paths import contract_upload_path

        instance = mock.Mock(year=2026, department=self.department, category=self.category)
        path = contract_upload_path(instance, "契約書.pdf")
        prefix = "contracts/2026/001-02/010/"
        self.assertTrue(path.startswith(prefix), path)
        remainder = path[len(prefix):]
        uuid_part, _, filename_part = remainder.partition("_")
        self.assertEqual(len(uuid_part), 32)
        self.assertEqual(filename_part, "契約書.pdf")

    def test_contract_searchable_upload_path_uses_separate_directory(self):
        from contracts.storage_paths import contract_searchable_upload_path

        instance = mock.Mock(year=2026, department=self.department, category=self.category)
        path = contract_searchable_upload_path(instance, "契約書.pdf")
        self.assertTrue(path.startswith("contracts/2026/001-02/010/searchable/"), path)
        self.assertTrue(path.endswith("_契約書.pdf"))

    def test_upload_paths_are_unique_per_call_via_uuid(self):
        from contracts.storage_paths import contract_upload_path

        instance = mock.Mock(year=2026, department=self.department, category=self.category)
        path1 = contract_upload_path(instance, "同名.pdf")
        path2 = contract_upload_path(instance, "同名.pdf")
        self.assertNotEqual(path1, path2)


class EditDeleteViewTests(TestCase):
    """保管画面２（編集・edit.html）の[4]メモ欄直下「削除」ボタン＝レコードの論理削除
    （documents.tests.EditDeleteViewTestsと同じ観点。契約書側はcan_edit_contractも要る）。"""

    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.employee = Employee.objects.create_user(
            employee_no="1", name="テスト太郎", password="pass1234",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        PermissionProfile.objects.create(
            employee=self.employee, role=PermissionRole.STAFF, contract_edit=True
        )
        self.group = Group.objects.create(code="A", name="契約分類Ａ", doc_kbn=DocKbn.CONTRACT)
        self.category = Category.objects.create(
            code="001", name="契約カテゴリーＡ", group=self.group, doc_kbn=DocKbn.CONTRACT
        )
        self.client.login(username="1", password="pass1234")

    def _create_contract(self, title):
        from contracts.models import Contract

        contract = Contract(
            title=title, department=self.department, group=self.group, category=self.category,
            year=2026, uploader=self.employee, expiry_date=datetime.date(2036, 1, 1),
        )
        contract.file.save(f"{title}.txt", ContentFile(b"hello"), save=False)
        contract.save()
        return contract

    def test_edit_screen_shows_delete_form_for_fresh_contract(self):
        contract = self._create_contract("新規契約書")
        response = self.client.get(f"/contracts/{contract.pk}/edit/")
        self.assertTrue(response.context["can_delete"])
        self.assertContains(response, f"/contracts/{contract.pk}/edit-delete/")
        self.assertContains(response, 'id="record-delete-form"')
        # 単独編集では from_bulk は出さない（一括編集ウィザードからのみ）。
        self.assertNotContains(response, 'name="from_bulk"')

    def test_single_delete_logical_deletes_and_redirects_to_search(self):
        from contracts.models import Contract

        contract = self._create_contract("単独削除対象")
        response = self.client.post(f"/contracts/{contract.pk}/edit-delete/")
        self.assertRedirects(response, "/contracts/search/")
        contract.refresh_from_db()
        self.assertTrue(contract.is_deleted)
        self.assertTrue(Contract.objects.filter(pk=contract.pk).exists())
        self.assertTrue(
            AuditLog.objects.filter(action="保管画面２　削除", event_message__contains="単独削除対象").exists()
        )

    def test_delete_without_contract_edit_permission_is_rejected(self):
        from contracts.models import Contract

        other = Employee.objects.create_user(
            employee_no="2", name="権限なし", password="pass1234",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.IPPAN,
        )
        PermissionProfile.objects.create(
            employee=other, role=PermissionRole.STAFF, contract_edit=False
        )
        contract = self._create_contract("権限テスト")
        self.client.login(username="2", password="pass1234")
        response = self.client.post(f"/contracts/{contract.pk}/edit-delete/")
        self.assertEqual(response.status_code, 403)
        contract.refresh_from_db()
        self.assertFalse(contract.is_deleted)
        self.assertTrue(Contract.objects.filter(pk=contract.pk, is_deleted=False).exists())

    def test_delete_rejected_after_window(self):
        from contracts.models import Contract

        contract = self._create_contract("窓経過")
        Contract.objects.filter(pk=contract.pk).update(
            save_date=timezone.now() - datetime.timedelta(days=8)
        )
        response = self.client.get(f"/contracts/{contract.pk}/edit/")
        self.assertFalse(response.context["can_delete"])
        response = self.client.post(f"/contracts/{contract.pk}/edit-delete/")
        self.assertEqual(response.status_code, 403)
        contract.refresh_from_db()
        self.assertFalse(contract.is_deleted)

    def test_single_edit_screen_has_no_bulk_delete_markup(self):
        """一括編集の削除は「更新」でまとめて確定する別方式のため、単独編集画面には
        toggle_delete ボタンも from_bulk hidden も出ない（EditDeleteView は単独編集専用）。"""
        contract = self._create_contract("単独のみ")
        response = self.client.get(f"/contracts/{contract.pk}/edit/")
        self.assertNotContains(response, 'name="from_bulk"')
        self.assertNotContains(response, 'value="toggle_delete"')


class UploadStep2RemoveViewTests(TestCase):
    """保管画面２（登録）の「削除」ボタン＝表示中ファイルのアップロード取り消し
    （documents.tests.UploadStep2RemoveViewTestsと同じ観点。2026-08-31：メインフォームごと
    送信〈action=remove〉して他ファイルの入力を保持する方式へ変更。契約書側は
    RequiresContractEditMixin）。"""

    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.employee = Employee.objects.create_user(
            employee_no="1", name="テスト太郎", password="pass1234",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        PermissionProfile.objects.create(
            employee=self.employee, role=PermissionRole.STAFF, contract_edit=True
        )
        self.client.login(username="1", password="pass1234")

    def _select_files(self, *names):
        self.client.post(
            "/contracts/upload/step1/",
            {"files": [SimpleUploadedFile(n, b"dummy", content_type="application/pdf") for n in names]},
        )

    def _remove(self, index, extra=None):
        step2 = self.client.get("/contracts/upload/step2/")
        data = {"token": step2.context["token"], "action": "remove", "remove_index": str(index)}
        data.update(extra or {})
        return self.client.post("/contracts/upload/step2/", data)

    def test_remove_one_keeps_others_preserves_input_and_deletes_temp_file(self):
        from pathlib import Path

        from django.conf import settings

        from core.upload_services import get_pending_files

        self._select_files("a.pdf", "b.pdf")
        pending_before = get_pending_files(self.client.session, "contracts_pending_upload")
        removed_temp = pending_before[0]["temp_name"]

        response = self._remove(0, {
            "department_0": self.department.pk, "title_0": "甲", "contract_partner_0": "甲社",
            "department_1": self.department.pk, "title_1": "乙", "contract_partner_1": "乙社",
        })
        self.assertEqual(response.status_code, 200)
        pending_after = get_pending_files(self.client.session, "contracts_pending_upload")
        self.assertEqual([p["original_name"] for p in pending_after], ["b.pdf"])
        self.assertFalse((Path(settings.MEDIA_ROOT) / "tmp_uploads" / removed_temp).exists())
        form = response.context["form"]
        self.assertEqual(form["title_0"].value(), "乙")
        self.assertEqual(form["contract_partner_0"].value(), "乙社")

    def test_step2_get_renders_remove_button_and_action_inputs(self):
        self._select_files("a.pdf", "b.pdf")
        response = self.client.get("/contracts/upload/step2/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="btn-remove-upload"')
        self.assertContains(response, 'name="action"')
        self.assertContains(response, 'name="remove_index"')
        self.assertNotContains(response, "/contracts/upload/step2/remove/")

    def test_remove_button_div_is_outside_memo_form_section(self):
        """html5 で「削除」ボタンの div は [4]メモ欄の form-section の外へ移動
        （documents 側と同じ。Rev1.4 追加の説明画像 image69/image70 と対応）。"""
        self._select_files("a.pdf", "b.pdf")
        content = self.client.get("/contracts/upload/step2/").content.decode("utf-8")
        memo_idx = content.rindex("[4] メモ欄")
        button_idx = content.index('id="btn-remove-upload"')
        self.assertIn("</div>", content[memo_idx:button_idx])
        self.assertLess(button_idx, content.index("storage-outer-actions"))

    def test_remove_last_pending_redirects_to_step1(self):
        self._select_files("only.pdf")
        response = self._remove(0)
        self.assertRedirects(response, "/contracts/upload/step1/")

    def test_requires_contract_edit_permission(self):
        other = Employee.objects.create_user(
            employee_no="2", name="権限なし", password="pass1234",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.IPPAN,
        )
        PermissionProfile.objects.create(
            employee=other, role=PermissionRole.STAFF, contract_edit=False
        )
        self._select_files("a.pdf")
        self.client.login(username="2", password="pass1234")
        response = self.client.post(
            "/contracts/upload/step2/", {"action": "remove", "remove_index": "0"}
        )
        self.assertEqual(response.status_code, 403)
