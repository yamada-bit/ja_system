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
from contracts.services import calculate_expiry_date
from masters.models import Category, DocKbn, Group
from organizations.models import Department
from permissions.models import PermissionProfile, PermissionRole


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
        docstring参照）。既に削除済みの契約書への削除操作はサーバー側でも拒否し、本体・関連書類
        （RelatedFile）ともレコード・ファイルが残ることを確認する。"""
        from contracts.models import Contract, RelatedFile

        related = RelatedFile.objects.create(
            contract=self.contract, file=ContentFile(b"REL", name="付属資料.pdf"), display_order=0
        )
        contract_file_name = self.contract.file.name
        related_file_name = related.file.name

        self.contract.is_deleted = True
        self.contract.save(update_fields=["is_deleted", "deleted_at"])

        response = self.client.post(
            f"/contracts/{self.contract.pk}/delete/", HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.json()["success"])
        self.assertTrue(Contract.objects.filter(pk=self.contract.pk).exists())
        self.assertTrue(RelatedFile.objects.filter(pk=related.pk).exists())
        self.assertTrue(self.contract.file.storage.exists(contract_file_name))
        self.assertTrue(self.contract.file.storage.exists(related_file_name))

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


class RelatedFilesMultiUploadTests(TestCase):
    """契約書の複数件一括登録時、原本index.html:1567-1589のsetupStorageFormForActiveDoc()通り
    文書ごとに独立した関連書類を添付できる（原本フィデリティ監査で発見：以前は1件登録時のみ
    許可していた）。"""

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

    def test_each_document_gets_its_own_related_files(self):
        import re

        from django.core.files.uploadedfile import SimpleUploadedFile

        from contracts.models import Contract

        self.client.post("/contracts/upload/step1/", {"files": [
            SimpleUploadedFile("a.pdf", b"AAAA", content_type="application/pdf"),
            SimpleUploadedFile("b.pdf", b"BBBB", content_type="application/pdf"),
        ]})
        step2 = self.client.get("/contracts/upload/step2/")
        token = re.search(r'name="token" value="([^"]+)"', step2.content.decode("utf-8")).group(1)

        before = set(Contract.objects.values_list("pk", flat=True))
        self.client.post("/contracts/upload/step2/", {
            "token": token,
            "department": self.department.pk,
            "group": self.group.pk,
            "category": self.category.pk,
            "year": 2026,
            "title_0": "契約書A",
            "title_1": "契約書B",
            "related_files_0": SimpleUploadedFile("rel_a.txt", b"REL-A"),
            "related_files_1": SimpleUploadedFile("rel_b.txt", b"REL-B"),
        })
        created = list(Contract.objects.exclude(pk__in=before).order_by("pk"))
        self.assertEqual(len(created), 2)
        self.assertIn("rel_a", created[0].related_files.get().file.name)
        self.assertIn("rel_b", created[1].related_files.get().file.name)


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
        entry = AuditLog.objects.get(action="契約書検索 ダウンロード")
        self.assertEqual(entry.employee_no, "1")
        self.assertIn("DL対象", entry.event_message)

    def test_denied_download_does_not_create_audit_log(self):
        response = self.client.get(f"/contracts/{self.contract.pk}/download/")
        self.assertEqual(response.status_code, 403)
        self.assertFalse(AuditLog.objects.filter(action="契約書検索 ダウンロード").exists())

    def test_deleted_contract_download_returns_404(self):
        """documents.tests.DownloadViewTests.test_deleted_document_download_returns_404と同じ理由
        （xlsx 検索・閲覧・変更!B659(Rev1.2)「削除されている契約書は、ボタンを非表示とする」の
        URL直打ち対策）。"""
        PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.STAFF, contract_download=True)
        self.contract.is_deleted = True
        self.contract.save(update_fields=["is_deleted"])
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
        entry = AuditLog.objects.get(action="契約書検索 一括ダウンロード")
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


class BulkEditViewTests(TestCase):
    """screen-search（契約書モード）「一括編集」。documents.tests.BulkEditViewTestsと同じ設計・
    同じアサーション観点（save-as-you-go方式、AuditLogが契約書ごとに1件ずつ記録されること）。"""

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

    def _step_data(self, title, bulk_nav=None):
        data = {
            "token": self._get_token(),
            "department": self.department.pk,
            "group": self.group.pk,
            "category": self.category.pk,
            "year": 2026,
            "title_0": title,
        }
        if bulk_nav:
            data["bulk_nav"] = bulk_nav
        return data

    def test_start_without_selection_redirects_with_message(self):
        response = self.client.post("/contracts/bulk-edit/start/", {})
        self.assertRedirects(response, "/contracts/search/")

    def test_direct_access_without_session_state_redirects(self):
        response = self.client.get("/contracts/bulk-edit/")
        self.assertRedirects(response, "/contracts/search/")

    def test_walk_through_two_contracts_saves_each_and_records_per_item_audit_log(self):
        contract1 = self._create_contract("c1")
        contract2 = self._create_contract("c2")
        self.client.post("/contracts/bulk-edit/start/", {"pks": [contract1.pk, contract2.pk]})

        get_response = self.client.get("/contracts/bulk-edit/")
        self.assertContains(get_response, "1 / 2")
        response = self.client.post("/contracts/bulk-edit/", self._step_data("c1-編集後"))
        self.assertRedirects(response, "/contracts/bulk-edit/")
        contract1.refresh_from_db()
        self.assertEqual(contract1.title, "c1-編集後")

        get_response = self.client.get("/contracts/bulk-edit/")
        self.assertContains(get_response, "2 / 2")
        response = self.client.post("/contracts/bulk-edit/", self._step_data("c2-編集後"))
        self.assertEqual(response.status_code, 200)
        contract2.refresh_from_db()
        self.assertEqual(contract2.title, "c2-編集後")
        created = response.context["complete"]["created"]
        self.assertEqual([c.pk for c in created], [contract1.pk, contract2.pk])

        entries = AuditLog.objects.filter(action="保管画面２ 更新").order_by("timestamp")
        self.assertEqual(entries.count(), 2)
        self.assertIn("c1-編集後", entries[0].event_message)
        self.assertIn("c2-編集後", entries[1].event_message)


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
        self.assertTrue(AuditLog.objects.filter(action="契約書検索 プレビュー").exists())

    def test_missing_file_returns_404(self):
        PermissionProfile.objects.create(
            employee=self.employee, role=PermissionRole.STAFF, contract_download=True
        )
        with mock.patch(
            "django.db.models.fields.files.FieldFile.open", side_effect=OSError("missing")
        ):
            response = self.client.get(f"/contracts/{self.contract.pk}/preview/")
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

        self._grant_contract_download()
        response = self.client.get(f"/contracts/{contract.pk}/edit/")
        self.assertEqual(response.context["preview_kind"], "pdf")
        self.assertTrue(response.context["can_download"])
        self.assertContains(response, f'<iframe src="/contracts/{contract.pk}/preview/"')


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
        from contracts.forms import UploadStep2Form

        form = UploadStep2Form(employee=self.admin, edit_mode=False)
        self.assertEqual(form["department"].value(), self.admin.department_id)

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

    def test_related_files_returns_display_name_not_full_path(self):
        """監査で発見：以前はrf.file.name（MEDIA_ROOT基準のフルパス）をそのまま返しており、
        詳細ポップアップの「関連書類」欄が長いパス表示になっていた。"""
        from contracts.models import RelatedFile

        related = RelatedFile.objects.create(
            contract=self.contract,
            file=ContentFile(b"REL", name="付属資料.pdf"),
            display_order=0,
        )
        response = self.client.get(f"/contracts/api/{self.contract.pk}/")
        data = response.json()
        self.assertEqual(data["related_files"], ["付属資料.pdf"])
        self.assertNotIn(related.file.name, data["related_files"])

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
        """xlsx 保管!B300,B581・検索・閲覧・変更!B664-665「初回登録から1週間以上経過している
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
                    "token": token,
                    "department": self.department.pk,
                    "group": group.pk,
                    "category": category.pk,
                    "year": 2026,
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
                    "token": self.token,
                    "department": self.department.pk,
                    "group": self.group.pk,
                    "category": self.category.pk,
                    "year": 2026,
                    "title_0": "テスト契約書",
                },
            )
        self.assertEqual(response.status_code, 200)
        contract = Contract.objects.get(title="テスト契約書")
        self.assertEqual(contract.extracted_text, "十分な文字数を含む本文テキストです。")


class ContractEditViewFileHandlingTests(TestCase):
    """ContractEditView.postの関連書類追加・削除まわり（原本index.html:1567-1589の
    handleRelatedFileChange/removeExistingRelatedFile対応）を監査で発見・修正した2点、
    (1) remove_related_idsへの改ざん値混入でValueErrorが伝播しないこと、
    (2) 関連書類のファイルI/O失敗時にtransaction.atomic()で本体更新までロールバックされ、
    利用者にわかるエラーメッセージが出ることを確認する。"""

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

    def test_remove_related_ids_with_non_numeric_value_is_ignored(self):
        from contracts.models import RelatedFile

        contract = self._create_contract()
        related = RelatedFile.objects.create(
            contract=contract, file=ContentFile(b"BBBB", name="related.pdf"), display_order=0
        )
        data = self._edit_form_data(contract)
        data["token"] = self._get_token(contract)
        data["remove_related_ids"] = f"abc,{related.pk}"

        response = self.client.post(f"/contracts/{contract.pk}/edit/", data)

        self.assertEqual(response.status_code, 200)
        contract.refresh_from_db()
        self.assertEqual(contract.title, "更新後タイトル")
        self.assertFalse(RelatedFile.objects.filter(pk=related.pk).exists())

    def test_related_file_save_failure_rolls_back_and_shows_error(self):
        from contracts.models import Contract, RelatedFile

        contract = self._create_contract()
        data = self._edit_form_data(contract)
        data["token"] = self._get_token(contract)

        with mock.patch(
            "contracts.models.RelatedFile.objects.create", side_effect=OSError("disk full")
        ):
            response = self.client.post(
                f"/contracts/{contract.pk}/edit/",
                {**data, "related_files": [ContentFile(b"CCCC", name="new.pdf")]},
                format="multipart",
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], f"/contracts/{contract.pk}/edit/")
        contract.refresh_from_db()
        # transaction.atomic()により本体タイトルの更新もロールバックされていること
        self.assertEqual(contract.title, "元のタイトル")
        self.assertFalse(RelatedFile.objects.filter(contract=contract).exists())


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

    def test_type_group_filtered_by_visible_groups(self):
        visible = Group.objects.create(code="A", name="契約分類Ａ", doc_kbn=DocKbn.CONTRACT)
        hidden = Group.objects.create(code="B", name="契約分類Ｂ", doc_kbn=DocKbn.CONTRACT)
        profile = PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.STAFF)
        profile.contract_visible_groups.add(visible)

        response = self.client.get("/contracts/api/options/", {"type": "group"})
        items = response.json()["items"]
        self.assertEqual([i["value"] for i in items], [visible.pk])
        self.assertNotIn(hidden.pk, [i["value"] for i in items])

    def test_type_category_returns_items_for_contract_kbn_only(self):
        group = Group.objects.create(code="A", name="契約分類Ａ", doc_kbn=DocKbn.CONTRACT)
        Category.objects.create(code="001", name="契約カテゴリーＡ", group=group, doc_kbn=DocKbn.CONTRACT)
        Category.objects.create(code="002", name="文書カテゴリー", group=group, doc_kbn=DocKbn.DOCUMENT)

        response = self.client.get("/contracts/api/options/", {"type": "category"})
        items = response.json()["items"]
        self.assertEqual([i["label"] for i in items], ["契約カテゴリーＡ"])

    def test_invalid_type_returns_400(self):
        response = self.client.get("/contracts/api/options/", {"type": "unknown"})
        self.assertEqual(response.status_code, 400)

    def test_requires_login(self):
        self.client.logout()
        response = self.client.get("/contracts/api/options/", {"type": "dept"})
        self.assertEqual(response.status_code, 302)
