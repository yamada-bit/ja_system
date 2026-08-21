from unittest import mock

from django.test import TestCase

from accounts.models import Employee, Position, Rank
from audit.models import AuditLog
from audit.services import log as audit_log
from organizations.models import Department
from permissions.models import PermissionProfile, PermissionRole


class AuditLogServiceTests(TestCase):
    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.employee = Employee.objects.create_user(
            employee_no="1", name="テスト太郎", password="x",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )

    def test_log_creates_record_with_snapshot_fields(self):
        """employee_no/employee_name/department_nameは、後から職員名や部署が変わっても
        当時の記録が残るよう非正規化スナップショットとして保存する。
        """
        audit_log(
            employee=self.employee,
            action="保管画面２ 登録",
            event_message="文書「テスト文書」を保管しました。",
            personal_info_flag=True,
        )
        entry = AuditLog.objects.get()
        self.assertEqual(entry.employee_no, "1")
        self.assertEqual(entry.employee_name, "テスト太郎")
        self.assertEqual(entry.department_name, "総務部")
        self.assertEqual(entry.action, "保管画面２ 登録")
        self.assertTrue(entry.personal_info_flag)

    def test_log_failure_does_not_raise(self):
        """監査ログの記録失敗で本処理まで失敗させない設計（例外は握りつぶしログにのみ残す）。"""
        with mock.patch("audit.services.AuditLog.objects.create", side_effect=Exception("db down")):
            try:
                audit_log(employee=self.employee, action="テスト", event_message="テスト")
            except Exception:
                self.fail("audit_log()は例外を伝播させてはならない")
        self.assertEqual(AuditLog.objects.count(), 0)


class AuditLogSettingsMenuAccessControlTests(TestCase):
    """設定メニュー「操作履歴ログ」は管理者のみ表示・利用可（xlsx 設定メニュー!B46以降）。
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

    def test_manager_cannot_access_log_list(self):
        self._login_as(PermissionRole.MANAGER)
        response = self.client.get("/audit/")
        self.assertEqual(response.status_code, 403)

    def test_staff_cannot_access_log_csv_export(self):
        self._login_as(PermissionRole.STAFF)
        response = self.client.get("/audit/csv/")
        self.assertEqual(response.status_code, 403)

    def test_admin_can_access_log_list(self):
        self._login_as(PermissionRole.ADMIN)
        response = self.client.get("/audit/")
        self.assertEqual(response.status_code, 200)


class AuditLogListViewTests(TestCase):
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
        AuditLog.objects.create(
            employee_no="1", employee_name="テスト太郎", department_name="本店|総務部",
            action="ログイン", event_message="ログイン", personal_info_flag=False,
        )
        AuditLog.objects.create(
            employee_no="2", employee_name="山田花子", department_name="本店|総務部",
            action="文書 ダウンロード", event_message="ファイル名：規定一覧", personal_info_flag=True,
        )

    def test_filter_by_employee_name(self):
        response = self.client.get("/audit/", {"employee_name": "山田"})
        self.assertContains(response, "文書 ダウンロード")
        self.assertNotContains(response, "ログイン</td>")

    def test_filter_by_full_name_ignores_fullwidth_space(self):
        """xlsx 操作履歴ログ!B39-40(Rev1.1)「姓と名を全角スペース区切りでフルネーム検索可能」。"""
        response = self.client.get("/audit/", {"employee_name": "山田　花子"})
        self.assertContains(response, "文書 ダウンロード")
        self.assertNotContains(response, "ログイン</td>")

    def test_filter_by_employee_no_exact_match(self):
        """xlsx 操作履歴ログ!B36-37(Rev1.1)「職員番号の完全一致検索とする」。"""
        response = self.client.get("/audit/", {"employee_no": "2"})
        self.assertContains(response, "文書 ダウンロード")
        self.assertNotContains(response, "ログイン</td>")
        # 部分一致ではないため"1"や"22"では一致しない。
        response_partial = self.client.get("/audit/", {"employee_no": "22"})
        self.assertNotContains(response_partial, "文書 ダウンロード")

    def test_filter_by_event_message_and_search(self):
        """xlsx 操作履歴ログ!B42-43(Rev1.1)「イベントメッセージの部分一致検索、スペース区切りのAND検索」。"""
        response = self.client.get("/audit/", {"event_message": "ファイル名 規定一覧"})
        self.assertContains(response, "文書 ダウンロード")
        self.assertNotContains(response, "ログイン</td>")
        response_no_match = self.client.get("/audit/", {"event_message": "ファイル名 存在しない語"})
        self.assertNotContains(response_no_match, "文書 ダウンロード")

    def test_filter_by_personal_info_flag(self):
        """xlsx 操作履歴ログ!B43「チェックを入れて検索すると、個人情報書類フラグがセットされている
        文書を扱ったイベントのみ抽出する」。
        """
        response = self.client.get("/audit/", {"personal_info_flag": "on"})
        self.assertContains(response, "山田花子")
        # ログイン中ユーザー名(ヘッダーのuser-info)自体は「テスト太郎」を含むため、
        # 一覧テーブルの行を特定できる文言で絞り込み結果を確認する。
        self.assertNotContains(response, "ログイン</td>")


class AuditLogCsvExportViewTests(TestCase):
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
        AuditLog.objects.create(
            employee_no="1", employee_name="テスト太郎", department_name="本店|総務部",
            action="ログイン", event_message="ログイン", personal_info_flag=False,
        )
        AuditLog.objects.create(
            employee_no="2", employee_name="山田花子", department_name="本店|総務部",
            action="文書 ダウンロード", event_message="ファイル名：規定一覧", personal_info_flag=True,
        )

    def test_csv_export_contains_filtered_rows(self):
        """一覧画面と同じ検索条件（絞込み結果）をCSV化する（accounts.StaffCsvExportViewと同方針）。"""
        response = self.client.get("/audit/csv/", {"employee_name": "山田"})
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8-sig")
        content = response.content.decode("utf-8-sig")
        self.assertIn("山田花子", content)
        self.assertNotIn("ログイン,ログイン", content)

    def test_csv_export_records_audit_log(self):
        """CSV出力自体も職員名等の個人情報を含む一覧のファイル出力のため、監査ログに記録する。"""
        before_count = AuditLog.objects.count()
        self.client.get("/audit/csv/")
        entry = AuditLog.objects.order_by("-id").first()
        self.assertEqual(AuditLog.objects.count(), before_count + 1)
        self.assertEqual(entry.action, "操作履歴ログ CSV出力")
        self.assertTrue(entry.personal_info_flag)
