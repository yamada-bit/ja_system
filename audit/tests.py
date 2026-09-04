import datetime
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from accounts.models import Employee, Position, Rank
from audit.models import AuditLog
from audit.services import build_diff_message
from audit.services import log as audit_log
from audit.services import log_raw as audit_log_raw
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
            action="保管画面２　登録",
            event_message="文書「テスト文書」を保管しました。",
            personal_info_flag=True,
        )
        entry = AuditLog.objects.get()
        self.assertEqual(entry.employee_no, "1")
        self.assertEqual(entry.employee_name, "テスト太郎")
        self.assertEqual(entry.department_name, "総務部")
        self.assertEqual(entry.action, "保管画面２　登録")
        self.assertTrue(entry.personal_info_flag)

    def test_log_failure_does_not_raise(self):
        """監査ログの記録失敗で本処理まで失敗させない設計（例外は握りつぶしログにのみ残す）。"""
        with mock.patch("audit.services.AuditLog.objects.create", side_effect=Exception("db down")):
            try:
                audit_log(employee=self.employee, action="テスト", event_message="テスト")
            except Exception:
                self.fail("audit_log()は例外を伝播させてはならない")
        self.assertEqual(AuditLog.objects.count(), 0)

    def test_log_raw_creates_record_without_employee_instance(self):
        """log_raw()は認証済みEmployeeインスタンスを経由できない場面向け（core.management.commands.
        purge_expired_deleted_records、accounts.views.LoginView.form_invalid等）。log()を介さず
        職員番号/職員名/部署名を直接指定してもAuditLogが作成されることを確認する。
        """
        audit_log_raw(
            employee_no="(自動バッチ)",
            employee_name="(自動バッチ)",
            department_name="(自動バッチ)",
            action="物理削除バッチ　完全削除",
            event_message="文書「テスト」を完全に削除しました。",
            personal_info_flag=True,
        )
        entry = AuditLog.objects.get()
        self.assertEqual(entry.employee_no, "(自動バッチ)")
        self.assertEqual(entry.action, "物理削除バッチ　完全削除")
        self.assertTrue(entry.personal_info_flag)

    def test_log_raw_failure_does_not_raise(self):
        with mock.patch("audit.services.AuditLog.objects.create", side_effect=Exception("db down")):
            try:
                audit_log_raw(
                    employee_no="1", employee_name="不明", department_name="不明",
                    action="テスト", event_message="テスト",
                )
            except Exception:
                self.fail("log_raw()は例外を伝播させてはならない")
        self.assertEqual(AuditLog.objects.count(), 0)


class BuildDiffMessageRedactionTests(TestCase):
    """xlsx 操作履歴ログ!B69-70 の「更新した項目名：更新前データ -> 更新後データ」ルールを
    パスワード等の機微項目へ適用すると認証情報が平文でログに残る（簡易設計指示書レビュー指摘
    2-1）。build_diff_message が最終防衛としてマスクすることを確認する。
    """

    def test_non_sensitive_change_is_kept_verbatim(self):
        message = build_diff_message("職員：太郎(1)", [("氏名", "旧名", "新名")])
        self.assertEqual(message, "職員：太郎(1),氏名：旧名 -> 新名")

    def test_password_label_value_is_masked_even_if_caller_passes_raw_value(self):
        message = build_diff_message(
            "職員：太郎(1)", [("パスワード", "oldsecret", "newsecret")]
        )
        self.assertNotIn("oldsecret", message)
        self.assertNotIn("newsecret", message)
        self.assertEqual(message, "職員：太郎(1),パスワード：(変更あり) -> (変更あり)")

    def test_existing_marker_value_is_unchanged(self):
        """既存の呼び出し（build_staff_edit_diff_message）が渡すマーカー値では文言が変わらない。"""
        message = build_diff_message(
            "職員：太郎(1)", [("パスワード", "(変更あり)", "(変更あり)")]
        )
        self.assertEqual(message, "職員：太郎(1),パスワード：(変更あり) -> (変更あり)")

    def test_label_match_is_case_insensitive_and_partial(self):
        for label in ("Password", "新パスワード", "PWD(確認)"):
            with self.subTest(label=label):
                message = build_diff_message("対象", [(label, "before", "after")])
                self.assertNotIn("before", message)
                self.assertIn("(変更あり) -> (変更あり)", message)

    def test_sensitive_and_normal_changes_mixed(self):
        message = build_diff_message(
            "職員：太郎(1)",
            [("氏名", "旧名", "新名"), ("パスワード", "raw", "raw2")],
        )
        self.assertEqual(
            message, "職員：太郎(1),氏名：旧名 -> 新名,パスワード：(変更あり) -> (変更あり)"
        )


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
            action="文書　ダウンロード", event_message="ファイル名：規定一覧", personal_info_flag=True,
        )

    def test_no_filter_returns_all_records(self):
        """audit/views.py・audit/services.pyのコメントが警告する「request.GET or Noneにすると
        初回アクセス時にフォームが未バインド扱いになりフィルタが一切効かなくなる」回帰の検知テスト。
        パラメータ無しGETで全件表示されることを確認する。"""
        response = self.client.get("/audit/")
        self.assertContains(response, "文書　ダウンロード")
        self.assertContains(response, "ログイン</td>")

    def test_filter_by_employee_name(self):
        response = self.client.get("/audit/", {"employee_name": "山田"})
        self.assertContains(response, "文書　ダウンロード")
        self.assertNotContains(response, "ログイン</td>")

    def test_filter_by_full_name_ignores_fullwidth_space(self):
        """xlsx 操作履歴ログ!B39-40(Rev1.1)「姓と名を全角スペース区切りでフルネーム検索可能」。"""
        response = self.client.get("/audit/", {"employee_name": "山田　花子"})
        self.assertContains(response, "文書　ダウンロード")
        self.assertNotContains(response, "ログイン</td>")

    def test_filter_by_employee_no_exact_match(self):
        """xlsx 操作履歴ログ!B36-37(Rev1.1)「職員番号の完全一致検索とする」。"""
        response = self.client.get("/audit/", {"employee_no": "2"})
        self.assertContains(response, "文書　ダウンロード")
        self.assertNotContains(response, "ログイン</td>")
        # 部分一致ではないため"1"や"22"では一致しない。
        response_partial = self.client.get("/audit/", {"employee_no": "22"})
        self.assertNotContains(response_partial, "文書　ダウンロード")

    def test_filter_by_event_message_and_search(self):
        """xlsx 操作履歴ログ!B42-43(Rev1.1)「イベントメッセージの部分一致検索、スペース区切りのAND検索」。"""
        response = self.client.get("/audit/", {"event_message": "ファイル名 規定一覧"})
        self.assertContains(response, "文書　ダウンロード")
        self.assertNotContains(response, "ログイン</td>")
        response_no_match = self.client.get("/audit/", {"event_message": "ファイル名 存在しない語"})
        self.assertNotContains(response_no_match, "文書　ダウンロード")

    def test_filter_by_personal_info_flag(self):
        """xlsx 操作履歴ログ!B43「チェックを入れて検索すると、個人情報書類フラグがセットされている
        文書を扱ったイベントのみ抽出する」。
        """
        response = self.client.get("/audit/", {"personal_info_flag": "on"})
        self.assertContains(response, "山田花子")
        # ログイン中ユーザー名(ヘッダーのuser-info)自体は「テスト太郎」を含むため、
        # 一覧テーブルの行を特定できる文言で絞り込み結果を確認する。
        self.assertNotContains(response, "ログイン</td>")

    def test_filter_by_date_range(self):
        """xlsx 操作履歴ログ!B33-34(Rev1.1)「操作日(開始)/操作日(終了)」の日付範囲検索。
        フォーム定義の先頭2フィールドだが、AuditLogListViewTests/AuditLogCsvExportViewTestsの
        どのテストからも一度も指定されておらず未検証だった（テストカバレッジ棚卸しで発見、
        2026-08-26追加）。timestampはauto_now_addのため、作成後にqueryset.update()で
        任意の日時へ書き換える。

        書き換え先の日時は`retention_cutoff_date()`（既定3ヵ月）より新しい範囲に取る
        （xlsx 操作履歴ログ!B51-52の保持下限より古い日付を指定してもヒットしなくなったため。
        2026-09-03）。
        """
        today = timezone.localdate()
        older = today - datetime.timedelta(days=40)
        newer = today - datetime.timedelta(days=30)
        login_entry = AuditLog.objects.get(action="ログイン")
        download_entry = AuditLog.objects.get(action="文書　ダウンロード")
        AuditLog.objects.filter(pk=login_entry.pk).update(
            timestamp=timezone.make_aware(datetime.datetime.combine(older, datetime.time(9, 0)))
        )
        AuditLog.objects.filter(pk=download_entry.pk).update(
            timestamp=timezone.make_aware(datetime.datetime.combine(newer, datetime.time(9, 0)))
        )
        response = self.client.get(
            "/audit/",
            {
                "date_start": (newer - datetime.timedelta(days=2)).isoformat(),
                "date_end": (newer + datetime.timedelta(days=2)).isoformat(),
            },
        )
        self.assertContains(response, "文書　ダウンロード")
        self.assertNotContains(response, "ログイン</td>")

    def test_pagination_splits_across_pages(self):
        """CLAUDE.md「一覧画面のページネーションはDjango Paginatorで実装する」の動作確認
        （AuditLogListView.PAGE_SIZE=100超のデータで2ページ目に分かれること）。setUpの2件に
        加え、100件ちょうどでpage=2が1件になるよう99件追加する。
        """
        AuditLog.objects.bulk_create(
            [
                AuditLog(
                    employee_no=str(100 + i), employee_name=f"追加太郎{i}", department_name="本店|総務部",
                    action="ログイン", event_message="ログイン", personal_info_flag=False,
                )
                for i in range(99)
            ]
        )
        self.assertEqual(AuditLog.objects.count(), 101)

        page1 = self.client.get("/audit/")
        self.assertEqual(len(page1.context["page_obj"]), 100)
        self.assertEqual(page1.context["page_obj"].paginator.num_pages, 2)

        page2 = self.client.get("/audit/", {"page": "2"})
        self.assertEqual(len(page2.context["page_obj"]), 1)


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
            action="文書　ダウンロード", event_message="ファイル名：規定一覧", personal_info_flag=True,
        )

    def test_csv_export_with_no_matching_rows_returns_header_only(self):
        """検索条件に一致するレコードが無い場合、ヘッダー行のみのCSVを返すこと
        （フィルタ側で例外にならず正常系として完結することの確認）。"""
        response = self.client.get("/audit/csv/", {"employee_name": "存在しない職員"})
        content = response.content.decode("utf-8-sig")
        lines = [line for line in content.splitlines() if line]
        self.assertEqual(len(lines), 1)
        self.assertIn("操作日時,職員番号,部署名,職員名,操作内容,イベントメッセージ,個人情報", lines[0])

    def test_csv_export_contains_filtered_rows(self):
        """一覧画面と同じ検索条件（絞込み結果）をCSV化する（accounts.StaffCsvExportViewと同方針）。"""
        response = self.client.get("/audit/csv/", {"employee_name": "山田"})
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8-sig")
        content = response.content.decode("utf-8-sig")
        self.assertIn("山田花子", content)
        self.assertNotIn("ログイン,ログイン", content)

    def test_csv_export_escapes_formula_prefixed_employee_name(self):
        """職員名が「=」等で始まる場合、CSVインジェクション対策としてシングルクォートを付与し、
        Excel側にテキストとして扱わせる（2026-08-24追加、core.csv_services.sanitize_csv_row参照）。"""
        AuditLog.objects.create(
            employee_no="3", employee_name="=cmd|'/c calc'!A1", department_name="本店|総務部",
            action="文書　登録", event_message="文書「テスト」を保管しました。",
            personal_info_flag=False,
        )
        response = self.client.get("/audit/csv/")
        content = response.content.decode("utf-8-sig")
        self.assertIn("'=cmd|'/c calc'!A1", content)

    def test_csv_export_excludes_records_older_than_retention(self):
        """xlsx 操作履歴ログ!B51-52「最大保存件数(=CSV出力最大件数)＝3ヵ月分」。
        保持下限より古いレコードはCSV出力の対象からも外れる。"""
        old_entry = AuditLog.objects.get(action="ログイン")
        AuditLog.objects.filter(pk=old_entry.pk).update(
            timestamp=timezone.now() - datetime.timedelta(days=200)
        )
        response = self.client.get("/audit/csv/")
        content = response.content.decode("utf-8-sig")
        self.assertIn("山田花子", content)  # 直近のレコードは出る
        self.assertNotIn("ログイン,ログイン", content)  # 200日前のログイン行は出ない

    def test_csv_export_records_audit_log(self):
        """CSV出力自体も職員名等の個人情報を含む一覧のファイル出力のため、監査ログに記録する。"""
        before_count = AuditLog.objects.count()
        self.client.get("/audit/csv/")
        entry = AuditLog.objects.order_by("-id").first()
        self.assertEqual(AuditLog.objects.count(), before_count + 1)
        self.assertEqual(entry.action, "操作履歴ログ　CSV出力")
        self.assertTrue(entry.personal_info_flag)


class AuditLogRetentionTests(TestCase):
    """xlsx 操作履歴ログ!B51-52「操作履歴ログの最大保存件数(=CSV出力最大件数)設定値は、初期値を
    3ヵ月分とし、設定ファイル等で定義し、先方より変更依頼を受けた際に容易に変更できること」。
    「3ヵ月分」を settings.AUDIT_LOG_RETENTION_MONTHS（.env経由、既定3）ヵ月で表現し、
    保持下限より古いログは一覧・CSVから除外＋日次バッチで物理削除する（2026-09-03実装）。
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

    def _entry(self, action, days_ago):
        entry = AuditLog.objects.create(
            employee_no="1", employee_name="テスト太郎", department_name="本店|総務部",
            action=action, event_message=action,
        )
        AuditLog.objects.filter(pk=entry.pk).update(
            timestamp=timezone.now() - datetime.timedelta(days=days_ago)
        )
        return entry

    def test_list_view_excludes_records_older_than_retention(self):
        self._entry("古いイベント", days_ago=200)
        self._entry("新しいイベント", days_ago=10)
        response = self.client.get("/audit/")
        self.assertContains(response, "新しいイベント")
        self.assertNotContains(response, "古いイベント")

    def test_retention_cutoff_is_configurable(self):
        """先方の変更依頼に応じて .env の1行で保持期間を変えられること（@override_settings で代用）。"""
        self._entry("120日前イベント", days_ago=120)
        with self.settings(AUDIT_LOG_RETENTION_MONTHS=6):
            response = self.client.get("/audit/")
            self.assertContains(response, "120日前イベント")
        with self.settings(AUDIT_LOG_RETENTION_MONTHS=3):
            response = self.client.get("/audit/")
            self.assertNotContains(response, "120日前イベント")

    def test_purge_command_deletes_only_expired_rows(self):
        old = self._entry("古いイベント", days_ago=200)
        recent = self._entry("新しいイベント", days_ago=10)
        from django.core.management import call_command

        call_command("purge_expired_audit_logs")
        self.assertFalse(AuditLog.objects.filter(pk=old.pk).exists())
        self.assertTrue(AuditLog.objects.filter(pk=recent.pk).exists())

    def test_purge_command_does_not_write_its_own_audit_log(self):
        """パージ自体は「操作」ではなく保守バッチのため操作履歴ログに記録しない
        （記録すると次回パージ対象になって増えるだけ）。"""
        self._entry("古いイベント", days_ago=200)
        from django.core.management import call_command

        call_command("purge_expired_audit_logs")
        self.assertFalse(AuditLog.objects.filter(action__icontains="パージ").exists())
        self.assertEqual(AuditLog.objects.count(), 0)
