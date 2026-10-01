import datetime
import os
import tempfile
import time
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.contrib.sessions.backends.db import SessionStore
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import CommandError, call_command
from django.db import DatabaseError, OperationalError
from django.template import Context, Template
from django.test import TestCase, override_settings
from django.utils import timezone
from pypdf import PdfReader, PdfWriter

from accounts.models import Employee, Position, Rank
from audit.models import AuditLog
from core import ocr_layout_services, pdf_text_embed_services, searchable_pdf_services
from core.double_submit import consume_token, issue_token
from core.file_serving import apply_file_response_security_headers, resolve_as_attachment
from core.file_type_services import is_image_filename
from core.upload_validation import blocked_upload_message, non_pdf_upload_message
from core.csv_services import sanitize_csv_cell, sanitize_csv_row
from core.forms import search_year_choices
from core.middleware import SESSION_LAST_ACTIVITY_KEY
from core.notice_services import add_months, get_notice_counts, is_expiring_soon
from core.ocr_layout_services import OcrDisabledError, OcrTimeLimitError, TextData, TextDatas
from core.text_extraction_services import (
    is_scanned, try_immediate_text_layer_extraction, try_immediate_text_layer_extraction_batch,
)
from core.text_normalization import normalize_for_search
from core.upload_services import (
    ChunkUploadError,
    PendingFileStorageError,
    TMP_UPLOAD_SUBDIR,
    clear_pending_files,
    combine_upload_chunks,
    open_pending_file,
    remove_pending_file,
    save_pending_files,
    save_upload_chunk,
)
from core.widgets import PopupSelectWidget
from masters.models import (
    Category,
    DocKbn,
    Group,
    RetentionKbn,
    RetentionPeriod,
    RetentionPeriodUnit,
    SystemSetting,
)
from organizations.models import Department, DepartmentViewScope, MenuItemSetting
from permissions.models import PermissionProfile, PermissionRole


class MenuViewNoticeThresholdDisplayTests(TestCase):
    """screen-menuのお知らせ文言「有効期限切れまでXヶ月以内」「直近Xヶ月内で削除」のX表示。

    原本index.html:121-122は実際にはJSでも一度も置換されない静的モック文言「X ヶ月」だった
    （原本フィデリティ監査で発見）。件数側は既に実データを表示しているため不整合になっており、
    実際の設定値（settings.NOTICE_EXPIRING_THRESHOLD_MONTHS/NOTICE_DELETED_THRESHOLD_MONTHS）を
    表示するよう修正した（2026-08-13ユーザー指摘）。
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

    @override_settings(NOTICE_EXPIRING_THRESHOLD_MONTHS=3, NOTICE_DELETED_THRESHOLD_MONTHS=2)
    def test_menu_displays_configured_threshold_values(self):
        response = self.client.get("/")
        self.assertContains(response, "有効期限切れまで 3 ヶ月以内の文書が")
        self.assertContains(response, "直近 2 ヶ月内で削除された文書が")


class SearchYearChoicesTests(TestCase):
    """screen-search「年」プルダウン／年選択ポップアップの選択肢（core.forms.search_year_choices、
    xlsx 検索・閲覧・変更!B137-140「今年～文書が保存されている最古の年」、B499で契約書も同一規則）。
    """

    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.employee = Employee.objects.create_user(
            employee_no="1", name="テスト太郎", password="x",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        self.group = Group.objects.create(code="A", name="分類Ａ", doc_kbn=DocKbn.DOCUMENT)
        self.category = Category.objects.create(
            code="001", name="カテゴリーＡ", group=self.group, doc_kbn=DocKbn.DOCUMENT
        )
        self.retention_period = RetentionPeriod.objects.create(
            kbn=RetentionKbn.DOCUMENT, period_value=1, period_unit=RetentionPeriodUnit.YEAR, display_order=1
        )

    def test_no_documents_returns_current_year_only(self):
        current = datetime.date.today().year
        self.assertEqual(search_year_choices("document"), [(current, f"{current} 年")])

    def test_includes_range_down_to_oldest_saved_year(self):
        from documents.models import Document

        current = datetime.date.today().year
        oldest_year = current - 5
        doc = Document(
            title="古い文書", department=self.department, group=self.group, category=self.category,
            year=oldest_year, retention_period=self.retention_period, uploader=self.employee,
            expiry_date=datetime.date(current + 10, 1, 1),
        )
        doc.file.save("old.pdf", ContentFile(b"dummy"), save=False)
        doc.save()

        choices = search_year_choices("document")
        self.assertEqual(choices[0], (current, f"{current} 年"))
        self.assertEqual(choices[-1], (oldest_year, f"{oldest_year} 年"))
        self.assertEqual(len(choices), current - oldest_year + 1)

    def test_deleted_documents_do_not_extend_range(self):
        from documents.models import Document

        current = datetime.date.today().year
        doc = Document(
            title="ゴミ箱の古い文書", department=self.department, group=self.group, category=self.category,
            year=current - 20, retention_period=self.retention_period, uploader=self.employee,
            expiry_date=datetime.date(current + 10, 1, 1), is_deleted=True,
        )
        doc.file.save("old.pdf", ContentFile(b"dummy"), save=False)
        doc.save()

        self.assertEqual(search_year_choices("document"), [(current, f"{current} 年")])


class MenuNoticeTwoColumnLayoutTests(TestCase):
    """Rev1.2の埋め込み画像モック（メイン画面シート、セル文字列では検出できず画像ハッシュ突き合わせで
    発見）は、文書3項目・契約書3項目を左右に分けたブロック構成だった。テキストのみの1行2件数案は
    実際のモックと異なると判明したため、モック通りの2列構成に修正した（2026-08-24）。
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

    def test_document_and_contract_notices_rendered_as_separate_lists(self):
        response = self.client.get("/")
        content = response.content.decode("utf-8")
        # 文書側の3項目
        self.assertIn("有効期限切れの文書が", content)
        self.assertIn("有効期限切れまで", content)
        self.assertIn("ヶ月以内の文書が", content)
        self.assertIn("ヶ月内で削除された文書が", content)
        # 契約書側の3項目（文書と合体した1行ではなく独立した文言であること）
        self.assertIn("有効期限切れの契約書が", content)
        self.assertIn("ヶ月以内の契約書が", content)
        self.assertIn("ヶ月内で削除された契約書が", content)
        # 1行に「文書がX件、契約書がY件」と合体させる旧案の文言が残っていないこと
        self.assertNotIn("、契約書が", content)

    def test_notice_area_contains_two_ul_blocks(self):
        response = self.client.get("/")
        content = response.content.decode("utf-8")
        notice_area = content.split('class="notice-area"')[1]
        self.assertEqual(notice_area.count("<ul"), 2)

    def test_notice_columns_wrapper_matches_html5(self):
        """原本 index.html html5 に合わせ、左右2列のラッパを notice-columns クラス
        （＋ notice-columns>div > ul 構造）に統一し、style.css に flex 定義を持つ。"""
        content = self.client.get("/").content.decode("utf-8")
        notice_area = content.split('class="notice-area"')[1]
        self.assertIn('<div class="notice-columns">', notice_area)
        # 従来のインライン flex スタイルが残っていないこと
        self.assertNotIn("display:flex; gap:40px", notice_area)
        css = (settings.BASE_DIR / "static" / "css" / "style.css").read_text(encoding="utf-8")
        self.assertIn(".notice-columns {", css)
        self.assertIn(".notice-columns > div {", css)


class MenuButtonVisibilityTests(TestCase):
    """screen-menuのメニューボタン（検索・閲覧・変更/保管の文書・契約書）は
    organizations.MenuItemSettingの部署ごとの設定値で表示/非表示が決まる
    （xlsx メイン画面!B55「部署ごとに設定された内容でボタンの押下可不可を制御する」）。

    2026-08-19に一度連動させた後、未設定部署でボタンが全て消え原本の静的モックの見た目から
    乖離するとして撤回していたが、2026-08-26にユーザーが「実データ連動を優先する」方針へ
    再度変更したため改めて連動させた。未設定部署（MenuItemSettingレコード無し）は
    xlsx その他設定!B73「デフォルトは全項目OFF」通り全ボタン非表示になる。

    保管枠内「契約書」ボタンのみ、部署設定（show_storage_contract）に加えてRev1.2で追加された
    権限管理「契約書-契約書-契約書情報変更」（permissions.services.can_edit_contract）による
    表示制御がANDで重なる（xlsx 権限管理!B196-197「保存不可…メイン画面の保管枠内「契約書」
    ボタンを非表示にする」）。これは部署設定とは無関係の職員単位の権限制御。
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

    def test_all_buttons_hidden_for_unconfigured_department(self):
        from django.urls import reverse

        response = self.client.get("/")
        self.assertNotContains(response, f"window.location.href='{reverse('documents:search')}'")
        self.assertNotContains(response, f"window.location.href='{reverse('contracts:search')}'")
        self.assertNotContains(response, f"window.location.href='{reverse('documents:upload_step1')}'")
        self.assertNotContains(response, f"window.location.href='{reverse('contracts:upload_step1')}'")
        self.assertNotContains(response, "電子決裁の検索・閲覧・変更画面はスコープ外です")

    def test_search_eapproval_button_shown_when_department_setting_on(self):
        """電子決裁は実画面が無くdisabled固定だが、ボタンの表示/非表示自体は文書・契約書と
        同じくshow_search_eapprovalに連動する（以前は連動が漏れて常時表示されていた）。"""
        MenuItemSetting.objects.create(department=self.department, show_search_eapproval=True)
        response = self.client.get("/")
        self.assertContains(response, "電子決裁の検索・閲覧・変更画面はスコープ外です")

    def test_search_document_button_shown_when_department_setting_on(self):
        from django.urls import reverse

        MenuItemSetting.objects.create(department=self.department, show_search_document=True)
        response = self.client.get("/")
        self.assertContains(response, f"window.location.href='{reverse('documents:search')}'")
        self.assertNotContains(response, f"window.location.href='{reverse('contracts:search')}'")

    def test_search_contract_button_shown_when_department_setting_on(self):
        from django.urls import reverse

        MenuItemSetting.objects.create(department=self.department, show_search_contract=True)
        response = self.client.get("/")
        self.assertContains(response, f"window.location.href='{reverse('contracts:search')}'")

    def test_storage_document_button_shown_when_department_setting_on(self):
        from django.urls import reverse

        MenuItemSetting.objects.create(department=self.department, show_storage_document=True)
        response = self.client.get("/")
        self.assertContains(response, f"window.location.href='{reverse('documents:upload_step1')}'")

    def test_contract_storage_button_hidden_without_contract_edit_permission_even_if_department_setting_on(self):
        """Rev1.2で追加。部署設定がONでも、契約書-契約書-契約書情報変更がOFF
        （PermissionProfile未設定含む）の職員には保管枠内「契約書」ボタンを表示しない。"""
        from django.urls import reverse

        MenuItemSetting.objects.create(department=self.department, show_storage_contract=True)
        response = self.client.get("/")
        self.assertNotContains(response, f"window.location.href='{reverse('contracts:upload_step1')}'")

    def test_contract_storage_button_hidden_without_department_setting_even_with_contract_edit_permission(self):
        """権限がONでも部署設定がOFF（未設定含む）なら保管枠内「契約書」ボタンを表示しない。"""
        from django.urls import reverse

        PermissionProfile.objects.create(
            employee=self.employee, role=PermissionRole.STAFF, contract_edit=True
        )
        response = self.client.get("/")
        self.assertNotContains(response, f"window.location.href='{reverse('contracts:upload_step1')}'")

    def test_contract_storage_button_shown_with_both_department_setting_and_contract_edit_permission(self):
        from django.urls import reverse

        MenuItemSetting.objects.create(department=self.department, show_storage_contract=True)
        PermissionProfile.objects.create(
            employee=self.employee, role=PermissionRole.STAFF, contract_edit=True
        )
        response = self.client.get("/")
        self.assertContains(response, f"window.location.href='{reverse('contracts:upload_step1')}'")


class SettingsMenuVisibilityTests(TestCase):
    """screen-settingsのボタン表示/非表示（xlsx 設定メニュー!B31、詳細はB46以降の埋め込み画像の表）。
    システム権限（管理者/所属長/一般）ごとに表示してよいボタンが異なる。
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

    def test_admin_sees_all_buttons(self):
        PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.ADMIN)
        response = self.client.get("/settings/")
        for label in ["職員マスタ", "部署管理", "権限管理", "分類管理", "カテゴリー管理",
                      "電子決裁管理", "通知管理", "保存期間設定", "項目管理", "操作履歴ログ", "その他設定"]:
            self.assertContains(response, f">{label}<")

    def test_manager_sees_only_manager_level_buttons(self):
        PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.MANAGER)
        response = self.client.get("/settings/")
        for label in ["権限管理", "分類管理", "カテゴリー管理", "その他設定"]:
            self.assertContains(response, f">{label}<")
        for label in ["職員マスタ", "部署管理", "電子決裁管理", "通知管理", "保存期間設定", "項目管理", "操作履歴ログ"]:
            self.assertNotContains(response, f">{label}<")

    def test_staff_sees_only_staff_level_buttons(self):
        PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.STAFF)
        response = self.client.get("/settings/")
        for label in ["カテゴリー管理", "その他設定"]:
            self.assertContains(response, f">{label}<")
        for label in ["職員マスタ", "部署管理", "権限管理", "分類管理",
                      "電子決裁管理", "通知管理", "保存期間設定", "項目管理", "操作履歴ログ"]:
            self.assertNotContains(response, f">{label}<")

    def test_no_profile_defaults_to_staff_level(self):
        """PermissionProfile未作成の職員はget_role()でSTAFF扱いになる（permissions.services.get_role）。"""
        response = self.client.get("/settings/")
        self.assertContains(response, ">カテゴリー管理<")
        self.assertNotContains(response, ">職員マスタ<")


class SanitizeCsvCellTests(TestCase):
    """core.csv_services（audit/accounts/permissionsのCSV出力共通。Excel等で開いた際の
    数式インジェクション対策、2026-08-24追加）。"""

    def test_formula_prefix_is_escaped(self):
        for prefix in ("=", "+", "-", "@", "\t", "\r"):
            with self.subTest(prefix=prefix):
                self.assertEqual(sanitize_csv_cell(f"{prefix}cmd|'/c calc'!A1"), f"'{prefix}cmd|'/c calc'!A1")

    def test_normal_text_is_unchanged(self):
        self.assertEqual(sanitize_csv_cell("テスト太郎"), "テスト太郎")

    def test_non_string_value_is_unchanged(self):
        self.assertEqual(sanitize_csv_cell(1), 1)

    def test_empty_string_is_unchanged(self):
        self.assertEqual(sanitize_csv_cell(""), "")

    def test_sanitize_csv_row_applies_to_each_cell(self):
        self.assertEqual(sanitize_csv_row(["=SUM(A1)", "通常値", 3]), ["'=SUM(A1)", "通常値", 3])


class NoticeCountsTests(TestCase):
    """screen-menuの「お知らせ」3件（xlsx メイン画面!C42-46）。"""

    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.employee = Employee.objects.create_user(
            employee_no="1", name="テスト太郎", password="x",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        self.group = Group.objects.create(code="A", name="分類Ａ", doc_kbn=DocKbn.DOCUMENT)
        self.category = Category.objects.create(
            code="001", name="カテゴリーＡ", group=self.group, doc_kbn=DocKbn.DOCUMENT
        )
        self.retention_period = RetentionPeriod.objects.create(
            kbn=RetentionKbn.DOCUMENT, period_value=1, period_unit=RetentionPeriodUnit.YEAR, display_order=1
        )

    def _create_document(self, expiry_date, is_deleted=False, deleted_at=None):
        from documents.models import Document

        doc = Document(
            title="テスト", department=self.department, group=self.group, category=self.category,
            year=2026, retention_period=self.retention_period, uploader=self.employee,
            expiry_date=expiry_date, is_deleted=is_deleted, deleted_at=deleted_at,
        )
        doc.file.save("test.pdf", ContentFile(b"dummy"), save=False)
        doc.save()
        return doc

    def _create_contract(self, expiry_date, is_deleted=False, deleted_at=None):
        from contracts.models import Contract

        contract = Contract(
            title="テスト契約書", department=self.department, group=self.group, category=self.category,
            year=2026, uploader=self.employee,
            expiry_date=expiry_date, is_deleted=is_deleted, deleted_at=deleted_at,
        )
        contract.file.save("test.pdf", ContentFile(b"dummy"), save=False)
        contract.save()
        return contract

    def test_expired_document_counted(self):
        today = timezone.localdate()
        self._create_document(expiry_date=today - datetime.timedelta(days=1))
        counts = get_notice_counts(self.employee)
        self.assertEqual(counts.expired_documents, 1)
        self.assertEqual(counts.expiring_soon_documents, 0)

    def test_expiring_soon_within_threshold_counted(self):
        today = timezone.localdate()
        self._create_document(expiry_date=today + datetime.timedelta(days=5))
        counts = get_notice_counts(self.employee)
        self.assertEqual(counts.expiring_soon_documents, 1)

    def test_expiring_far_in_future_not_counted(self):
        today = timezone.localdate()
        self._create_document(expiry_date=today + datetime.timedelta(days=400))
        counts = get_notice_counts(self.employee)
        self.assertEqual(counts.expiring_soon_documents, 0)

    def test_recently_deleted_counted(self):
        now = timezone.now()
        self._create_document(
            expiry_date=timezone.localdate() + datetime.timedelta(days=100),
            is_deleted=True,
            deleted_at=now,
        )
        counts = get_notice_counts(self.employee)
        self.assertEqual(counts.recently_deleted_documents, 1)

    def test_other_department_document_not_counted_for_staff(self):
        """一般職員（`can_select_department`がFalse）は自部署以外の文書がカウントされない
        ことを確認する（お知らせのバッジ件数と検索結果件数を一致させるための絞り込み）。"""
        other_department = Department.objects.create(
            branch_code="999", branch_name="他支店", section_code="09", section_name="他部署"
        )
        today = timezone.localdate()
        other_doc = self._create_document(expiry_date=today - datetime.timedelta(days=1))
        other_doc.department = other_department
        other_doc.save()
        counts = get_notice_counts(self.employee)
        self.assertEqual(counts.expired_documents, 0)

    @override_settings(NOTICE_EXPIRING_THRESHOLD_MONTHS=6, NOTICE_DELETED_THRESHOLD_MONTHS=1)
    def test_expiring_and_deleted_thresholds_are_independent(self):
        """xlsx メイン画面!B36/B38は別々の設定値。2026-08-13以前は`SystemSetting.
        notice_threshold_months`1つを両方が共有していたため、片方だけ変更する運用に対応できなかった
        （settings.NOTICE_EXPIRING_THRESHOLD_MONTHS/NOTICE_DELETED_THRESHOLD_MONTHSへ分離）。"""
        today = timezone.localdate()
        # 5ヶ月後失効：EXPIRING側のしきい値(6ヶ月)には収まるが、DELETED側のしきい値(1ヶ月)を
        # そのまま誤って流用していたら収まらないはずの期間。
        self._create_document(expiry_date=today + datetime.timedelta(days=150))
        # 3ヶ月前に削除：DELETED側のしきい値(1ヶ月)には収まらないが、EXPIRING側のしきい値(6ヶ月)を
        # そのまま誤って流用していたら収まってしまうはずの期間。
        self._create_document(
            expiry_date=today + datetime.timedelta(days=200),
            is_deleted=True,
            deleted_at=timezone.now() - datetime.timedelta(days=90),
        )
        counts = get_notice_counts(self.employee)
        self.assertEqual(counts.expiring_soon_documents, 1)
        self.assertEqual(counts.recently_deleted_documents, 0)

    def test_other_department_document_counted_when_in_view_scope(self):
        """documents/search_services.pyの非管理者向け部署フィルタと同じvisible_department_ids()を
        使うよう修正した（2026-08-24）。閲覧部署範囲テーブル〈部署統合・分割〉に登録された他部署の
        文書も、検索画面と同様にお知らせバッジへ計上されることを確認する。"""
        other_department = Department.objects.create(
            branch_code="999", branch_name="他支店", section_code="09", section_name="他部署"
        )
        DepartmentViewScope.objects.create(
            viewer_department=self.department, visible_department=other_department
        )
        today = timezone.localdate()
        other_doc = self._create_document(expiry_date=today - datetime.timedelta(days=1))
        other_doc.department = other_department
        other_doc.save()
        counts = get_notice_counts(self.employee)
        self.assertEqual(counts.expired_documents, 1)

    def test_contract_counted_independently_of_document(self):
        """Rev1.2（xlsx メイン画面!C42-46「文書、契約書」）で契約書も集計対象になったことを確認する。"""
        today = timezone.localdate()
        self._create_document(expiry_date=today - datetime.timedelta(days=1))
        self._create_contract(expiry_date=today - datetime.timedelta(days=1))
        counts = get_notice_counts(self.employee)
        self.assertEqual(counts.expired_documents, 1)
        self.assertEqual(counts.expired_contracts, 1)

    def test_contract_expiring_soon_and_recently_deleted_counted(self):
        """test_contract_counted_independently_of_documentはexpired_contractsのみ確認しており、
        契約書側のexpiring_soon_contracts/recently_deleted_contractsは一度も検証されていなかった
        （テストカバレッジ棚卸しで発見、2026-08-26追加）。"""
        today = timezone.localdate()
        self._create_contract(expiry_date=today + datetime.timedelta(days=5))
        self._create_contract(
            expiry_date=today + datetime.timedelta(days=100),
            is_deleted=True,
            deleted_at=timezone.now(),
        )
        counts = get_notice_counts(self.employee)
        self.assertEqual(counts.expiring_soon_contracts, 1)
        self.assertEqual(counts.recently_deleted_contracts, 1)

    def test_other_department_contract_not_counted_for_staff(self):
        """documents側のtest_other_department_document_not_counted_for_staffに対応する契約書側の
        部署スコープ確認（permissions.services.contract_searchable_department_ids）。
        配線自体が一度も確認されていなかった（テストカバレッジ棚卸しで発見、2026-08-26追加）。"""
        other_department = Department.objects.create(
            branch_code="999", branch_name="他支店", section_code="09", section_name="他部署"
        )
        today = timezone.localdate()
        other_contract = self._create_contract(expiry_date=today - datetime.timedelta(days=1))
        other_contract.department = other_department
        other_contract.save()
        counts = get_notice_counts(self.employee)
        self.assertEqual(counts.expired_contracts, 0)

    def test_other_department_contract_counted_when_in_view_scope(self):
        """[review_test_audit_core.txt No.11] 文書側の
        test_other_department_document_counted_when_in_view_scope に対応する契約書側の正の分岐。
        契約書お知らせ集計も permissions.services.contract_searchable_department_ids() 経由で
        閲覧部署範囲テーブル（部署統合・分割）の他部署を計上する（負の分岐＝
        test_other_department_contract_not_counted_for_staff だけでは片肺だった）。"""
        other_department = Department.objects.create(
            branch_code="998", branch_name="別支店", section_code="08", section_name="別部署"
        )
        DepartmentViewScope.objects.create(
            viewer_department=self.department, visible_department=other_department
        )
        today = timezone.localdate()
        other_contract = self._create_contract(expiry_date=today - datetime.timedelta(days=1))
        other_contract.department = other_department
        other_contract.save()
        counts = get_notice_counts(self.employee)
        self.assertEqual(counts.expired_contracts, 1)

    def test_expiry_and_deletion_boundary_days_belong_to_inclusive_side(self):
        """[review_test_audit_core.txt No.12] _expiry_counts の「境界当日」の帰属を固定する。
        expiry_date == today は expired ではなく expiring_soon 側（Q は expiry_date__lt=today と
        expiry_date__gte=today）、expiry_date == soon_limit ちょうどは expiring_soon に含まれる
        （__lte）、deleted_at の日付 == deleted_since ちょうどは recently_deleted に含まれる
        （__date__gte）。お知らせ件数と検索結果件数の一致という設計目標に直結する off-by-one。"""
        today = timezone.localdate()
        soon_limit = add_months(today, settings.NOTICE_EXPIRING_THRESHOLD_MONTHS)
        deleted_since = add_months(today, -settings.NOTICE_DELETED_THRESHOLD_MONTHS)

        self._create_document(expiry_date=today)  # 当日 → expiring_soon
        self._create_document(expiry_date=soon_limit)  # 上限ちょうど → expiring_soon
        self._create_document(
            expiry_date=today + datetime.timedelta(days=100),
            is_deleted=True,
            deleted_at=timezone.make_aware(
                datetime.datetime.combine(deleted_since, datetime.time(12, 0))
            ),
        )  # 削除下限ちょうど → recently_deleted

        counts = get_notice_counts(self.employee)
        self.assertEqual(counts.expired_documents, 0)
        self.assertEqual(counts.expiring_soon_documents, 2)
        self.assertEqual(counts.recently_deleted_documents, 1)


@override_settings(NOTICE_DELETED_THRESHOLD_MONTHS=1)
class PurgeExpiredDeletedRecordsCommandTests(TestCase):
    """core.management.commands.purge_expired_deleted_records（Rev1.2、2026-08-24追加）。
    xlsx メイン画面!B50-51「"直近Xヵ月"で設定されているXヵ月が既に経過している文書、契約書は
    自動的に物理削除を行うこと」に対応する日次バッチ。
    """

    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.employee = Employee.objects.create_user(
            employee_no="1", name="テスト太郎", password="x",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        self.group = Group.objects.create(code="A", name="分類Ａ", doc_kbn=DocKbn.DOCUMENT)
        self.category = Category.objects.create(
            code="001", name="カテゴリーＡ", group=self.group, doc_kbn=DocKbn.DOCUMENT
        )
        self.retention_period = RetentionPeriod.objects.create(
            kbn=RetentionKbn.DOCUMENT, period_value=1, period_unit=RetentionPeriodUnit.YEAR, display_order=1
        )

    def _create_document(self, deleted_at):
        from documents.models import Document

        doc = Document(
            title="テスト", department=self.department, group=self.group, category=self.category,
            year=2026, retention_period=self.retention_period, uploader=self.employee,
            expiry_date=timezone.localdate() + datetime.timedelta(days=100),
            is_deleted=True, deleted_at=deleted_at,
        )
        doc.file.save("test.pdf", ContentFile(b"dummy"), save=False)
        doc.save()
        return doc

    def _create_contract(self, deleted_at=None, code="C1"):
        from contracts.models import Contract

        contract_group = Group.objects.create(code=code, name="契約分類", doc_kbn=DocKbn.CONTRACT)
        contract_category = Category.objects.create(
            code=f"{code}01", name="契約カテゴリー", group=contract_group, doc_kbn=DocKbn.CONTRACT
        )
        contract = Contract(
            title="テスト契約書", department=self.department, group=contract_group, category=contract_category,
            year=2026, uploader=self.employee,
            expiry_date=timezone.localdate() + datetime.timedelta(days=100),
            is_deleted=deleted_at is not None, deleted_at=deleted_at,
        )
        contract.file.save("test.pdf", ContentFile(b"dummy"), save=False)
        contract.save()
        return contract

    def test_document_past_threshold_is_purged(self):
        from documents.models import Document

        old_doc = self._create_document(deleted_at=timezone.now() - datetime.timedelta(days=40))
        file_name = old_doc.file.name

        call_command("purge_expired_deleted_records")

        self.assertFalse(Document.objects.filter(pk=old_doc.pk).exists())
        self.assertFalse(old_doc.file.storage.exists(file_name))

    def test_document_within_threshold_survives(self):
        from documents.models import Document

        recent_doc = self._create_document(deleted_at=timezone.now() - datetime.timedelta(days=5))

        call_command("purge_expired_deleted_records")

        self.assertTrue(Document.objects.filter(pk=recent_doc.pk).exists())

    def test_non_deleted_document_never_purged(self):
        """is_deleted=Falseの文書は対象外（deleted_atも通常Noneのため対象になりようがないが、
        念のためqueryset自体の条件を確認する）。"""
        from documents.models import Document

        old_doc = self._create_document(deleted_at=timezone.now() - datetime.timedelta(days=40))
        old_doc.is_deleted = False
        old_doc.save(update_fields=["is_deleted"])

        call_command("purge_expired_deleted_records")

        self.assertTrue(Document.objects.filter(pk=old_doc.pk).exists())

    def test_contract_past_threshold_is_purged(self):
        from contracts.models import Contract

        old_contract = self._create_contract(deleted_at=timezone.now() - datetime.timedelta(days=40))
        file_name = old_contract.file.name

        call_command("purge_expired_deleted_records")

        self.assertFalse(Contract.objects.filter(pk=old_contract.pk).exists())
        self.assertFalse(old_contract.file.storage.exists(file_name))

    def test_contract_relation_rows_purged_with_contract(self):
        """Rev1.6：関連書類は既存契約書への参照（ContractRelation）。purgeで契約書本体が物理削除
        されると、その契約書が contract 側でも related_contract 側でも参照している関連行が
        on_delete=CASCADE で一緒に消える。"""
        from contracts.models import Contract, ContractRelation

        old_contract = self._create_contract(deleted_at=timezone.now() - datetime.timedelta(days=40))
        other = self._create_contract(code="C2")
        ContractRelation.objects.create(contract=old_contract, related_contract=other, display_order=0)
        ContractRelation.objects.create(contract=other, related_contract=old_contract, display_order=0)

        call_command("purge_expired_deleted_records")

        self.assertFalse(Contract.objects.filter(pk=old_contract.pk).exists())
        self.assertTrue(Contract.objects.filter(pk=other.pk).exists())
        self.assertFalse(ContractRelation.objects.filter(contract=old_contract).exists())
        self.assertFalse(ContractRelation.objects.filter(related_contract=old_contract).exists())

    def test_document_purge_creates_audit_log(self):
        """廃止されたdocuments.views.DeleteViewの完全削除ログ（action="検索・閲覧画面 完全削除"）を
        引き続き本バッチでも記録することを確認する（CLAUDE.md「監査が必要なイベント...は一元的な
        記録機構（auditアプリ）を通す」、2026-08-24修正）。"""
        old_doc = self._create_document(deleted_at=timezone.now() - datetime.timedelta(days=40))
        title = old_doc.title

        call_command("purge_expired_deleted_records")

        log = AuditLog.objects.get(action="物理削除バッチ　完全削除", event_message__contains=title)
        self.assertIn(title, log.event_message)

    def test_contract_purge_creates_audit_log(self):
        old_contract = self._create_contract(deleted_at=timezone.now() - datetime.timedelta(days=40))
        title = old_contract.title

        call_command("purge_expired_deleted_records")

        log = AuditLog.objects.get(action="物理削除バッチ　完全削除", event_message__contains=title)
        self.assertIn(title, log.event_message)

    def test_purge_audit_log_propagates_document_privacy_flag(self):
        """[review_test_audit_core.txt No.2] purge_expired_deleted_records は監査ログの
        personal_info_flag に文書の privacy_flag を伝播させる（`_purge` の
        `personal_info_flag_fn=lambda obj: obj.privacy_flag`）。個人情報書類フラグは操作履歴ログ
        画面・CSV の抽出条件（personal_info_flag 検索）に直結するため、伝播が切れても気付ける
        よう固定する。契約書は privacy_flag 自体が無いため常に False（対比）。"""
        from documents.models import Document

        private_doc = self._create_document(deleted_at=timezone.now() - datetime.timedelta(days=40))
        Document.objects.filter(pk=private_doc.pk).update(title="個人情報書類", privacy_flag=True)
        plain_doc = self._create_document(deleted_at=timezone.now() - datetime.timedelta(days=40))
        Document.objects.filter(pk=plain_doc.pk).update(title="通常書類", privacy_flag=False)
        self._create_contract(deleted_at=timezone.now() - datetime.timedelta(days=40))

        call_command("purge_expired_deleted_records")

        self.assertTrue(
            AuditLog.objects.get(
                action="物理削除バッチ　完全削除", event_message__contains="個人情報書類"
            ).personal_info_flag
        )
        self.assertFalse(
            AuditLog.objects.get(
                action="物理削除バッチ　完全削除", event_message__contains="通常書類"
            ).personal_info_flag
        )
        self.assertFalse(
            AuditLog.objects.get(
                action="物理削除バッチ　完全削除", event_message__contains="テスト契約書"
            ).personal_info_flag
        )

    def test_document_file_deletion_failure_logs_real_pk(self):
        """document.delete()成功後はDjangoがpkをNoneにリセットするため、ファイル実体削除の失敗ログに
        削除前のpkを使うよう修正した（2026-08-24。修正前はpk=Noneでログに残り追跡不能だった）。"""
        old_doc = self._create_document(deleted_at=timezone.now() - datetime.timedelta(days=40))
        doc_pk = old_doc.pk

        with self.assertLogs("core.management.commands.purge_expired_deleted_records", level="ERROR") as cm:
            with patch(
                "django.db.models.fields.files.FieldFile.delete", side_effect=OSError("simulated storage error")
            ):
                call_command("purge_expired_deleted_records")

        self.assertTrue(any(f" pk={doc_pk}" in message for message in cm.output))
        self.assertFalse(any(" pk=None" in message for message in cm.output))

    def test_one_delete_failure_does_not_stop_purge_of_other_records(self):
        """[review_test_audit_core.txt No.6] `_purge` が「バルク delete() にせず1件ずつ
        delete する」設計判断そのものの回帰テスト。1件の obj.delete() が DBError を投げても
        (a) その1件だけ failed に計上して残り、(b) 後続の正常な対象は purge され続け、
        (c) stdout に「失敗1件」が出る。ここが壊れるとゴミ箱の1件の異常でゴミ箱全体の自動物理
        削除が止まる（xlsx メイン画面!B50-51 の要件が満たせなくなる）。"""
        from io import StringIO

        from django.db import Error as DBError
        from documents.models import Document

        docs = [
            self._create_document(deleted_at=timezone.now() - datetime.timedelta(days=40))
            for _ in range(3)
        ]
        Document.objects.filter(pk=docs[0].pk).update(title="削除失敗する文書")
        Document.objects.filter(pk=docs[1].pk).update(title="正常文書1")
        Document.objects.filter(pk=docs[2].pk).update(title="正常文書2")

        original_delete = Document.delete

        def flaky_delete(inner_self, *args, **kwargs):
            if inner_self.title == "削除失敗する文書":
                raise DBError("simulated constraint violation")
            return original_delete(inner_self, *args, **kwargs)

        out = StringIO()
        with patch.object(Document, "delete", flaky_delete):
            call_command("purge_expired_deleted_records", stdout=out)

        # (a) 失敗した1件は残る
        self.assertTrue(Document.objects.filter(pk=docs[0].pk).exists())
        # (b) 後続の正常な2件は物理削除される
        self.assertFalse(Document.objects.filter(pk=docs[1].pk).exists())
        self.assertFalse(Document.objects.filter(pk=docs[2].pk).exists())
        # (c) stdout の「失敗N件」表記
        self.assertIn("文書2件（失敗1件）", out.getvalue())
        # 失敗した1件は監査ログも残さない（delete 前に continue するため）
        self.assertFalse(
            AuditLog.objects.filter(
                action="物理削除バッチ　完全削除", event_message__contains="削除失敗する文書"
            ).exists()
        )

    def test_purge_removes_ocr_textdata_with_the_record(self):
        """ocr_textdata は DB カラムのため obj.delete() で自動的に消える（旧 searchable_file の
        副ファイル削除分岐は 2026-09-11 に廃止＝監査 案3）。原本ファイルのみ実体削除する。"""
        from documents.models import Document

        doc = self._create_document(deleted_at=timezone.now() - datetime.timedelta(days=40))
        doc.ocr_textdata = [{"page": 1, "w": 800, "h": 1100, "lines": [[1, 1, 2, 2, "x"]]}]
        doc.save(update_fields=["ocr_textdata"])
        file_name = doc.file.name
        storage = doc.file.storage

        call_command("purge_expired_deleted_records")

        self.assertFalse(Document.objects.filter(pk=doc.pk).exists())
        self.assertFalse(storage.exists(file_name))


class AddMonthsClampTests(TestCase):
    """core.notice_services.add_monthsの月末日クランプ（`min(base.day, _days_in_month(...))`）は
    NoticeCountsTests内で日数加減算の副次的な結果として間接的に実行されてはいるが、月末日や
    うるう年を跨ぐ入力を使ったテストが無く実質無検証だった（テストカバレッジ棚卸しで発見、
    2026-08-26追加）。"""

    def test_month_end_clamps_to_shorter_month(self):
        # 1/31の1ヶ月後は2/31が存在しないため、2月の最終日(28日、平年)にクランプされる。
        self.assertEqual(add_months(datetime.date(2026, 1, 31), 1), datetime.date(2026, 2, 28))

    def test_leap_year_february_clamps_to_29(self):
        self.assertEqual(add_months(datetime.date(2024, 1, 31), 1), datetime.date(2024, 2, 29))

    def test_non_leap_year_february_clamps_to_28(self):
        self.assertEqual(add_months(datetime.date(2025, 1, 31), 1), datetime.date(2025, 2, 28))

    def test_year_boundary_crossed_correctly(self):
        self.assertEqual(add_months(datetime.date(2026, 12, 15), 2), datetime.date(2027, 2, 15))

    def test_negative_months_cross_year_boundary(self):
        """[review_test_audit_core.txt No.4] audit.services.retention_cutoff_date /
        purge_expired_deleted_records / *.search_services._apply_notice_filter はいずれも負の
        months で add_months を呼ぶ（例: 1月起点で -3 ヶ月 → 前年10月）。既存ケースは正の months
        のみで、`month_index` が負のときの `year + month_index // 12`（フロア除算）・
        `month_index % 12 + 1` の年跨ぎが直接検証されていなかった。保持期間・自動物理削除の
        起点日という重要な値の計算式のため固定する。"""
        # 単純な年跨ぎ（前年へ）。
        self.assertEqual(add_months(datetime.date(2026, 1, 15), -3), datetime.date(2025, 10, 15))
        # ちょうど1月 → 前年12月（month_index=-1、% 12 が 11 になる境界）。
        self.assertEqual(add_months(datetime.date(2026, 1, 20), -1), datetime.date(2025, 12, 20))
        # 12ヶ月を超える負値（複数年戻る）＋月末日クランプの併用。
        self.assertEqual(add_months(datetime.date(2026, 1, 31), -14), datetime.date(2024, 11, 30))


class IsExpiringSoonTests(TestCase):
    """popup-detail「まもなく有効期限（更新月）」バナー用の判定（原本index.html:1146に対応する
    実データ上の状態。原本フィデリティ監査で発見・新設）。"""

    def test_already_expired_is_not_expiring_soon(self):
        today = timezone.localdate()
        self.assertFalse(is_expiring_soon(today - datetime.timedelta(days=1)))

    def test_within_threshold_is_expiring_soon(self):
        today = timezone.localdate()
        self.assertTrue(is_expiring_soon(today + datetime.timedelta(days=5)))

    def test_far_future_is_not_expiring_soon(self):
        today = timezone.localdate()
        self.assertFalse(is_expiring_soon(today + datetime.timedelta(days=400)))

    def test_threshold_boundary_day_is_expiring_soon(self):
        """[review_test_audit_core.txt No.12] is_expiring_soon の閾値ちょうど
        （expiry_date == add_months(today, NOTICE_EXPIRING_THRESHOLD_MONTHS)）は境界を含む（`<=`）。
        当日（まだ期限切れではない）も expiring_soon 側。既存ケースは境界から日数が離れた値のみ。"""
        today = timezone.localdate()
        self.assertTrue(
            is_expiring_soon(add_months(today, settings.NOTICE_EXPIRING_THRESHOLD_MONTHS))
        )
        self.assertTrue(is_expiring_soon(today))


class SessionIdleTimeoutMiddlewareTests(TestCase):
    """core.middleware.SessionIdleTimeoutMiddleware（自動ログアウト本体）。設定値の保存
    （LogoutTimeForm経由）はOtherMainEditViewTests等でカバーされているが、保存された値が
    実際にリクエスト処理でログアウトを引き起こすかというミドルウェア自身のロジックは
    一切テストされていなかった（テストカバレッジ棚卸しで発見、2026-08-26追加）。
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

    def test_idle_over_configured_timeout_logs_out_user(self):
        SystemSetting.objects.create(pk=1, session_idle_timeout_minutes=1)
        session = self.client.session
        session[SESSION_LAST_ACTIVITY_KEY] = time.time() - 120
        session.save()
        response = self.client.get("/", follow=True)
        self.assertRedirects(response, "/accounts/login/?next=/")

    def test_idle_within_configured_timeout_keeps_session_active(self):
        SystemSetting.objects.create(pk=1, session_idle_timeout_minutes=60)
        session = self.client.session
        session[SESSION_LAST_ACTIVITY_KEY] = time.time() - 10
        session.save()
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)

    @override_settings(SESSION_IDLE_TIMEOUT_MINUTES=1)
    def test_no_system_setting_falls_back_to_settings_value(self):
        # SystemSettingを1件も作らないことで、_get_timeout_minutes()のフォールバック
        # （SystemSetting.objects.first()がNoneの場合にsettings.SESSION_IDLE_TIMEOUT_MINUTESを
        # 使う分岐）を狙って通す。
        session = self.client.session
        session[SESSION_LAST_ACTIVITY_KEY] = time.time() - 120
        session.save()
        response = self.client.get("/", follow=True)
        self.assertRedirects(response, "/accounts/login/?next=/")

    @override_settings(SESSION_IDLE_TIMEOUT_MINUTES=1)
    def test_database_error_on_query_falls_back_to_settings_value(self):
        """[review_test_audit_core.txt No.13] SystemSetting.objects.first() のクエリ自体が
        DatabaseError を投げたとき settings.SESSION_IDLE_TIMEOUT_MINUTES にフォールバックする分岐
        （2026-09-10 1e4f528 で `except Exception` → `except DatabaseError` に限定）。
        test_no_system_setting_falls_back_to_settings_value は「レコード0件」の別分岐で、
        こちらは例外種別を絞った直後の握りつぶし範囲の回帰を検知する。"""
        session = self.client.session
        session[SESSION_LAST_ACTIVITY_KEY] = time.time() - 120
        session.save()
        with self.assertLogs("core.middleware", level="ERROR") as cm:
            with patch(
                "masters.models.SystemSetting.objects.first",
                side_effect=DatabaseError("connection lost"),
            ):
                response = self.client.get("/", follow=True)
        self.assertRedirects(response, "/accounts/login/?next=/")
        self.assertTrue(any("既定値にフォールバック" in message for message in cm.output))


class OtherSettingsRoutingTests(TestCase):
    """xlsx その他設定シート: 権限（管理者のみ／管理者以外）で表示内容を振り分ける。
    原本のデモ用ログインID分岐(`login-user`が"2"/"3"か)を実際のPermissionRoleに置き換えている。
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

    def test_admin_sees_main_settings(self):
        PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.ADMIN)
        response = self.client.get("/settings/other/")
        self.assertContains(response, "メイン画面項目")

    def test_staff_sees_password_change(self):
        PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.STAFF)
        response = self.client.get("/settings/other/")
        self.assertContains(response, "変更後パスワード")

    def test_no_profile_defaults_to_password_change(self):
        response = self.client.get("/settings/other/")
        self.assertContains(response, "変更後パスワード")

    def test_password_change_has_no_current_password_row(self):
        """Rev1.5(原本html6)で「現在のパスワード」行がパスワード変更画面から削除された。
        「変更後パスワードが現在のものと同一ならエラー」の検証は残る（下記
        test_password_change_rejects_same_as_current）。"""
        response = self.client.get("/settings/other/")
        self.assertNotContains(response, "現在のパスワード")

    def test_password_change_fields_have_reveal_toggle(self):
        """変更後パスワード／確認欄に打ち間違い確認用の 👁️ トグルを付ける（ログイン画面・
        職員マスタ編集と同じ挙動。原本html6には無いがChrome/Firefoxにネイティブreveal機能が
        無いための独自追加。差異一覧xlsx シート4 No.6）。"""
        response = self.client.get("/settings/other/")
        self.assertContains(response, 'data-target="id_new_password"')
        self.assertContains(response, 'data-target="id_new_password_confirm"')

    def test_staff_cannot_access_main_edit(self):
        department2 = Department.objects.create(
            branch_code="999", branch_name="別支店", section_code="", section_name=""
        )
        PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.STAFF)
        response = self.client.get(f"/settings/other/main/{department2.pk}/edit/")
        self.assertEqual(response.status_code, 403)

    def test_staff_cannot_access_logout_edit(self):
        PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.STAFF)
        response = self.client.get("/settings/other/logout/edit/")
        self.assertEqual(response.status_code, 403)

    def test_password_change_requires_matching_confirmation(self):
        response = self.client.get("/settings/other/")
        token = response.context["token"]
        response2 = self.client.post(
            "/settings/other/",
            {"new_password": "newpass1", "new_password_confirm": "different", "token": token},
        )
        self.assertContains(response2, "一致しません")
        self.employee.refresh_from_db()
        self.assertTrue(self.employee.check_password("pass1234"))

    def test_password_change_rejects_short_or_symbol_password(self):
        """xlsx その他設定!B152(Rev1.1)「半角英数6桁以上とする。記号、全角文字が含まれる場合は
        更新時にエラーとする。」"""
        response = self.client.get("/settings/other/")
        token = response.context["token"]
        response2 = self.client.post(
            "/settings/other/",
            {"new_password": "ab1", "new_password_confirm": "ab1", "token": token},
        )
        self.assertContains(response2, "半角英数6桁以上")

        response = self.client.get("/settings/other/")
        token = response.context["token"]
        response3 = self.client.post(
            "/settings/other/",
            {"new_password": "abc12!", "new_password_confirm": "abc12!", "token": token},
        )
        self.assertContains(response3, "半角英数6桁以上")

        # 全角文字が含まれるケース（B152「全角文字が含まれる場合は…エラー」）。
        response = self.client.get("/settings/other/")
        token = response.context["token"]
        response4 = self.client.post(
            "/settings/other/",
            {"new_password": "ａｂｃ１２３", "new_password_confirm": "ａｂｃ１２３", "token": token},
        )
        self.assertContains(response4, "半角英数6桁以上")

        self.employee.refresh_from_db()
        self.assertTrue(self.employee.check_password("pass1234"))

    def test_password_change_rejects_same_as_current(self):
        """xlsx その他設定!B149-150(Rev1.1)「現在のパスワードと同一の場合は更新時にエラーとする」。"""
        response = self.client.get("/settings/other/")
        token = response.context["token"]
        response2 = self.client.post(
            "/settings/other/",
            {"new_password": "pass1234", "new_password_confirm": "pass1234", "token": token},
        )
        self.assertContains(response2, "現在のパスワードと同じ")

    def test_password_change_creates_audit_log(self):
        """原本index.html:3225の操作履歴ログサンプル「パスワード　更新」に対応
        （原本フィデリティ監査で発見：以前は一切記録されていなかった）。"""
        response = self.client.get("/settings/other/")
        token = response.context["token"]
        self.client.post(
            "/settings/other/",
            {"new_password": "newpass123", "new_password_confirm": "newpass123", "token": token},
        )
        self.assertTrue(AuditLog.objects.filter(action="パスワード　更新", employee_no="1").exists())


class OtherMainListPaginationTests(TestCase):
    """screen-other-main一覧のページャーが実際に機能することを確認（原本フィデリティ監査で発見：
    以前は部署数に関わらず常に1ページ固定・次へ/前へdisabledの静的ページャーで、Django Paginator
    が未実装だった。他の一覧画面〈分類管理・カテゴリー管理・操作履歴ログ等〉との一貫性のため
    PAGE_SIZE=100で追加、Rev1.1で50→100件に変更）。"""

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
        # 既存の1件と合わせて101件にし、1ページ100件の境界を超えさせる。
        for i in range(100):
            Department.objects.create(
                branch_code=f"{i:03d}", branch_name=f"支店{i}", section_code="", section_name="",
            )

    def test_second_page_has_remaining_department(self):
        response = self.client.get("/settings/other/")
        self.assertEqual(response.context["page_obj"].paginator.num_pages, 2)
        response2 = self.client.get("/settings/other/?page=2")
        self.assertEqual(len(response2.context["page_obj"]), 1)

    def test_row_number_continues_across_pages(self):
        response2 = self.client.get("/settings/other/?page=2")
        self.assertIn(">101<", response2.content.decode())


class OtherMainEditViewTests(TestCase):
    """screen-other-main-edit「No.」欄は一覧(other_main.html)と同じ表示順を示す必要がある
    （原本フィデリティ監査で発見：以前はdepartment.pkをそのまま表示しており、一覧の行番号と
    食い違っていた）。"""

    def setUp(self):
        # branch_code降順で作成することで、作成順(pk順)と一覧の並び順(branch_code順)を
        # わざとずらし、No.計算がpkの丸写しになっていないことを検証できるようにする。
        self.dept_b = Department.objects.create(
            branch_code="999", branch_name="Z支店", section_code="", section_name=""
        )
        self.dept_a = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.employee = Employee.objects.create_user(
            employee_no="1", name="テスト太郎", password="pass1234",
            department=self.dept_a, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.ADMIN)
        self.client.login(username="1", password="pass1234")

    def test_no_reflects_list_display_order_not_pk(self):
        # dept_aはpkが2番目だが、branch_code順では1番目に表示されるべき。
        response = self.client.get(f"/settings/other/main/{self.dept_a.pk}/edit/")
        self.assertEqual(response.context["no"], 1)
        response2 = self.client.get(f"/settings/other/main/{self.dept_b.pk}/edit/")
        self.assertEqual(response2.context["no"], 2)

    def test_main_edit_creates_audit_log(self):
        response = self.client.get(f"/settings/other/main/{self.dept_a.pk}/edit/")
        token = response.context["token"]
        self.client.post(f"/settings/other/main/{self.dept_a.pk}/edit/", {"token": token})
        self.assertTrue(AuditLog.objects.filter(action="メイン画面項目設定　更新").exists())

    def test_logout_edit_creates_audit_log(self):
        response = self.client.get("/settings/other/logout/edit/")
        token = response.context["token"]
        self.client.post("/settings/other/logout/edit/", {"session_idle_timeout_minutes": "30", "token": token})
        self.assertTrue(AuditLog.objects.filter(action="自動ログアウト時間設定　更新").exists())


class DoubleSubmitServicesTests(TestCase):
    """core.double_submit（二重送信対策トークン）の単体テスト。各アプリのtests.pyには
    不正トークン時の失敗分岐（consume_tokenがFalseを返すケース）は多数あるが、本来の目的
    である「正当なトークンの単回使用」（同じトークンでの2回目のconsume_tokenは失敗する＝
    ブラウザの戻る+再送信・二度押しを弾く）自体を検証するテストがどこにも無かった
    （review_test_permissions_accounts.txt X-3、2026-09-18追加）。"""

    def setUp(self):
        self.session = SessionStore()
        self.session.create()

    def test_valid_token_can_only_be_consumed_once(self):
        token = issue_token(self.session, "test_form")
        self.assertTrue(consume_token(self.session, "test_form", token))
        # 同じトークンでの2回目のconsume_token（＝ブラウザの戻る+再送信や二度押し）は失敗する。
        self.assertFalse(consume_token(self.session, "test_form", token))

    def test_reissuing_token_invalidates_the_previous_one(self):
        """同じform_idでissue_tokenを再度呼ぶと（フォームの再表示等）、古いトークンは
        もう使えなくなる（tokens[form_id]が上書きされるため）。"""
        old_token = issue_token(self.session, "test_form")
        new_token = issue_token(self.session, "test_form")
        self.assertNotEqual(old_token, new_token)
        self.assertFalse(consume_token(self.session, "test_form", old_token))
        self.assertTrue(consume_token(self.session, "test_form", new_token))

    def test_concurrent_requests_can_consume_valid_token_only_once(self):
        """TOCTOU対策の検証（ユーザー報告2026-09-28：保管画面２「登録」ボタン連打で500エラー、
        docs/HTML_REIMPL_CHECKLIST_ARCHIVE.md参照）。上のtest_valid_token_can_only_be_consumed_once
        は同じSessionStoreインスタンスへの2回呼び出しのため、1回目のconsume_tokenが
        `del tokens[form_id]`でそのインスタンスのローカル辞書を書き換えた時点で2回目は
        セッション側の比較だけで弾かれてしまい、DB側のユニーク制約（今回追加した
        core.models.ConsumedFormToken）は経由しない。ここでは同じセッションキーを別々の
        SessionStoreインスタンスとして読み込み直す（＝ほぼ同時に届いた2リクエストが、それぞれ
        独立したセッションのスナップショットを持つ状況を模す）ことで、セッション側の比較だけでは
        両方とも「トークンはまだ有効」と判定してしまうケースを再現し、それでも実際に処理を
        継続できるのはどちらか一方だけであることを検証する。"""
        token = issue_token(self.session, "test_form")
        self.session.save()

        session_a = SessionStore(session_key=self.session.session_key)
        session_b = SessionStore(session_key=self.session.session_key)
        # 2つのインスタンスとも、保存済みの同じセッションから独立してトークンを読み込める
        # （＝どちらも「トークンはまだ有効」と判定する前提が成り立つ）ことを確認しておく。
        self.assertEqual(session_a.get("double_submit_tokens", {}).get("test_form"), token)
        self.assertEqual(session_b.get("double_submit_tokens", {}).get("test_form"), token)

        self.assertTrue(consume_token(session_a, "test_form", token))
        self.assertFalse(consume_token(session_b, "test_form", token))


class OtherViewsDoubleSubmitTokenTests(TestCase):
    """organizations/masters/permissions/accountsの各Viewは二重送信対策トークン不正時分岐
    （core.double_submit.consume_tokenがFalseを返すケース）を自アプリのtests.pyで検証済みだが、
    core/views.py自身が唯一の実装元であるOtherSettingsView/OtherMainEditView/
    OtherLogoutEditViewの3画面はどのアプリからも間接カバーされず未検証のまま残っていた
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
        self.client.login(username="1", password="pass1234")

    def test_other_settings_post_with_invalid_token_shows_error_and_does_not_change_password(self):
        PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.STAFF)
        response = self.client.post(
            "/settings/other/",
            {"token": "invalid-token", "new_password": "newpass123", "new_password_confirm": "newpass123"},
            follow=True,
        )
        messages_list = [str(m) for m in response.context["messages"]]
        self.assertTrue(any("二重に送信された可能性" in m for m in messages_list))
        self.employee.refresh_from_db()
        self.assertTrue(self.employee.check_password("pass1234"))

    def test_other_main_edit_post_with_invalid_token_shows_error_and_does_not_save(self):
        PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.ADMIN)
        response = self.client.post(
            f"/settings/other/main/{self.department.pk}/edit/",
            {"token": "invalid-token"},
            follow=True,
        )
        messages_list = [str(m) for m in response.context["messages"]]
        self.assertTrue(any("二重に送信された可能性" in m for m in messages_list))
        self.assertFalse(AuditLog.objects.filter(action="メイン画面項目設定　更新").exists())

    def test_other_logout_edit_post_with_invalid_token_shows_error_and_does_not_save(self):
        PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.ADMIN)
        response = self.client.post(
            "/settings/other/logout/edit/",
            {"token": "invalid-token", "session_idle_timeout_minutes": "30"},
            follow=True,
        )
        messages_list = [str(m) for m in response.context["messages"]]
        self.assertTrue(any("二重に送信された可能性" in m for m in messages_list))
        self.assertFalse(AuditLog.objects.filter(action="自動ログアウト時間設定　更新").exists())

    def test_other_logout_edit_rejects_resubmission_of_the_same_valid_token(self):
        """X-3：不正トークンではなく「正当なトークンの2回目送信」（ブラウザの戻る+再送信・
        二度押し）自体を実際のビュー経由（E2E）で拒否できることを検証する。"""
        PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.ADMIN)
        token = self.client.get("/settings/other/logout/edit/").context["token"]

        self.client.post(
            "/settings/other/logout/edit/",
            {"token": token, "session_idle_timeout_minutes": "45"},
        )
        self.assertEqual(SystemSetting.load().session_idle_timeout_minutes, 45)

        response = self.client.post(
            "/settings/other/logout/edit/",
            {"token": token, "session_idle_timeout_minutes": "90"},
            follow=True,
        )
        messages_list = [str(m) for m in response.context["messages"]]
        self.assertTrue(any("二重に送信された可能性" in m for m in messages_list))
        self.assertEqual(SystemSetting.load().session_idle_timeout_minutes, 45)


class OtherViewsDatabaseWriteFailureTests(TestCase):
    """OtherSettingsView.post（パスワード保存）/OtherMainEditView.post（メイン画面項目設定保存）の
    DB書き込み失敗（IntegrityError/DatabaseError）分岐が未検証だった（正常系・バリデーション
    エラー系は厚いが、DB境界の異常系はここでも手薄。テストカバレッジ棚卸しで発見、2026-08-26追加）。
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

    def test_other_settings_post_db_failure_shows_friendly_message(self):
        PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.STAFF)
        response = self.client.get("/settings/other/")
        token = response.context["token"]
        with patch.object(Employee, "save", side_effect=DatabaseError("simulated db error")):
            response2 = self.client.post(
                "/settings/other/",
                {"token": token, "new_password": "newpass123", "new_password_confirm": "newpass123"},
                follow=True,
            )
        messages_list = [str(m) for m in response2.context["messages"]]
        self.assertTrue(any("パスワードの更新に失敗しました" in m for m in messages_list))
        self.employee.refresh_from_db()
        self.assertTrue(self.employee.check_password("pass1234"))

    def test_other_main_edit_post_db_failure_shows_friendly_message(self):
        PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.ADMIN)
        response = self.client.get(f"/settings/other/main/{self.department.pk}/edit/")
        token = response.context["token"]
        with patch("core.forms.MenuItemSettingForm.save", side_effect=DatabaseError("simulated db error")):
            response2 = self.client.post(
                f"/settings/other/main/{self.department.pk}/edit/",
                {"token": token},
                follow=True,
            )
        messages_list = [str(m) for m in response2.context["messages"]]
        self.assertTrue(any("メイン画面項目設定の更新に失敗しました" in m for m in messages_list))


class UploadServicesErrorHandlingTests(TestCase):
    """core/upload_services.pyのファイルI/O例外処理（コード監査2026-08-10で指摘・修正）。
    握りつぶさず`PendingFileStorageError`として意味のある形で伝播すること、複数ファイル
    ループ途中の失敗で孤児ファイルを残さないことを検証する。
    """

    SESSION_KEY = "test_pending_files"

    def setUp(self):
        self.session = SessionStore()
        self.tmp_dir = Path(settings.MEDIA_ROOT) / TMP_UPLOAD_SUBDIR

    def test_mkdir_failure_raises_pending_file_storage_error(self):
        files = [SimpleUploadedFile("a.pdf", b"dummy")]
        with patch("pathlib.Path.mkdir", side_effect=OSError("simulated disk error")):
            with self.assertRaises(PendingFileStorageError):
                save_pending_files(self.session, self.SESSION_KEY, files)

    def test_write_failure_rolls_back_earlier_files_in_same_batch(self):
        real_open = open

        files = [
            SimpleUploadedFile("first.pdf", b"dummy1"),
            SimpleUploadedFile("second.pdf", b"dummy2"),
        ]

        # 1件目は成功させ、2件目の書き込みで失敗させることで、1件目として書き込み済みの
        # 一時ファイルがロールバックされることを確認する
        # （tmp_uploads配下への書き込み(wb)だけを狙って失敗させ、テストランナー自体の
        # ログ出力等、他のファイルI/Oを巻き込まないようにする）。
        call_count = {"n": 0}

        def flaky_open_second_only(file, mode="r", *args, **kwargs):
            if mode == "wb" and TMP_UPLOAD_SUBDIR in str(file):
                call_count["n"] += 1
                if call_count["n"] == 2:
                    raise OSError("simulated disk error")
            return real_open(file, mode, *args, **kwargs)

        before = set(self.tmp_dir.glob("*")) if self.tmp_dir.exists() else set()
        with patch("builtins.open", side_effect=flaky_open_second_only):
            with self.assertRaises(PendingFileStorageError):
                save_pending_files(self.session, self.SESSION_KEY, files)
        after = set(self.tmp_dir.glob("*")) if self.tmp_dir.exists() else set()

        # 失敗後もtmp_uploads/に新規の孤児ファイルが残っていないこと、セッションにも
        # 部分的な状態が反映されていないことを確認する。
        self.assertEqual(before, after)
        self.assertNotIn(self.SESSION_KEY, self.session)

    def test_open_pending_file_missing_file_raises_pending_file_storage_error(self):
        with self.assertRaises(PendingFileStorageError):
            open_pending_file("does-not-exist_dummy.pdf")

    def test_clear_pending_files_continues_after_delete_failure(self):
        files = [SimpleUploadedFile("keep_me.pdf", b"dummy")]
        pending = save_pending_files(self.session, self.SESSION_KEY, files)
        temp_name = pending[0]["temp_name"]

        with patch("pathlib.Path.unlink", side_effect=OSError("simulated permission error")):
            # 削除が失敗しても例外を再送出せず処理を継続し、セッションからは消すことを確認する
            # （clear_pending_filesのdocstringに明記した意図的な設計判断）。
            clear_pending_files(self.session, self.SESSION_KEY)

        self.assertNotIn(self.SESSION_KEY, self.session)
        # 実体は削除に失敗しているため残っている（孤児ファイル）。後片付けする。
        (self.tmp_dir / temp_name).unlink(missing_ok=True)

    def test_remove_pending_file_drops_one_entry_and_deletes_its_temp_file(self):
        """保管画面２（登録）の「削除」ボタン（アップロード取り消し）。表示中の1件だけを
        保留一覧から外し、その一時ファイル実体も消す。他のエントリはそのまま残る。"""
        pending = save_pending_files(
            self.session,
            self.SESSION_KEY,
            [SimpleUploadedFile("a.pdf", b"a"), SimpleUploadedFile("b.pdf", b"b")],
        )
        removed_temp = pending[0]["temp_name"]
        kept_temp = pending[1]["temp_name"]

        result = remove_pending_file(self.session, self.SESSION_KEY, 0)

        self.assertEqual(result["original_name"], "a.pdf")
        self.assertEqual(
            [p["original_name"] for p in self.session[self.SESSION_KEY]], ["b.pdf"]
        )
        self.assertFalse((self.tmp_dir / removed_temp).exists())
        self.assertTrue((self.tmp_dir / kept_temp).exists())
        (self.tmp_dir / kept_temp).unlink(missing_ok=True)

    def test_remove_pending_file_out_of_range_returns_none_without_side_effects(self):
        pending = save_pending_files(
            self.session, self.SESSION_KEY, [SimpleUploadedFile("a.pdf", b"a")]
        )
        self.assertIsNone(remove_pending_file(self.session, self.SESSION_KEY, 5))
        self.assertIsNone(remove_pending_file(self.session, self.SESSION_KEY, -1))
        self.assertEqual(len(self.session[self.SESSION_KEY]), 1)
        (self.tmp_dir / pending[0]["temp_name"]).unlink(missing_ok=True)


class BulkEditServicesStagingTests(TestCase):
    """core.bulk_edit_services のステージング型セッションヘルパー（2026-08-28ユーザー確定）。"""

    KEY = "test_bulk_edit"

    def setUp(self):
        self.session = SessionStore()

    def _start(self, pks):
        from core.bulk_edit_services import start_bulk_edit

        start_bulk_edit(self.session, self.KEY, list(pks))

    def test_start_initialises_staging_areas(self):
        self._start([10, 20])
        state = self.session[self.KEY]
        self.assertEqual(state, {"pks": [10, 20], "index": 0, "staged": {}, "to_delete": [], "staged_related": {}})

    def test_stage_page_and_read_back(self):
        from core.bulk_edit_services import get_bulk_edit_state, stage_page, staged_page_data

        self._start([10, 20])
        stage_page(self.session, self.KEY, 10, {"title_0": "new"})
        state = get_bulk_edit_state(self.session, self.KEY)
        self.assertEqual(staged_page_data(state, 10), {"title_0": "new"})
        self.assertIsNone(staged_page_data(state, 20))

    def test_toggle_delete_mark(self):
        from core.bulk_edit_services import is_marked_for_delete, toggle_delete_mark

        self._start([10, 20])
        self.assertTrue(toggle_delete_mark(self.session, self.KEY, 10))
        self.assertTrue(is_marked_for_delete(self.session[self.KEY], 10))
        self.assertFalse(toggle_delete_mark(self.session, self.KEY, 10))
        self.assertFalse(is_marked_for_delete(self.session[self.KEY], 10))

    def test_stage_related_ids_overwrites(self):
        """Rev1.6：関連書類のステージは「紐付け先契約書pkの全量リスト」を丸ごと上書きする
        （差分ではない）。未編集ページは None（＝現状維持）。"""
        from core.bulk_edit_services import stage_related_ids, staged_related_ids_for

        self._start([10, 20])
        stage_related_ids(self.session, self.KEY, 10, [3, 5])
        stage_related_ids(self.session, self.KEY, 10, [7])
        self.assertEqual(staged_related_ids_for(self.session[self.KEY], 10), [7])
        self.assertIsNone(staged_related_ids_for(self.session[self.KEY], 20))

    def test_staged_related_ids_for_tolerates_legacy_bucket_without_key(self):
        """U-35／audit_core No.7：旧形式セッション（"related_ids" キーの無い bucket）が
        デプロイ跨ぎで残っても KeyError にならず [] を返す（bucket.get(...) 参照）。"""
        from core.bulk_edit_services import staged_related_ids_for

        self._start([10])
        state = self.session[self.KEY]
        state["staged_related"] = {"10": {"add": [1], "remove": [2]}}  # 旧形式
        self.assertEqual(staged_related_ids_for(state, 10), [])
        self.assertIsNone(staged_related_ids_for(state, 20))

    def test_discard_bulk_edit_clears_state(self):
        from core.bulk_edit_services import discard_bulk_edit, stage_related_ids

        self._start([10])
        stage_related_ids(self.session, self.KEY, 10, [3])
        discard_bulk_edit(self.session, self.KEY)
        self.assertIsNone(self.session.get(self.KEY))


class BaseBulkEditViewCoreTests(TestCase):
    """core.bulk_edit_views.BaseBulkEditView のうち、documents/contracts の BulkEditViewTests に
    対応テストが無い分岐（review_test_audit_core.txt No.10 / No.18）を、具象サブクラス
    documents.views.BulkEditView を実際に HTTP で叩いて検証する（BaseBulkEditView は抽象クラスの
    ため単体では叩けない）。"""

    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.other_department = Department.objects.create(
            branch_code="999", branch_name="他支店", section_code="09", section_name="他部署"
        )
        self.employee = Employee.objects.create_user(
            employee_no="1", name="テスト太郎", password="pass1234",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.ADMIN)
        self.group = Group.objects.create(code="A", name="分類Ａ", doc_kbn=DocKbn.DOCUMENT)
        self.category = Category.objects.create(
            code="001", name="カテゴリーＡ", group=self.group, doc_kbn=DocKbn.DOCUMENT
        )
        self.retention_period = RetentionPeriod.objects.create(
            kbn=RetentionKbn.DOCUMENT, period_value=1, period_unit=RetentionPeriodUnit.YEAR,
            display_order=1,
        )
        self.client.login(username="1", password="pass1234")

    def _create_document(self, title, department=None):
        from documents.models import Document

        doc = Document(
            title=title, department=department or self.department, group=self.group,
            category=self.category, year=2026, retention_period=self.retention_period,
            uploader=self.employee, expiry_date=datetime.date(2030, 1, 1),
        )
        doc.file.save(f"{title}.txt", ContentFile(b"hello"), save=False)
        doc.save()
        return doc

    def _get_token(self):
        import re

        get_response = self.client.get("/documents/bulk-edit/")
        return re.search(
            r'name="token" value="([^"]+)"', get_response.content.decode("utf-8")
        ).group(1)

    def _page_data(self, obj, *, title=None, bulk_action="update", **extra):
        """表示中ページの送信データ（既定は obj の現在値そのまま＝dirty でない「更新」）。
        `bulk_action=None` を渡すと bulk_action を送らない（ページ移動 bulk_nav 用）。"""
        data = {
            "token": self._get_token(),
            "department": obj.department_id,
            "group": obj.group_id,
            "category": obj.category_id,
            "year": obj.year,
            "retention_period": obj.retention_period_id,
            "privacy_flag": "True" if obj.privacy_flag else "False",
            "memo": obj.memo or "",
            "title_0": title if title is not None else obj.title,
        }
        if bulk_action is not None:
            data["bulk_action"] = bulk_action
        data.update(extra)
        return data

    def test_update_post_with_invalid_token_aborts_without_committing(self):
        """[review_test_audit_core.txt No.10] BaseBulkEditView.post のインライン consume_token
        失敗分岐（bulk_edit_views.py:145-147。reject_if_resubmitted ではない別実装）。一括編集
        「更新」POST でトークン不一致 → messages.error ＋ bulk_edit_url へ redirect ＋ ステージ内容が
        確定されない（DB 無変更・監査ログ無し・セッション状態は保持）ことを固定する。"""
        from django.contrib.messages import get_messages

        docs = [self._create_document(f"d{i}") for i in range(2)]
        self.client.post("/documents/bulk-edit/start/", {"pks": [d.pk for d in docs]})
        data = self._page_data(docs[0], title="d0-new")
        data["token"] = "bogus-token"

        resp = self.client.post("/documents/bulk-edit/", data)

        self.assertRedirects(resp, "/documents/bulk-edit/")
        texts = [str(m) for m in get_messages(resp.wsgi_request)]
        self.assertTrue(any("二重に送信された可能性がある" in t for t in texts))
        docs[0].refresh_from_db()
        self.assertEqual(docs[0].title, "d0")
        self.assertEqual(AuditLog.objects.filter(action="保管画面２　更新").count(), 0)
        self.assertIsNotNone(self.client.session.get("documents_bulk_edit"))

    def test_commit_drops_pk_that_left_department_scope_after_wizard_start(self):
        """[review_test_audit_core.txt No.18 シナリオ(a)] ウィザード開始後に閲覧部署範囲が縮小
        （＝ステージ済みの対象が部署スコープ外に）なった pk は、_committable_pks の
        dept_ids_resolver 再適用で確定対象から静かに除外され、ステージ済み編集が反映されない
        （＋dropped の logger.warning）。開始時除外のテストはあるが確定経路は未カバーだった。"""
        self.employee.permission_profile.role = PermissionRole.STAFF
        self.employee.permission_profile.save(update_fields=["role"])
        scope = DepartmentViewScope.objects.create(
            viewer_department=self.department, visible_department=self.other_department
        )
        own = self._create_document("own")
        other = self._create_document("other", department=self.other_department)
        self.client.post("/documents/bulk-edit/start/", {"pks": [own.pk, other.pk]})
        self.client.post(
            "/documents/bulk-edit/", self._page_data(own, bulk_action=None, bulk_nav="next")
        )
        self.client.post(
            "/documents/bulk-edit/",
            self._page_data(other, title="other-new", bulk_action=None, bulk_nav="prev"),
        )
        # 開始後に閲覧部署範囲を取り消す（管理者が当該職員のスコープを縮小したのと同義）。
        scope.delete()

        with self.assertLogs("core.bulk_edit_views", level="WARNING") as cm:
            resp = self.client.post("/documents/bulk-edit/", self._page_data(own))

        self.assertEqual(resp.status_code, 200)
        other.refresh_from_db()
        self.assertEqual(other.title, "other")
        self.assertFalse(
            AuditLog.objects.filter(
                action="保管画面２　更新", event_message__contains="other"
            ).exists()
        )
        self.assertTrue(any("スコープ外/論理削除済み" in message for message in cm.output))

    def test_start_dedupes_duplicated_pks(self):
        """U-23／audit_core No.3：改ざんで同じ pk を複数回 POST しても、resolve_ordered_pks が
        dict.fromkeys で順序保持 dedupe するため、ウィザードの pks には1回しか入らない
        （dedupe しないと確定ループが同一レコードを2回削除扱いし削除監査ログが重複する）。"""
        docs = [self._create_document(f"d{i}") for i in range(2)]
        self.client.post(
            "/documents/bulk-edit/start/",
            {"pks": [docs[0].pk, docs[1].pk, docs[0].pk, docs[1].pk, docs[0].pk]},
        )
        state = self.client.session["documents_bulk_edit"]
        self.assertEqual(state["pks"], [docs[0].pk, docs[1].pk])

    def test_bulk_delete_of_duplicated_pk_writes_one_audit_log(self):
        """dedupe の効果：同一 pk を2回送って一括削除しても削除監査ログは1件だけ。"""
        doc = self._create_document("dup")
        self.client.post("/documents/bulk-edit/start/", {"pks": [doc.pk, doc.pk]})
        self.client.post("/documents/bulk-edit/", self._page_data(doc, bulk_action="toggle_delete"))
        self.client.post("/documents/bulk-edit/", self._page_data(doc))
        self.assertEqual(
            AuditLog.objects.filter(action="保管画面２　削除", event_message__contains="dup").count(), 1
        )

    def test_commit_drops_pk_logically_deleted_after_wizard_start(self):
        """[review_test_audit_core.txt No.18 シナリオ(b)] 別タブ／他ユーザーが対象を論理削除した
        後に「更新」しても、_committable_pks の is_deleted=False 再適用でゴミ箱内レコードは確定
        対象から除外され、編集も「更新」監査ログも発生しない。"""
        from documents.models import Document

        docs = [self._create_document(f"d{i}") for i in range(2)]
        self.client.post("/documents/bulk-edit/start/", {"pks": [d.pk for d in docs]})
        self.client.post(
            "/documents/bulk-edit/", self._page_data(docs[0], bulk_action=None, bulk_nav="next")
        )
        self.client.post(
            "/documents/bulk-edit/",
            self._page_data(docs[1], title="d1-new", bulk_action=None, bulk_nav="prev"),
        )
        Document.objects.filter(pk=docs[1].pk).update(is_deleted=True, deleted_at=timezone.now())

        with self.assertLogs("core.bulk_edit_views", level="WARNING") as cm:
            resp = self.client.post("/documents/bulk-edit/", self._page_data(docs[0]))

        self.assertEqual(resp.status_code, 200)
        docs[1].refresh_from_db()
        self.assertEqual(docs[1].title, "d1")
        self.assertFalse(
            AuditLog.objects.filter(
                action="保管画面２　更新", event_message__contains="d1"
            ).exists()
        )
        self.assertTrue(any("スコープ外/論理削除済み" in message for message in cm.output))


class OptionListAPIScopeExtensionTests(TestCase):
    """core.api.BaseOptionListAPIView の部署スコープ拡張／自部署スコープ絞り込み分岐
    （review_test_audit_core.txt No.15 / No.16）。documents/contracts の OptionsAPIViewTests は
    「STAFF=自部署のみ」「ADMIN=全部署」の2択しか無く、非管理者の閲覧範囲が1件広がった中間状態や
    「他部署の分類・カテゴリーを popup に出さない」部署スコープ層が未検証だった。core 側の基底
    クラスの分岐のため、両アプリのエンドポイントを叩いて確認する。"""

    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.scope_dept = Department.objects.create(
            branch_code="111", branch_name="A支店", section_code="01", section_name="営業部"
        )
        self.unrelated_dept = Department.objects.create(
            branch_code="222", branch_name="B支店", section_code="01", section_name="経理部"
        )
        self.employee = Employee.objects.create_user(
            employee_no="1", name="テスト太郎", password="pass1234",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        self.profile = PermissionProfile.objects.create(
            employee=self.employee, role=PermissionRole.STAFF
        )
        self.client.login(username="1", password="pass1234")

    def test_document_dept_options_add_one_department_from_view_scope(self):
        """[No.15/文書] 非管理者に DepartmentViewScope で他部署が1件許可されると、その部署だけが
        popup 選択肢に加わる（＝documents.search_services.build_queryset の絞り込み範囲と一致）。"""
        DepartmentViewScope.objects.create(
            viewer_department=self.department, visible_department=self.scope_dept
        )
        response = self.client.get("/documents/api/options/", {"type": "dept"})
        values = {i["value"] for i in response.json()["items"]}
        self.assertEqual(values, {self.department.pk, self.scope_dept.pk})
        self.assertNotIn(self.unrelated_dept.pk, values)

    def test_contract_dept_options_add_one_department_from_contract_view_setting(self):
        """[No.15/契約書] 契約書-部門間閲覧設定（PermissionProfile.contract_visible_departments）で
        追加された部署だけが popup 選択肢に加わる（permissions.services.
        contract_searchable_department_ids と一致）。"""
        self.profile.contract_visible_departments.add(self.scope_dept)
        response = self.client.get("/contracts/api/options/", {"type": "dept"})
        values = {i["value"] for i in response.json()["items"]}
        self.assertEqual(values, {self.department.pk, self.scope_dept.pk})
        self.assertNotIn(self.unrelated_dept.pk, values)

    def test_document_group_options_exclude_other_department_groups(self):
        """[No.16] _scope_by_department（permissions.services.department_ids_for_group_scope による
        自部署スコープ絞り込み）。visible_groups（権限）とは別レイヤーで、他部署の分類は popup に
        出さない（フォームの queryset 差し替えでは効かず API 本体で再適用している分岐）。"""
        own = Group.objects.create(
            code="A", name="自部署分類", doc_kbn=DocKbn.DOCUMENT, department=self.department
        )
        other = Group.objects.create(
            code="B", name="他部署分類", doc_kbn=DocKbn.DOCUMENT, department=self.unrelated_dept
        )
        response = self.client.get("/documents/api/options/", {"type": "group"})
        values = {i["value"] for i in response.json()["items"]}
        self.assertIn(own.pk, values)
        self.assertNotIn(other.pk, values)

    def test_document_category_options_exclude_other_department_categories(self):
        """[No.16] _category_items 経由の _scope_by_department。_category_items には visible_groups
        相当のフィルタが無いぶん、部署スコープが唯一の絞り込みになる。"""
        group = Group.objects.create(
            code="A", name="分類Ａ", doc_kbn=DocKbn.DOCUMENT, department=self.department
        )
        Category.objects.create(
            code="001", name="自部署カテゴリー", group=group, doc_kbn=DocKbn.DOCUMENT,
            department=self.department,
        )
        Category.objects.create(
            code="002", name="他部署カテゴリー", group=group, doc_kbn=DocKbn.DOCUMENT,
            department=self.unrelated_dept,
        )
        response = self.client.get("/documents/api/options/", {"type": "category"})
        labels = {i["label"] for i in response.json()["items"]}
        self.assertIn("自部署カテゴリー", labels)
        self.assertNotIn("他部署カテゴリー", labels)


class ChunkUploadServiceTests(TestCase):
    """core/upload_services.pyのチャンク分割アップロード（save_upload_chunk/combine_upload_chunks）。
    documents/contracts.tests.ChunkUploadAPITestsがビュー経由の配線を検証するのに対し、
    こちらはサービス層のファイル結合・サイズ上限・クリーンアップの挙動そのものを検証する。
    """

    SESSION_KEY = "test_chunk_pending_files"

    def setUp(self):
        self.session = SessionStore()
        self.chunk_dir = Path(settings.MEDIA_ROOT) / TMP_UPLOAD_SUBDIR / "chunks"
        self.tmp_dir = Path(settings.MEDIA_ROOT) / TMP_UPLOAD_SUBDIR

    def test_combine_appends_to_existing_session_pending_list(self):
        """通常アップロード分（save_pending_files）が既にセッションへ登録済みの状態でも、
        チャンク経由のファイルが上書きせず追記されること（documents/contracts.UploadStep1View.post
        の「通常ファイル0件でもチャンク経由の登録済み分で進める」設計の前提）。
        """
        existing = save_pending_files(
            self.session, self.SESSION_KEY, [SimpleUploadedFile("first.pdf", b"dummy")]
        )
        save_upload_chunk("upload-1", 0, SimpleUploadedFile("chunk", b"A" * 10))
        combine_upload_chunks(self.session, self.SESSION_KEY, "upload-1", 1, "second.pdf")

        pending = self.session[self.SESSION_KEY]
        self.assertEqual(len(pending), 2)
        self.assertEqual(pending[0]["temp_name"], existing[0]["temp_name"])
        self.assertTrue(pending[1]["temp_name"].endswith("_second.pdf"))
        # チャンク断片は結合成功後に削除されていること。
        self.assertFalse((self.chunk_dir / "upload-1").exists())

    def test_missing_chunk_raises_and_cleans_up_saved_chunks(self):
        save_upload_chunk("upload-2", 0, SimpleUploadedFile("chunk", b"A" * 10))
        # チャンク1を保存せずに結合を試みる（total_chunks=2だが実際には1つしか無い）。
        with self.assertRaises(ChunkUploadError):
            combine_upload_chunks(self.session, self.SESSION_KEY, "upload-2", 2, "broken.pdf")
        self.assertNotIn(self.SESSION_KEY, self.session)
        # 欠落検出時、保存済みだったチャンク0も後片付けされていること（ゴミを残さない設計）。
        self.assertFalse((self.chunk_dir / "upload-2").exists())

    def test_combined_size_over_limit_raises_and_cleans_up(self):
        save_upload_chunk("upload-3", 0, SimpleUploadedFile("chunk", b"A" * 10))
        save_upload_chunk("upload-3", 1, SimpleUploadedFile("chunk", b"B" * 10))
        with self.settings(CHUNK_UPLOAD_MAX_SIZE_BYTES=15):
            with self.assertRaises(ChunkUploadError):
                combine_upload_chunks(self.session, self.SESSION_KEY, "upload-3", 2, "toobig.pdf")
        self.assertFalse((self.chunk_dir / "upload-3").exists())

    def test_original_filename_path_component_is_stripped(self):
        """original_filenameはブラウザ側File.nameをそのまま受け取る値のため、万一パス区切り文字が
        混入していてもtmp_uploads配下に閉じたファイル名として結合すること（ディレクトリ
        トラバーサル対策）。"""
        save_upload_chunk("upload-4", 0, SimpleUploadedFile("chunk", b"A" * 10))
        combine_upload_chunks(self.session, self.SESSION_KEY, "upload-4", 1, "../../evil.pdf")

        pending = self.session[self.SESSION_KEY]
        temp_name = pending[0]["temp_name"]
        self.assertNotIn("..", temp_name)
        self.assertTrue((self.tmp_dir / temp_name).exists())
        (self.tmp_dir / temp_name).unlink(missing_ok=True)

    def test_save_upload_chunk_io_failure_raises_pending_file_storage_error(self):
        with patch("pathlib.Path.mkdir", side_effect=OSError("simulated disk error")):
            with self.assertRaises(PendingFileStorageError):
                save_upload_chunk("upload-5", 0, SimpleUploadedFile("chunk", b"A"))


class CleanupTempUploadsCommandTests(TestCase):
    """core.management.commands.cleanup_temp_uploads（2026-08-13追加）。

    storage/media/tmp_uploads/にテスト実行やウィザード中断の残骸が無期限に蓄積していた問題
    （IsolatedMediaTestRunner導入と合わせて対応）への恒久策。settings.STALE_TMP_UPLOAD_
    THRESHOLD_HOURSより古いものだけを削除し、閾値内（＝進行中の可能性がある）ものは残すこと、
    chunks/配下は upload_id ディレクトリ単位で削除することを検証する。

    コマンド名は`ja_system/bat/cleanup_temp_uploads.bat`が前提としている名前（旧実装Phase1
    時代の別レイアウト向けコマンドを指したまま移植されていなかった）に合わせている
    （core.management.commands.cleanup_temp_uploadsのモジュールdocstring参照）。
    """

    def setUp(self):
        self.tmp_dir = Path(settings.MEDIA_ROOT) / TMP_UPLOAD_SUBDIR
        self.chunk_dir = self.tmp_dir / "chunks"
        self.tmp_dir.mkdir(parents=True, exist_ok=True)

    def _touch(self, path, hours_ago):
        path.write_bytes(b"dummy")
        old_time = (timezone.now() - datetime.timedelta(hours=hours_ago)).timestamp()
        os.utime(path, (old_time, old_time))

    def test_old_loose_file_removed_recent_file_kept(self):
        old_file = self.tmp_dir / "old_a.pdf"
        recent_file = self.tmp_dir / "recent_a.pdf"
        self._touch(old_file, hours_ago=48)
        self._touch(recent_file, hours_ago=1)

        call_command("cleanup_temp_uploads")

        self.assertFalse(old_file.exists())
        self.assertTrue(recent_file.exists())

    def test_old_chunk_dir_removed_recent_chunk_dir_kept(self):
        old_chunk_dir = self.chunk_dir / "old-upload"
        recent_chunk_dir = self.chunk_dir / "recent-upload"
        old_chunk_dir.mkdir(parents=True)
        recent_chunk_dir.mkdir(parents=True)
        self._touch(old_chunk_dir / "chunk_0000", hours_ago=48)
        self._touch(recent_chunk_dir / "chunk_0000", hours_ago=1)

        call_command("cleanup_temp_uploads")

        self.assertFalse(old_chunk_dir.exists())
        self.assertTrue(recent_chunk_dir.exists())

    def test_default_threshold_keeps_files_within_24_hours(self):
        recent_file = self.tmp_dir / "recent_a.pdf"
        self._touch(recent_file, hours_ago=23)

        call_command("cleanup_temp_uploads")

        self.assertTrue(recent_file.exists())

    def test_dry_run_lists_targets_without_deleting(self):
        old_file = self.tmp_dir / "old_a.pdf"
        self._touch(old_file, hours_ago=48)

        call_command("cleanup_temp_uploads", "--dry-run")

        self.assertTrue(old_file.exists())


class PopupSelectWidgetTamperResistanceTests(TestCase):
    """core/widgets.pyのPopupSelectWidget（コード監査2026-08-10で指摘・修正）。フォーム改ざんで
    非数値のpk値が混入しても、queryset.filter(pk__in=...)実行時に未処理のValueErrorで
    500にならず、不正値を無視して描画できることを検証する。
    """

    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )

    def test_render_ignores_non_numeric_tampered_pk_without_raising(self):
        widget = PopupSelectWidget(
            popup_type="dept", mode="storage", api_url="/core/api/options/",
            queryset=Department.objects.all(), multi=True,
        )
        # "abc"は改ざんされた非数値値。例外を送出せず、有効な値(self.department.pk)だけを
        # ラベルに反映できることを確認する。
        html = widget.render("dept", f"abc,{self.department.pk}", attrs={"id": "id_dept"})
        self.assertIn("id_dept", html)
        self.assertIn(str(self.department), html)

    def test_display_element_is_single_line_input_by_default(self):
        widget = PopupSelectWidget(
            popup_type="dept", mode="search", api_url="/core/api/options/",
            queryset=Department.objects.all(), multi=True,
        )
        html = widget.render("dept", str(self.department.pk), attrs={"id": "id_dept"})
        self.assertIn('<input type="text" id="id_dept_display"', html)
        self.assertNotIn("<textarea", html)

    def test_display_multiline_renders_readonly_textarea_with_value_as_content(self):
        """簡易設計指示書 Rev1.3（権限管理編集）で追加。display_multiline=Trueのとき、表示用要素を
        複数行<textarea readonly>で描画し、選択済みラベルは属性ではなくタグ内容として持つ。
        """
        widget = PopupSelectWidget(
            popup_type="dept", mode="search", api_url="/core/api/options/",
            queryset=Department.objects.all(), multi=True, display_multiline=True,
        )
        html = widget.render("dept", str(self.department.pk), attrs={"id": "id_dept"})
        self.assertIn('<textarea id="id_dept_display"', html)
        self.assertIn("readonly", html)
        self.assertIn(f">{self.department}</textarea>", html)
        # 原本 index.html html5（Rev1.3で画面変更、Rev1.4時点）の rows="5" に一致させる。
        self.assertIn('rows="5"', html)
        # 送信用hidden inputと「選択」ボタンは従来通り。
        self.assertIn('type="hidden"', html)
        self.assertIn("選択</button>", html)


class PopupSelectPositioningJsTests(TestCase):
    """common.js の popup-select 配置ロジック（原本 index.html html5 の openPopupPopup 移植）。
    本プロジェクトに JS 単体テストの仕組みは無いため（クライアント JS は実プレビューで確認する
    方針）、ここでは静的ファイルを読んで「縦位置の反転ロジックが positionPopupPopup に切り出され、
    openPopupPopup から renderPopupPopupItems() の後に呼ばれる」構造が保たれているかを回帰ガード
    として検証する（原本 html5 で Rev1.3 の rows=5 textarea 対応として追加された挙動）。
    """

    def _js(self):
        return (settings.BASE_DIR / "static" / "js" / "common.js").read_text(encoding="utf-8")

    def test_position_helper_defined_and_flips_upward(self):
        js = self._js()
        self.assertIn("function positionPopupPopup(btn)", js)
        # 下端はみ出し時にボタンの上へ反転する式
        self.assertIn("rect.bottom + 5 + popRect.height > windowHeight", js)
        self.assertIn("rect.top - popRect.height - 5", js)

    def test_open_calls_position_after_render_on_both_cache_paths(self):
        js = self._js()
        open_body = js.split("function openPopupPopup(btn, type, mode, apiUrl) {", 1)[1].split(
            "function positionPopupPopup", 1
        )[0]
        # キャッシュヒット側・fetch解決側の両方で render の直後に position を呼ぶ
        self.assertIn("renderPopupPopupItems();\n    positionPopupPopup(btn);", open_body)
        self.assertIn("renderPopupPopupItems();\n        positionPopupPopup(btn);", open_body)
        # 原本 html5 に合わせた previousElementSibling || nextElementSibling
        self.assertIn("btn.previousElementSibling || btn.nextElementSibling", open_body)


class IsScannedTests(TestCase):
    """core.text_extraction_services.is_scanned（スキャン文書判定、2026-08-10追加）の単体テスト。
    元はcore.ocr_servicesにあったが、2026-08-19のOCR関数統合でOCR呼び出し側（現
    core.ocr_layout_services）に残す理由が無くなり、主な利用者であるcore.text_extraction_services
    へ移設した。実際のGoogle Cloud Vision呼び出しのテストはOcrLayoutServicesTestsで行う。
    """

    def test_is_scanned_true_for_empty_or_short_text(self):
        self.assertTrue(is_scanned(""))
        self.assertTrue(is_scanned("   "))
        self.assertTrue(is_scanned("短い"))

    def test_is_scanned_false_for_sufficient_text(self):
        self.assertFalse(is_scanned("十分な文字数を含むテキスト層です。"))


def _make_vertex(x, y):
    return SimpleNamespace(x=x, y=y)


def _make_bbox(x1, y1, x2, y2):
    """Vision APIのbounding_box相当（頂点4つ、左上→右上→右下→左下の順）を組み立てる。"""
    return SimpleNamespace(
        vertices=[_make_vertex(x1, y1), _make_vertex(x2, y1), _make_vertex(x2, y2), _make_vertex(x1, y2)],
    )


def _make_symbol(text, x1, y1, x2, y2):
    return SimpleNamespace(
        text=text, bounding_box=_make_bbox(x1, y1, x2, y2),
        property=SimpleNamespace(detected_break=None),
    )


def _make_word(symbols, x1, y1, x2, y2):
    return SimpleNamespace(symbols=symbols, bounding_box=_make_bbox(x1, y1, x2, y2))


class OcrLayoutServicesTests(TestCase):
    """core.ocr_layout_services（検索用PDFの遅延生成が使う座標付きOCR、2026-08-10追加）
    の単体テスト。実際のGoogle Cloud Vision API・pdf2image（poppler）は使わず、モックで完結させる。
    """

    def test_raises_when_ocr_disabled(self):
        with override_settings(OCR_ENABLED=False):
            with self.assertRaises(OcrDisabledError):
                ocr_layout_services.extract_text_and_layout_via_ocr(b"%PDF-1.4 dummy")

    def test_calls_vision_once_per_page_without_page_limit(self):
        """1リクエスト最大5ページ制約のある同期API(batch_annotate_files)ではなくページ画像を
        1ページずつ投入する方式であることの裏付けとして、5ページを超えるページ数でも
        全ページ分document_text_detectionが呼ばれることを確認する。"""
        mock_vision = MagicMock()
        mock_response = MagicMock()
        mock_response.full_text_annotation.pages = []
        mock_vision.ImageAnnotatorClient.return_value.document_text_detection.return_value = mock_response
        fake_images = [MagicMock() for _ in range(7)]

        with override_settings(OCR_ENABLED=True):
            with patch.dict(
                "sys.modules", {"google.cloud": MagicMock(vision=mock_vision), "google.cloud.vision": mock_vision}
            ):
                with patch("pdf2image.pdfinfo_from_path", return_value={"Pages": 7}), patch(
                    "pdf2image.convert_from_path", return_value=[fake_images[0]]
                ):
                    text, textdatas = ocr_layout_services.extract_text_and_layout_via_ocr(
                        b"%PDF-1.4 dummy", source_name="big.pdf",
                    )
        self.assertEqual(
            mock_vision.ImageAnnotatorClient.return_value.document_text_detection.call_count, 7,
        )
        self.assertEqual(text, "\n" * 6)  # 各ページのテキストが空文字のまま改行7個分連結される
        self.assertEqual(textdatas, [])

    def test_page_error_is_skipped_without_failing_other_pages(self):
        """1ページのOCR失敗（Vision APIの一時的なエラー等）で他ページの処理を止めない
        （core.ocr_services.extract_text_via_ocrに同名のテストがあったが、2026-08-19の統合で
        本モジュールが唯一のOCR呼び出し口になったためこちらに移設）。"""
        mock_vision = MagicMock()
        ok_response = MagicMock()
        ok_response.full_text_annotation.pages = []
        mock_vision.ImageAnnotatorClient.return_value.document_text_detection.side_effect = [
            RuntimeError("internal error"), ok_response,
        ]

        with override_settings(OCR_ENABLED=True):
            with patch.dict(
                "sys.modules", {"google.cloud": MagicMock(vision=mock_vision), "google.cloud.vision": mock_vision}
            ):
                with patch("pdf2image.pdfinfo_from_path", return_value={"Pages": 2}), patch(
                    "pdf2image.convert_from_path", return_value=[MagicMock()]
                ):
                    text, textdatas = ocr_layout_services.extract_text_and_layout_via_ocr(b"%PDF-1.4 dummy")

        self.assertEqual(text, "")
        self.assertEqual(textdatas, [])

    def test_vision_call_has_timeout(self):
        """Vision APIの呼び出しにタイムアウトを付ける（応答が固まって1ページで長時間止まらないように）。"""
        mock_vision = MagicMock()
        mock_response = MagicMock()
        mock_response.full_text_annotation.pages = []
        client = mock_vision.ImageAnnotatorClient.return_value
        client.document_text_detection.return_value = mock_response
        with override_settings(OCR_ENABLED=True, OCR_VISION_TIMEOUT_SECONDS=17):
            with patch.dict(
                "sys.modules", {"google.cloud": MagicMock(vision=mock_vision), "google.cloud.vision": mock_vision}
            ):
                with patch("pdf2image.pdfinfo_from_path", return_value={"Pages": 1}), patch(
                    "pdf2image.convert_from_path", return_value=[MagicMock()]
                ):
                    ocr_layout_services.extract_text_and_layout_via_ocr(b"%PDF-1.4 dummy")
        self.assertEqual(client.document_text_detection.call_args.kwargs["timeout"], 17)

    def test_raises_time_limit_error_when_deadline_exceeded(self):
        """max_secondsを超えたら、残りページを処理せずOcrTimeLimitErrorで打ち切る
        （バッチが実行時間制限で強制終了される前に自分で諦められるようにするため）。"""
        mock_vision = MagicMock()
        with override_settings(OCR_ENABLED=True):
            with patch.dict(
                "sys.modules", {"google.cloud": MagicMock(vision=mock_vision), "google.cloud.vision": mock_vision}
            ):
                with patch("pdf2image.pdfinfo_from_path", return_value={"Pages": 3}), patch(
                    "pdf2image.convert_from_path"
                ) as mock_convert, patch("core.ocr_layout_services.time.monotonic", side_effect=[0, 100]):
                    with self.assertRaises(ocr_layout_services.OcrTimeLimitError):
                        ocr_layout_services.extract_text_and_layout_via_ocr(b"%PDF-1.4 dummy", max_seconds=10)
        mock_convert.assert_not_called()

    def test_get_lines_reconstructs_line_from_word_coordinates(self):
        """座標ベースの行復元ロジック（_get_lines）が、同じ行にある複数wordのsymbolテキストを
        1つのTextDataに連結することを検証する（PDF埋め込み時の位置精度の基礎になるロジック）。"""
        symbol1 = _make_symbol("あ", 10, 10, 30, 40)
        symbol2 = _make_symbol("い", 40, 10, 60, 40)
        word1 = _make_word([symbol1], 10, 10, 30, 40)
        word2 = _make_word([symbol2], 40, 10, 60, 40)
        paragraph = SimpleNamespace(words=[word1, word2])
        block = SimpleNamespace(bounding_box=_make_bbox(0, 0, 500, 100), paragraphs=[paragraph])
        page = SimpleNamespace(width=1000, height=1000, blocks=[block])
        response = SimpleNamespace(full_text_annotation=SimpleNamespace(pages=[page]))

        result = ocr_layout_services._get_lines(1, response)

        self.assertEqual(len(result), 1)
        pagedata = result[0]
        self.assertEqual((pagedata.page_no, pagedata.page_width, pagedata.page_height), (1, 1000, 1000))
        self.assertEqual(len(pagedata.textdata_list), 1)
        line = pagedata.textdata_list[0]
        self.assertEqual(line.text, "あい")
        self.assertEqual((line.x1, line.y1, line.x2, line.y2), (10, 10, 60, 40))

        textlines = ocr_layout_services._get_textlines(result, 1)
        self.assertEqual(textlines, ["あい"])

    def test_textdatas_json_round_trip(self):
        """監査 案3：ocr_textdata（JSONField）へ保存する textdatas_to_json と、検索用PDFの
        遅延生成で使う textdatas_from_json が往復で一致する（配列形式 [x1,y1,x2,y2,text]）。"""
        original = [
            TextDatas(1, 800, 1100, [TextData(10, 20, 100, 40, "あいう"), TextData(10, 50, 90, 70, "えお")]),
            TextDatas(2, 800, 1100, [TextData(5, 5, 50, 25, "Ｘ")]),
        ]
        as_json = ocr_layout_services.textdatas_to_json(original)
        # JSON 化しても素の list/dict/int/str だけであること（DB JSONField 保存可能）。
        self.assertEqual(as_json[0]["page"], 1)
        self.assertEqual(as_json[0]["lines"][0], [10, 20, 100, 40, "あいう"])
        restored = ocr_layout_services.textdatas_from_json(as_json)
        self.assertEqual(restored, original)


class PdfTextEmbedServicesTests(TestCase):
    """core.pdf_text_embed_services（検索用PDFの透明テキスト埋め込み、2026-08-10追加）の単体テスト。"""

    @staticmethod
    def _make_blank_pdf_bytes(page_count):
        writer = PdfWriter()
        for _ in range(page_count):
            writer.add_blank_page(width=200, height=200)
        buf = BytesIO()
        writer.write(buf)
        writer.close()
        return buf.getvalue()

    def test_embed_preserves_page_count_and_content(self):
        original_bytes = self._make_blank_pdf_bytes(2)
        textdatas = [
            ocr_layout_services.TextDatas(
                page_no=1, page_width=1000, page_height=1000,
                textdata_list=[ocr_layout_services.TextData(10, 10, 100, 40, "テスト")],
            ),
        ]
        result_bytes = pdf_text_embed_services.embed_textdatas_into_pdf(original_bytes, textdatas)
        reader = PdfReader(BytesIO(result_bytes))
        self.assertEqual(len(reader.pages), 2)

    def test_embed_skips_page_without_matching_textdatas(self):
        """textdatasに対応ページが無い場合はそのページをそのまま出力する（例外にならない）。"""
        original_bytes = self._make_blank_pdf_bytes(1)
        result_bytes = pdf_text_embed_services.embed_textdatas_into_pdf(original_bytes, textdatas=[])
        reader = PdfReader(BytesIO(result_bytes))
        self.assertEqual(len(reader.pages), 1)

    def test_embed_failure_on_one_page_falls_back_to_original_page(self):
        """page_width/page_height が0（不正な座標データ）でも例外を送出せず、そのページは
        透明テキスト無しの原本ページのまま出力する（1ページの埋め込み失敗で全体を失敗させない）。"""
        original_bytes = self._make_blank_pdf_bytes(1)
        textdatas = [
            ocr_layout_services.TextDatas(
                page_no=1, page_width=0, page_height=0,
                textdata_list=[ocr_layout_services.TextData(10, 10, 100, 40, "テスト")],
            ),
        ]
        result_bytes = pdf_text_embed_services.embed_textdatas_into_pdf(original_bytes, textdatas)
        reader = PdfReader(BytesIO(result_bytes))
        self.assertEqual(len(reader.pages), 1)


class SearchablePdfServicesTests(TestCase):
    """core.searchable_pdf_services.build_searchable_pdf（監査 案3）の直接呼び出しテスト。
    documents/contracts側のビューテスト（SearchablePdfViewTests等）はこの関数自体をモック化して
    権限・404・監査ログだけを見ているため、ocr_textdata読み出し→埋め込みの実処理を通しで
    検証するテストがここに無いとカバレッジの穴になる。ocr_textdata・fileの2属性しか使わないため
    Document/Contractモデルは使わずSimpleNamespaceで代用する。"""

    def test_embeds_textdata_from_real_object_attributes(self):
        original_bytes = PdfTextEmbedServicesTests._make_blank_pdf_bytes(1)
        obj = SimpleNamespace(
            ocr_textdata=[{"page": 1, "w": 1000, "h": 1000, "lines": [[10, 10, 100, 40, "テスト"]]}],
            file=SimpleNamespace(open=lambda mode: BytesIO(original_bytes)),
        )
        result_bytes = searchable_pdf_services.build_searchable_pdf(obj)
        reader = PdfReader(BytesIO(result_bytes))
        self.assertEqual(len(reader.pages), 1)

    def test_raises_when_ocr_textdata_empty(self):
        obj = SimpleNamespace(ocr_textdata=None, file=None)
        with self.assertRaises(searchable_pdf_services.SearchablePdfUnavailable):
            searchable_pdf_services.build_searchable_pdf(obj)


class ExtractPendingPdfTextCommandTests(TestCase):
    """extract_pending_pdf_textコマンド（全文検索基盤、2026-08-10追加）の単体テスト。
    実際のPDF解析（pdfplumber）・Google Cloud Vision呼び出しはモック化し、
    1件の抽出失敗でバッチ全体が止まらないことを重点的に検証する。
    """

    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.employee = Employee.objects.create_user(
            employee_no="1", name="テスト太郎", password="pass1234",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        self.group = Group.objects.create(code="A", name="分類Ａ", doc_kbn=DocKbn.DOCUMENT)
        self.category = Category.objects.create(
            code="001", name="カテゴリーＡ", group=self.group, doc_kbn=DocKbn.DOCUMENT
        )
        self.retention_period = RetentionPeriod.objects.create(
            kbn=RetentionKbn.DOCUMENT, period_value=1, period_unit=RetentionPeriodUnit.YEAR, display_order=1
        )

    def _make_document(self, title):
        from documents.models import Document

        doc = Document(
            title=title, department=self.department, group=self.group, category=self.category,
            year=2026, retention_period=self.retention_period, uploader=self.employee,
            expiry_date=timezone.localdate(),
        )
        doc.file.save(f"{title}.pdf", ContentFile(b"%PDF-1.4 dummy"), save=False)
        doc.save()
        return doc

    @staticmethod
    def _mock_pdfplumber(text):
        """pdfplumber.open()が返すコンテキストマネージャをモックし、page.extract_text()が
        textを返すようにする（1ページのみのPDFとして扱う）。"""
        mock_page = MagicMock()
        mock_page.extract_text.return_value = text
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__.return_value = mock_pdf
        mock_pdf.__exit__.return_value = False
        return mock_pdf

    def test_smaller_files_are_processed_first(self):
        """pk順ではなくファイルサイズの小さい順に処理する（大容量スキャンPDFが先頭に居座って
        後ろの文書が飢餓状態になるのを防ぐ）。"""
        from documents.models import Document

        big = self._make_document("大きい")
        big.file.save("big.pdf", ContentFile(b"%PDF-1.4 " + b"x" * 5000), save=True)
        small = self._make_document("小さい")
        order = []

        def fake_extract(obj):
            order.append(obj.pk)
            return "十分な文字数を含む本文テキストです。"

        with patch("core.management.commands.extract_pending_pdf_text.extract_text_layer", side_effect=fake_extract):
            call_command("extract_pending_pdf_text")
        self.assertEqual(order, [small.pk, big.pk])
        self.assertEqual(Document.objects.filter(text_extracted=True).count(), 2)

    def test_size_options_split_documents_into_disjoint_lanes(self):
        """--max-bytes（以下）と--larger-than-bytes（超）に同じ値を渡すと、通常タスクと大容量タスクの
        担当が重複も漏れもなく分かれる。"""
        small = self._make_document("小さい")
        big = self._make_document("大きい")
        big.file.save("big.pdf", ContentFile(b"%PDF-1.4 " + b"x" * 5000), save=True)
        boundary = small.file.size
        seen = []

        def fake_extract(obj):
            seen.append(obj.pk)
            return "十分な文字数を含む本文テキストです。"

        target = "core.management.commands.extract_pending_pdf_text.extract_text_layer"
        with patch(target, side_effect=fake_extract):
            call_command("extract_pending_pdf_text", max_bytes=boundary)
        self.assertEqual(seen, [small.pk])
        seen.clear()
        with patch(target, side_effect=fake_extract):
            call_command("extract_pending_pdf_text", larger_than_bytes=boundary)
        self.assertEqual(seen, [big.pk])

    def test_time_limit_option_overrides_setting(self):
        """--time-limitがsettings.OCR_BATCH_TIME_LIMIT_SECONDSより優先される。"""
        doc1 = self._make_document("一件目")
        doc2 = self._make_document("二件目")
        # 設定は十分長いが、--time-limit=100で2件目の着手時(200秒経過)には打ち切られる。
        with override_settings(OCR_BATCH_TIME_LIMIT_SECONDS=100000), patch(
            "core.management.commands.extract_pending_pdf_text.time.monotonic",
            side_effect=[0, 10, 200],
        ), patch(
            "core.management.commands.extract_pending_pdf_text.extract_text_layer",
            return_value="十分な文字数を含む本文テキストです。",
        ):
            call_command("extract_pending_pdf_text", time_limit=100)
        doc1.refresh_from_db()
        doc2.refresh_from_db()
        self.assertTrue(doc1.text_extracted)
        self.assertFalse(doc2.text_extracted)

    def test_stops_starting_new_records_after_time_limit(self):
        """実行時間の上限に達したら、残りは処理せず次回に持ち越す（text_extracted=Falseのまま）。"""
        doc1 = self._make_document("一件目")
        doc2 = self._make_document("二件目")
        with override_settings(OCR_BATCH_TIME_LIMIT_SECONDS=100), patch(
            "core.management.commands.extract_pending_pdf_text.time.monotonic",
            side_effect=[0, 10, 200],
        ), patch(
            "core.management.commands.extract_pending_pdf_text.extract_text_layer",
            return_value="十分な文字数を含む本文テキストです。",
        ):
            call_command("extract_pending_pdf_text")
        doc1.refresh_from_db()
        doc2.refresh_from_db()
        self.assertTrue(doc1.text_extracted)
        self.assertFalse(doc2.text_extracted)

    def test_ocr_time_limit_defers_record_without_failing_batch(self):
        """OCRが残り時間内に終わらなかった場合は失敗扱いにせず持ち越し、後続の処理は続ける。"""
        scanned = self._make_document("スキャン")
        scanned.file.save("scan.pdf", ContentFile(b"%PDF-1.4 " + b"x" * 5000), save=True)
        normal = self._make_document("通常")
        texts = {scanned.pk: "", normal.pk: "十分な文字数を含む本文テキストです。"}
        with override_settings(OCR_ENABLED=True), patch(
            "core.management.commands.extract_pending_pdf_text.extract_text_layer",
            side_effect=lambda obj: texts[obj.pk],
        ), patch(
            "core.management.commands.extract_pending_pdf_text.ocr_layout_services"
        ) as mock_ocr:
            mock_ocr.extract_text_and_layout_via_ocr.side_effect = OcrTimeLimitError("time over")
            call_command("extract_pending_pdf_text")
        scanned.refresh_from_db()
        normal.refresh_from_db()
        self.assertFalse(scanned.text_extracted)
        self.assertTrue(normal.text_extracted)

    def test_text_layer_extraction_populates_normalized_and_flag(self):
        doc = self._make_document("通常文書")
        with patch(
            "core.text_extraction_services.pdfplumber.open",
            return_value=self._mock_pdfplumber("十分な文字数を含む本文テキストです。"),
        ):
            call_command("extract_pending_pdf_text")
        doc.refresh_from_db()
        self.assertEqual(
            doc.extracted_text_normalized, normalize_for_search("十分な文字数を含む本文テキストです。")
        )
        self.assertTrue(doc.text_extracted)
        self.assertIsNone(doc.ocr_textdata)

    def test_scanned_document_is_skipped_when_ocr_disabled(self):
        doc = self._make_document("スキャン文書")
        with override_settings(OCR_ENABLED=False):
            with patch(
                "core.text_extraction_services.pdfplumber.open", return_value=self._mock_pdfplumber(""),
            ):
                call_command("extract_pending_pdf_text")
        doc.refresh_from_db()
        self.assertEqual(doc.extracted_text_normalized, "")
        # OCR_ENABLED=Falseで呼び出しに至っていないため、有効化後に再試行できるようFalseのまま。
        self.assertFalse(doc.text_extracted)

    def test_scanned_document_uses_ocr_when_enabled(self):
        doc = self._make_document("スキャン文書2")
        with override_settings(OCR_ENABLED=True):
            with patch(
                "core.text_extraction_services.pdfplumber.open", return_value=self._mock_pdfplumber(""),
            ):
                with patch(
                    "core.management.commands.extract_pending_pdf_text.ocr_layout_services"
                    ".extract_text_and_layout_via_ocr",
                    return_value=("OCRで抽出した本文", []),
                ) as mock_ocr:
                    call_command("extract_pending_pdf_text")
        doc.refresh_from_db()
        self.assertEqual(doc.extracted_text_normalized, normalize_for_search("OCRで抽出した本文"))
        self.assertTrue(doc.text_extracted)
        mock_ocr.assert_called_once()

    def test_ocr_result_empty_string_marks_extracted_and_is_excluded_from_next_run(self):
        """OCR結果が本当に空文字列だった場合（画像に文字が全く無い等）、text_extracted=Trueになり、
        次回バッチではOCRが再実行されないことを確認する（無限リトライ対策、監査 案2）。"""
        doc = self._make_document("空文字OCR結果文書")
        with override_settings(OCR_ENABLED=True):
            with patch(
                "core.text_extraction_services.pdfplumber.open", return_value=self._mock_pdfplumber(""),
            ):
                with patch(
                    "core.management.commands.extract_pending_pdf_text.ocr_layout_services"
                    ".extract_text_and_layout_via_ocr",
                    return_value=("", []),
                ) as mock_ocr:
                    call_command("extract_pending_pdf_text")
                    self.assertEqual(mock_ocr.call_count, 1)

                    call_command("extract_pending_pdf_text")
                    # text_extracted=Trueによりクエリ対象から外れるため、2回目は呼ばれない。
                    self.assertEqual(mock_ocr.call_count, 1)
        doc.refresh_from_db()
        self.assertEqual(doc.extracted_text_normalized, "")
        self.assertTrue(doc.text_extracted)

    def test_ocr_exception_does_not_mark_extracted_so_it_retries_next_run(self):
        """OCR呼び出し自体が例外を送出した場合（タイムアウト等の一時的なエラー）は
        text_extractedをセットせず、次回バッチでも対象のままにする。"""
        doc = self._make_document("OCR失敗文書")
        with override_settings(OCR_ENABLED=True):
            with patch(
                "core.text_extraction_services.pdfplumber.open", return_value=self._mock_pdfplumber(""),
            ):
                with patch(
                    "core.management.commands.extract_pending_pdf_text.ocr_layout_services"
                    ".extract_text_and_layout_via_ocr",
                    side_effect=TimeoutError("vision api timeout"),
                ):
                    call_command("extract_pending_pdf_text")
        doc.refresh_from_db()
        self.assertEqual(doc.extracted_text_normalized, "")
        self.assertFalse(doc.text_extracted)

    def test_one_failure_does_not_stop_processing_of_other_documents(self):
        """1件目のpdfplumber解析が例外を送出しても、2件目は正常に処理される
        （「1件の抽出失敗でバッチ全体を止めない」設計方針）。"""
        broken_doc = self._make_document("破損文書")
        healthy_doc = self._make_document("正常文書")

        def selective_open(fileobj):
            # queryset は core.management.commands.extract_pending_pdf_text._process_model の
            # order_by("pk")によりpk昇順で処理されるため、1回目=broken_doc、2回目=healthy_doc。
            selective_open.calls += 1
            if selective_open.calls == 1:
                raise ValueError("corrupt pdf")
            return self._mock_pdfplumber("十分な文字数を含む正常な本文です。")

        selective_open.calls = 0

        with patch("core.text_extraction_services.pdfplumber.open", side_effect=selective_open):
            call_command("extract_pending_pdf_text")

        broken_doc.refresh_from_db()
        healthy_doc.refresh_from_db()
        self.assertFalse(broken_doc.text_extracted)
        self.assertTrue(healthy_doc.text_extracted)
        self.assertEqual(
            healthy_doc.extracted_text_normalized, normalize_for_search("十分な文字数を含む正常な本文です。")
        )

    def test_db_save_failure_does_not_stop_processing_of_other_documents(self):
        """本文抽出自体は成功しても、その結果をDBへ保存するobj.save(update_fields=...)が
        DB接続断（OperationalError）で失敗した場合でも、バッチコマンド全体が停止せず後続
        レコードの処理が継続することを確認する（_process_modelのobj.save呼び出しをtry/exceptで
        保護したことの回帰確認。保護が無いと、この1件の失敗で例外がhandle()まで伝播し
        コマンド全体が異常終了してしまう）。"""
        from documents.models import Document

        failing_doc = self._make_document("DB保存失敗文書")
        healthy_doc = self._make_document("DB保存成功文書")

        original_save = Document.save

        def selective_save(self, *args, **kwargs):
            # order_by("pk")によりfailing_docが先に処理されるため、1回目の呼び出しでのみ
            # 例外を送出する。
            selective_save.calls += 1
            if selective_save.calls == 1:
                raise OperationalError("connection lost")
            return original_save(self, *args, **kwargs)

        selective_save.calls = 0

        with patch(
            "core.text_extraction_services.pdfplumber.open",
            return_value=self._mock_pdfplumber("十分な文字数を含む本文テキストです。"),
        ):
            with patch.object(Document, "save", selective_save):
                call_command("extract_pending_pdf_text")

        failing_doc.refresh_from_db()
        healthy_doc.refresh_from_db()
        # 保存自体が失敗したため、抽出結果はDBに反映されないまま（次回バッチで再試行される）。
        self.assertFalse(failing_doc.text_extracted)
        self.assertTrue(healthy_doc.text_extracted)
        self.assertEqual(
            healthy_doc.extracted_text_normalized, normalize_for_search("十分な文字数を含む本文テキストです。")
        )


class ExtractPendingPdfTextTextdataTests(TestCase):
    """extract_pending_pdf_textコマンドのsettings.OCR_STORE_TEXTDATA・_should_store_textdata
    （documents.Document.privacy_flag連動）分岐＝OCR座標データ ocr_textdata の保存要否の単体テスト
    （監査 案3、2026-09-11。旧 ExtractPendingPdfTextEmbedTests〈searchable_file 生成〉を置き換え）。
    core.ocr_layout_services はモック化し、コマンドの分岐・DB更新の結果のみを検証する。
    """

    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.employee = Employee.objects.create_user(
            employee_no="1", name="テスト太郎", password="pass1234",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        self.group = Group.objects.create(code="A", name="分類Ａ", doc_kbn=DocKbn.DOCUMENT)
        self.category = Category.objects.create(
            code="001", name="カテゴリーＡ", group=self.group, doc_kbn=DocKbn.DOCUMENT
        )
        self.retention_period = RetentionPeriod.objects.create(
            kbn=RetentionKbn.DOCUMENT, period_value=1, period_unit=RetentionPeriodUnit.YEAR, display_order=1
        )

    def _make_document(self, title, privacy_flag=False):
        from documents.models import Document

        doc = Document(
            title=title, department=self.department, group=self.group, category=self.category,
            year=2026, retention_period=self.retention_period, uploader=self.employee,
            expiry_date=timezone.localdate(), privacy_flag=privacy_flag,
        )
        doc.file.save(f"{title}.pdf", ContentFile(b"%PDF-1.4 dummy"), save=False)
        doc.save()
        return doc

    @staticmethod
    def _mock_pdfplumber(text):
        mock_page = MagicMock()
        mock_page.extract_text.return_value = text
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__.return_value = mock_pdf
        mock_pdf.__exit__.return_value = False
        return mock_pdf

    _FAKE_TEXTDATAS = [TextDatas(1, 800, 1100, [TextData(10, 10, 100, 30, "OCR")])]

    def _run_ocr_batch(self, store_textdata):
        with override_settings(OCR_ENABLED=True, OCR_STORE_TEXTDATA=store_textdata):
            with patch(
                "core.text_extraction_services.pdfplumber.open", return_value=self._mock_pdfplumber(""),
            ):
                with patch(
                    "core.management.commands.extract_pending_pdf_text.ocr_layout_services"
                    ".extract_text_and_layout_via_ocr",
                    return_value=("座標付きOCRで抽出した本文", self._FAKE_TEXTDATAS),
                ):
                    call_command("extract_pending_pdf_text")

    def test_textdata_not_stored_when_setting_off(self):
        """既定（OCR_STORE_TEXTDATA=False）では本文抽出はされるが ocr_textdata は保存されない。"""
        doc = self._make_document("座標保存無効")
        self._run_ocr_batch(store_textdata=False)
        doc.refresh_from_db()
        self.assertEqual(doc.extracted_text_normalized, normalize_for_search("座標付きOCRで抽出した本文"))
        self.assertTrue(doc.text_extracted)
        self.assertIsNone(doc.ocr_textdata)

    def test_textdata_stored_for_document_with_privacy_flag(self):
        """当初実装は privacy_flag の影響なし：個人情報が含まれる文書（privacy_flag=True）でも
        OCR_STORE_TEXTDATA=True なら ocr_textdata を保存する（2026-09-11ユーザー方針。将来除外
        したくなった場合の切替点は _should_store_textdata）。"""
        doc = self._make_document("個人情報を含む文書", privacy_flag=True)
        self._run_ocr_batch(store_textdata=True)
        doc.refresh_from_db()
        self.assertEqual(doc.extracted_text_normalized, normalize_for_search("座標付きOCRで抽出した本文"))
        self.assertTrue(doc.text_extracted)
        self.assertEqual(
            doc.ocr_textdata, ocr_layout_services.textdatas_to_json(self._FAKE_TEXTDATAS)
        )

    def test_textdata_stored_when_enabled_and_not_private(self):
        doc = self._make_document("座標保存対象", privacy_flag=False)
        self._run_ocr_batch(store_textdata=True)
        doc.refresh_from_db()
        self.assertTrue(doc.text_extracted)
        self.assertEqual(
            doc.ocr_textdata, ocr_layout_services.textdatas_to_json(self._FAKE_TEXTDATAS)
        )

    def test_textdata_not_stored_when_ocr_returns_no_layout(self):
        """座標データが1件も取れなかった場合（全ページOCR失敗等）は ocr_textdata を null のままにする。"""
        doc = self._make_document("座標データ無し文書", privacy_flag=False)
        with override_settings(OCR_ENABLED=True, OCR_STORE_TEXTDATA=True):
            with patch(
                "core.text_extraction_services.pdfplumber.open", return_value=self._mock_pdfplumber(""),
            ):
                with patch(
                    "core.management.commands.extract_pending_pdf_text.ocr_layout_services"
                    ".extract_text_and_layout_via_ocr",
                    return_value=("", []),
                ):
                    call_command("extract_pending_pdf_text")
        doc.refresh_from_db()
        self.assertTrue(doc.text_extracted)
        self.assertIsNone(doc.ocr_textdata)


class ShouldStoreTextdataTests(TestCase):
    """extract_pending_pdf_textコマンドの_should_store_textdata の単体テスト（監査 案3、2026-09-11。
    旧 ShouldEmbedTests）。**当初実装は privacy_flag の影響なし＝常に True**（将来 privacy_flag=True
    を除外したくなったら同メソッドのコメントアウト行を有効化する）。"""

    def setUp(self):
        from core.management.commands.extract_pending_pdf_text import Command

        self.command = Command()

    def test_stores_regardless_of_privacy_flag(self):
        self.assertTrue(self.command._should_store_textdata(SimpleNamespace(privacy_flag=False)))
        self.assertTrue(self.command._should_store_textdata(SimpleNamespace(privacy_flag=True)))

    def test_stores_when_model_has_no_privacy_flag_field(self):
        self.assertTrue(self.command._should_store_textdata(SimpleNamespace()))


class TryImmediateTextLayerExtractionTests(TestCase):
    """core.text_extraction_services.try_immediate_text_layer_extraction
    （アップロード直後の同期テキスト層抽出、2026-08-10追加）の単体テスト。
    documents/contracts.UploadStep2View.postから呼ばれる（documents.tests参照）が、
    ロジック自体はモデル非依存のためここではDocumentで代表して検証する。
    """

    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.employee = Employee.objects.create_user(
            employee_no="1", name="テスト太郎", password="pass1234",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        self.group = Group.objects.create(code="A", name="分類Ａ", doc_kbn=DocKbn.DOCUMENT)
        self.category = Category.objects.create(
            code="001", name="カテゴリーＡ", group=self.group, doc_kbn=DocKbn.DOCUMENT
        )
        self.retention_period = RetentionPeriod.objects.create(
            kbn=RetentionKbn.DOCUMENT, period_value=1, period_unit=RetentionPeriodUnit.YEAR, display_order=1
        )
        from documents.models import Document

        self.doc = Document(
            title="対象文書", department=self.department, group=self.group, category=self.category,
            year=2026, retention_period=self.retention_period, uploader=self.employee,
            expiry_date=timezone.localdate(),
        )
        self.doc.file.save("a.pdf", ContentFile(b"%PDF-1.4 dummy"), save=False)
        self.doc.save()

    @staticmethod
    def _mock_pdfplumber(text):
        mock_page = MagicMock()
        mock_page.extract_text.return_value = text
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__.return_value = mock_pdf
        mock_pdf.__exit__.return_value = False
        return mock_pdf

    def test_text_layer_pdf_is_extracted_immediately(self):
        with patch(
            "core.text_extraction_services.pdfplumber.open",
            return_value=self._mock_pdfplumber("十分な文字数を含む本文テキストです。"),
        ):
            try_immediate_text_layer_extraction(self.doc, label="document")
        self.doc.refresh_from_db()
        self.assertEqual(
            self.doc.extracted_text_normalized, normalize_for_search("十分な文字数を含む本文テキストです。")
        )
        self.assertTrue(self.doc.text_extracted)

    def test_scanned_pdf_is_left_for_the_batch(self):
        """テキスト層が実質無い（スキャン文書）場合は何もせず、text_extracted=False のまま据え置く
        （OCR要否の判定はcore.management.commands.extract_pending_pdf_textに委ねる）。"""
        with patch("core.text_extraction_services.pdfplumber.open", return_value=self._mock_pdfplumber("")):
            try_immediate_text_layer_extraction(self.doc, label="document")
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.extracted_text_normalized, "")
        self.assertFalse(self.doc.text_extracted)

    def test_extraction_failure_does_not_raise(self):
        """解析失敗（破損PDF等）でも例外を伝播させない（アップロード処理自体を失敗させないため）。"""
        with patch("core.text_extraction_services.pdfplumber.open", side_effect=ValueError("corrupt pdf")):
            try_immediate_text_layer_extraction(self.doc, label="document")
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.extracted_text_normalized, "")
        self.assertFalse(self.doc.text_extracted)

    def test_oversized_file_skips_sync_extraction(self):
        """個別サイズ上限（SYNC_TEXT_EXTRACTION_MAX_BYTES）超過ならpdfplumberを呼ばずバッチに委ねる。"""
        with self.settings(SYNC_TEXT_EXTRACTION_MAX_BYTES=1), patch(
            "core.text_extraction_services.pdfplumber.open"
        ) as mock_open:
            try_immediate_text_layer_extraction(self.doc, label="document")
        mock_open.assert_not_called()
        self.doc.refresh_from_db()
        self.assertFalse(self.doc.text_extracted)

    def test_batch_skips_files_over_cumulative_limit(self):
        """1リクエスト累計上限を超えた分は同期抽出を飛ばす（先頭のファイルは抽出される）。"""
        from documents.models import Document

        second = Document(
            title="2件目", department=self.department, group=self.group, category=self.category,
            year=2026, retention_period=self.retention_period, uploader=self.employee,
            expiry_date=timezone.localdate(),
        )
        second.file.save("b.pdf", ContentFile(b"%PDF-1.4 dummy"), save=False)
        second.save()
        size = self.doc.file.size
        with self.settings(SYNC_TEXT_EXTRACTION_MAX_TOTAL_BYTES=size), patch(
            "core.text_extraction_services.pdfplumber.open",
            return_value=self._mock_pdfplumber("十分な文字数を含む本文テキストです。"),
        ):
            try_immediate_text_layer_extraction_batch([self.doc, second], label="document")
        self.doc.refresh_from_db()
        second.refresh_from_db()
        self.assertTrue(self.doc.text_extracted)
        self.assertFalse(second.text_extracted)


class IsImageFilenameTests(TestCase):
    """保管画面２・編集画面の実画像プレビュー可否判定（documents/contracts.views参照）。"""

    def test_common_raster_extensions_are_images(self):
        for name in ["a.jpg", "a.JPG", "a.jpeg", "a.png", "a.gif", "a.bmp", "a.webp"]:
            self.assertTrue(is_image_filename(name), name)

    def test_non_image_extensions_are_not_images(self):
        for name in ["a.pdf", "a.docx", "a.txt", "noext"]:
            self.assertFalse(is_image_filename(name), name)

    def test_svg_is_excluded_for_xss_safety(self):
        """SVGはインラインscriptを含められるため、ブラウザに直接読み込ませるプレビュー用途では
        あえて画像として扱わない（core.file_type_services.is_image_filename docstring参照）。"""
        self.assertFalse(is_image_filename("a.svg"))


class SafeInlineFileServingTests(TestCase):
    """セキュリティレビュー H-3: `core.file_serving`。インライン配信は PDF・ラスター画像に
    限定し、それ以外は添付ダウンロードへ倒す。"""

    def test_pdf_and_images_stay_inline(self):
        for name in ["a.pdf", "a.PDF", "b.png", "c.jpg", "d.jpeg", "e.gif", "f.bmp", "g.webp"]:
            self.assertFalse(
                resolve_as_attachment(wants_inline=True, filename=name), name
            )

    def test_active_content_falls_back_to_attachment_even_when_inline_requested(self):
        for name in ["x.html", "x.htm", "x.svg", "x.xml", "x.js", "x.docx", "x.xlsx", "noext"]:
            self.assertTrue(
                resolve_as_attachment(wants_inline=True, filename=name), name
            )

    def test_download_intent_is_always_attachment(self):
        self.assertTrue(resolve_as_attachment(wants_inline=False, filename="a.pdf"))

    def test_security_headers_applied(self):
        from django.http import HttpResponse

        resp = apply_file_response_security_headers(HttpResponse(b"x"))
        self.assertEqual(resp.headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("script-src 'none'", resp.headers["Content-Security-Policy"])
        self.assertIn("object-src 'none'", resp.headers["Content-Security-Policy"])


class BlockedUploadValidationTests(TestCase):
    """セキュリティレビュー H-3: `core.upload_validation`。能動的コンテンツはアップロード時点で拒否。"""

    def test_active_content_extensions_are_blocked(self):
        for name in ["poc.html", "POC.HTM", "a.xhtml", "a.svg", "a.svgz", "a.js", "a.hta", "a.swf"]:
            self.assertIsNotNone(blocked_upload_message([name]), name)

    def test_ordinary_business_formats_are_allowed(self):
        for name in ["a.pdf", "a.docx", "a.xlsx", "a.pptx", "a.png", "a.txt", "a.zip", "a.csv", "noext"]:
            self.assertIsNone(blocked_upload_message([name]), name)

    def test_message_lists_only_the_blocked_names(self):
        msg = blocked_upload_message(["ok.pdf", "bad.html", "also.svg"])
        self.assertIn("bad.html", msg)
        self.assertIn("also.svg", msg)
        self.assertNotIn("ok.pdf", msg)


class NonPdfUploadValidationTests(TestCase):
    """保管画面１のサーバー側PDF限定（2026-09-30）。JSを迂回したPOST・チャンクAPIでも拒否する。"""

    def test_pdf_only_allowed_case_insensitive(self):
        self.assertIsNone(non_pdf_upload_message(["a.pdf", "B.PDF"]))

    def test_non_pdf_rejected_and_only_those_listed(self):
        msg = non_pdf_upload_message(["ok.pdf", "a.png", "b.docx", "noext"])
        self.assertIn("a.png", msg)
        self.assertIn("b.docx", msg)
        self.assertIn("noext", msg)
        self.assertNotIn("ok.pdf", msg)

    def test_step1_post_rejects_non_pdf_for_documents(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from accounts.models import Employee, Position, Rank
        from organizations.models import Department

        dept = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        Employee.objects.create_user(
            employee_no="1", name="テスト太郎", password="pass1234",
            department=dept, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        self.client.login(username="1", password="pass1234")
        resp = self.client.post(
            "/documents/upload/step1/",
            {"files": [SimpleUploadedFile("a.png", b"x", content_type="image/png")]},
        )
        self.assertEqual(resp.status_code, 200)  # redirectせず画面1を再描画
        self.assertContains(resp, "PDFファイル以外は保管できません")
        self.assertEqual(self.client.session.get("documents_pending_upload", []), [])

        ok = self.client.post(
            "/documents/upload/step1/",
            {"files": [SimpleUploadedFile("a.pdf", b"%PDF-1.4", content_type="application/pdf")]},
        )
        self.assertEqual(ok.status_code, 302)

    def test_chunk_api_rejects_non_pdf(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from accounts.models import Employee, Position, Rank
        from organizations.models import Department

        dept = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        Employee.objects.create_user(
            employee_no="1", name="テスト太郎", password="pass1234",
            department=dept, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        self.client.login(username="1", password="pass1234")
        resp = self.client.post(
            "/documents/upload/chunk/",
            {
                "upload_id": "abc-123", "file_name": "a.png", "chunk_index": "0",
                "total_chunks": "1", "file": SimpleUploadedFile("blob", b"x"),
            },
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("PDF", resp.json()["message"])


class HealthCheckViewTests(TestCase):
    """未実装改善候補の棚卸しで発見・2026-08-12追加。原本HTML/xlsxには存在しない、監視ツール向け
    死活監視エンドポイント（core.views.HealthCheckView）。"""

    def test_ok_without_login(self):
        """監視ツールは職員番号ログインを行わないため、未ログインでも200であること。"""
        response = self.client.get("/healthz/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "database": "ok"})

    def test_db_failure_returns_503(self):
        with patch("core.views.connection.cursor", side_effect=OperationalError("down")):
            response = self.client.get("/healthz/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["status"], "error")


class JsStaticTagTests(TestCase):
    """RELEASE_PREP_NOTES.md「1.」static/js minify対応。core.templatetags.js_static.js_staticは
    DEBUG時はソース(.js)を、本番(DEBUG=False)は.min.jsを参照する。"""

    def _render(self):
        template = Template("{% load js_static %}{% js_static 'js/common.js' %}")
        return template.render(Context({}))

    @override_settings(DEBUG=True)
    def test_debug_uses_source_file(self):
        self.assertTrue(self._render().endswith("js/common.js"))

    @override_settings(DEBUG=False)
    def test_non_debug_uses_min_file(self):
        self.assertTrue(self._render().endswith("js/common.min.js"))


class MinifyStaticJsCommandTests(TestCase):
    """RELEASE_PREP_NOTES.md「1.」static/js minify対応。core.management.commands.minify_static_js。
    settings.BASE_DIR配下のstatic/js/を対象にするコマンドのため、実ソースツリーを汚さないよう
    BASE_DIRをテスト用の一時ディレクトリへ差し替えて検証する。"""

    def test_minify_generates_min_js_alongside_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            js_dir = Path(tmp) / "static" / "js"
            js_dir.mkdir(parents=True)
            source = js_dir / "sample.js"
            source.write_text("function f() {\n  return 1;\n}\n", encoding="utf-8")

            with override_settings(BASE_DIR=Path(tmp)):
                call_command("minify_static_js")

            dest = js_dir / "sample.min.js"
            self.assertTrue(dest.exists())
            self.assertLess(len(dest.read_text(encoding="utf-8")), len(source.read_text(encoding="utf-8")))

    def test_existing_min_js_is_not_treated_as_a_source_file(self):
        """入力に*.min.jsしか無ければ、それを再minifyせず「対象なし」として扱う。"""
        with tempfile.TemporaryDirectory() as tmp:
            js_dir = Path(tmp) / "static" / "js"
            js_dir.mkdir(parents=True)
            (js_dir / "sample.min.js").write_text("var x=1;", encoding="utf-8")

            with override_settings(BASE_DIR=Path(tmp)):
                with self.assertRaises(CommandError):
                    call_command("minify_static_js")

    def test_no_source_files_raises_command_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "static" / "js").mkdir(parents=True)
            with override_settings(BASE_DIR=Path(tmp)):
                with self.assertRaises(CommandError):
                    call_command("minify_static_js")


class SeedInitialMastersCommandTests(TestCase):
    """RELEASE_PREP_NOTES.md「2.」本番の初期マスタデータ投入。
    core.management.commands.seed_initial_masters。"""

    def test_creates_document_retention_periods(self):
        call_command("seed_initial_masters")

        periods = list(
            RetentionPeriod.objects.filter(kbn=RetentionKbn.DOCUMENT, doc_name="", is_deleted=False).order_by(
                "display_order"
            )
        )
        self.assertEqual(
            [(p.period_value, p.period_unit) for p in periods],
            [
                (1, RetentionPeriodUnit.MONTH),
                (1, RetentionPeriodUnit.YEAR),
                (3, RetentionPeriodUnit.YEAR),
                (5, RetentionPeriodUnit.YEAR),
                (10, RetentionPeriodUnit.YEAR),
                (None, RetentionPeriodUnit.PERMANENT),
            ],
        )

    def test_rerun_is_idempotent(self):
        call_command("seed_initial_masters")
        call_command("seed_initial_masters")

        self.assertEqual(
            RetentionPeriod.objects.filter(kbn=RetentionKbn.DOCUMENT, doc_name="", is_deleted=False).count(),
            6,
        )

    def test_does_not_touch_eapproval_or_contract_scope(self):
        """電子決裁（kbn=EAPPROVAL）は恒久的にスコープ外、契約書は選択式ではなく固定年数
        （settings.CONTRACT_RETENTION_YEARS）のため、このコマンドはdocument以外を一切作らない。"""
        call_command("seed_initial_masters")
        self.assertFalse(RetentionPeriod.objects.exclude(kbn=RetentionKbn.DOCUMENT).exists())
