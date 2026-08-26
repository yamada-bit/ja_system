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
from documents.forms import SearchForm
from documents.search_services import build_queryset
from documents.services import calculate_expiry_date, can_delete, used_retention_periods
from masters.models import Category, DocKbn, Group, RetentionKbn, RetentionPeriod, RetentionPeriodUnit, SystemSetting
from organizations.models import Department
from permissions.models import PermissionProfile, PermissionRole


class CalculateExpiryDateTests(TestCase):
    def _period(self, unit, value=None):
        return RetentionPeriod.objects.create(
            kbn=RetentionKbn.DOCUMENT, period_value=value, period_unit=unit, display_order=1
        )

    def test_year_unit_adds_years(self):
        period = self._period(RetentionPeriodUnit.YEAR, value=3)
        result = calculate_expiry_date(datetime.date(2026, 8, 9), period)
        self.assertEqual(result, datetime.date(2029, 8, 9))

    def test_month_unit_adds_months_across_year_boundary(self):
        period = self._period(RetentionPeriodUnit.MONTH, value=1)
        result = calculate_expiry_date(datetime.date(2026, 12, 20), period)
        self.assertEqual(result, datetime.date(2027, 1, 20))

    def test_permanent_uses_system_setting_years(self):
        """xlsx 保存期間設定!B74「「永年」設定値は初期値50年、設定ファイル等で容易に変更できること」。"""
        period = self._period(RetentionPeriodUnit.PERMANENT)
        result = calculate_expiry_date(datetime.date(2026, 1, 1), period)
        self.assertEqual(result, datetime.date(2076, 1, 1))

    def test_permanent_respects_custom_system_setting(self):
        SystemSetting.objects.create(retention_permanent_years=30)
        period = self._period(RetentionPeriodUnit.PERMANENT)
        result = calculate_expiry_date(datetime.date(2026, 1, 1), period)
        self.assertEqual(result, datetime.date(2056, 1, 1))

    def test_leap_day_start_date_falls_back_to_feb28(self):
        period = self._period(RetentionPeriodUnit.YEAR, value=1)
        result = calculate_expiry_date(datetime.date(2028, 2, 29), period)
        self.assertEqual(result, datetime.date(2029, 2, 28))


class CanDeleteBoundaryTests(TestCase):
    """documents.services.can_deleteのDELETE_WINDOW_DAYS境界値（テストカバレッジ棚卸しで発見：
    「7日未満」「8日経過」は既存テストでカバーされていたが、ちょうどDELETE_WINDOW_DAYS
    （7日）経過した瞬間の境界〈timezone.now() - save_date < 7日、の等号側〉が未検証だった）。
    """

    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.employee = Employee.objects.create_user(
            employee_no="1", name="テスト太郎", password="x",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        group = Group.objects.create(code="A", name="分類Ａ", doc_kbn=DocKbn.DOCUMENT)
        category = Category.objects.create(code="001", name="カテゴリーＡ", group=group, doc_kbn=DocKbn.DOCUMENT)
        retention_period = RetentionPeriod.objects.create(
            kbn=RetentionKbn.DOCUMENT, period_value=1, period_unit=RetentionPeriodUnit.YEAR, display_order=1
        )
        from documents.models import Document

        self.document = Document(
            title="境界確認用", department=self.department, group=group, category=category,
            year=2026, retention_period=retention_period, uploader=self.employee,
            expiry_date=datetime.date(2030, 1, 1),
        )
        self.document.file.save("doc.pdf", ContentFile(b"dummy"), save=False)
        self.document.save()

    def test_exactly_at_window_boundary_is_not_deletable(self):
        from documents.models import Document

        Document.objects.filter(pk=self.document.pk).update(
            save_date=timezone.now() - datetime.timedelta(days=7)
        )
        self.document.refresh_from_db()
        self.assertFalse(can_delete(self.document))

    def test_just_under_window_boundary_is_still_deletable(self):
        from documents.models import Document

        Document.objects.filter(pk=self.document.pk).update(
            save_date=timezone.now() - datetime.timedelta(days=7) + datetime.timedelta(minutes=1)
        )
        self.document.refresh_from_db()
        self.assertTrue(can_delete(self.document))


class UsedRetentionPeriodsTests(TestCase):
    """xlsx 検索・閲覧・変更!B182-184「保存済み全文書に紐付けられている保存期間を重複なしで
    抽出し、プルダウン化する。(リストは日数の短い順から昇順で生成)　※「保存期間設定」で
    設定したデータは使用しない」。
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

    def _create_document(self, title, retention_period, is_deleted=False):
        from documents.models import Document

        doc = Document(
            title=title, department=self.department, group=self.group, category=self.category,
            year=2026, retention_period=retention_period, uploader=self.employee,
            expiry_date=datetime.date(2030, 1, 1), is_deleted=is_deleted,
        )
        doc.file.save("test.pdf", ContentFile(b"dummy"), save=False)
        doc.save()
        return doc

    def test_only_periods_actually_used_by_documents_are_returned(self):
        used = RetentionPeriod.objects.create(
            kbn=RetentionKbn.DOCUMENT, period_value=1, period_unit=RetentionPeriodUnit.YEAR, display_order=1
        )
        unused = RetentionPeriod.objects.create(
            kbn=RetentionKbn.DOCUMENT, period_value=3, period_unit=RetentionPeriodUnit.YEAR, display_order=2
        )
        self._create_document("doc", used)
        result = list(used_retention_periods())
        self.assertIn(used, result)
        self.assertNotIn(unused, result)

    def test_ordered_by_ascending_day_count_not_display_order(self):
        """display_orderを1年→3年→永年の順に設定しても、日数の短い順（6ヶ月→1年→永年）に
        並び替わることを確認する（B184「保存期間設定で設定したデータは使用しない」＝
        display_orderに依存しないという意味を含む）。
        """
        period_1y = RetentionPeriod.objects.create(
            kbn=RetentionKbn.DOCUMENT, period_value=1, period_unit=RetentionPeriodUnit.YEAR, display_order=1
        )
        period_permanent = RetentionPeriod.objects.create(
            kbn=RetentionKbn.DOCUMENT, period_unit=RetentionPeriodUnit.PERMANENT, display_order=2
        )
        period_6m = RetentionPeriod.objects.create(
            kbn=RetentionKbn.DOCUMENT, period_value=6, period_unit=RetentionPeriodUnit.MONTH, display_order=3
        )
        self._create_document("doc1", period_1y)
        self._create_document("doc2", period_permanent)
        self._create_document("doc3", period_6m)
        result = list(used_retention_periods())
        self.assertEqual(result, [period_6m, period_1y, period_permanent])

    def test_deleted_documents_are_excluded(self):
        period = RetentionPeriod.objects.create(
            kbn=RetentionKbn.DOCUMENT, period_value=1, period_unit=RetentionPeriodUnit.YEAR, display_order=1
        )
        self._create_document("doc", period, is_deleted=True)
        self.assertNotIn(period, list(used_retention_periods()))


class SearchQuerysetTests(TestCase):
    """screen-search「文書タイトル」「フリーワード」のAND/OR切替（xlsx 検索・閲覧・変更シート）。"""

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
        self.doc_apple_banana = self._create_document("apple banana report")
        self.doc_apple_only = self._create_document("apple summary")
        self.doc_unrelated = self._create_document("unrelated memo")

    def _create_document(self, title):
        from documents.models import Document

        doc = Document(
            title=title, department=self.department, group=self.group, category=self.category,
            year=2026, retention_period=self.retention_period, uploader=self.employee,
            expiry_date=datetime.date(2030, 1, 1),
        )
        doc.file.save("test.pdf", ContentFile(b"dummy"), save=False)
        doc.save()
        return doc

    def test_title_or_match_returns_any_word_hit(self):
        form = SearchForm(data={"title": "apple banana", "title_match": "or"})
        qs = build_queryset(form, employee=self.employee)
        self.assertIn(self.doc_apple_banana, qs)
        self.assertIn(self.doc_apple_only, qs)
        self.assertNotIn(self.doc_unrelated, qs)

    def test_title_and_match_requires_all_words(self):
        form = SearchForm(data={"title": "apple banana", "title_match": "and"})
        qs = build_queryset(form, employee=self.employee)
        self.assertIn(self.doc_apple_banana, qs)
        self.assertNotIn(self.doc_apple_only, qs)
        self.assertNotIn(self.doc_unrelated, qs)

    def test_title_search_matches_across_fullwidth_halfwidth(self):
        """xlsx検索・閲覧・変更シート「各検索条件に入力された文字は、数字の半角全角、カタカナの
        半角全角、アルファベットの半角全角を問わず、検索できるようにする。」に対応
        （documents.models.Document.title_normalized、core.text_normalization参照）。
        """
        doc = self._create_document("ＡＢＣ商事２０２６年度契約書")
        form = SearchForm(data={"title": "abc 2026", "title_match": "and"})
        qs = build_queryset(form, employee=self.employee)
        self.assertIn(doc, qs)

    def test_freeword_search_matches_extracted_text_across_katakana_width(self):
        """フリーワード検索（extracted_text対象）でも半角全角カタカナを区別しない
        （documents.models.Document.extracted_text_normalized参照）。
        """
        from documents.models import Document

        doc = Document(
            title="半角カタカナ本文テスト", department=self.department, group=self.group,
            category=self.category, year=2026, retention_period=self.retention_period,
            uploader=self.employee, expiry_date=datetime.date(2030, 1, 1),
            extracted_text="ﾃｽﾄﾃﾞｰﾀ",
        )
        doc.file.save("test.pdf", ContentFile(b"dummy"), save=False)
        doc.save()
        form = SearchForm(data={"freeword": "テストデータ", "freeword_match": "or"})
        qs = build_queryset(form, employee=self.employee)
        self.assertIn(doc, qs)

    def test_deleted_documents_excluded_by_default(self):
        self.doc_unrelated.is_deleted = True
        self.doc_unrelated.save()
        form = SearchForm(data={})
        qs = build_queryset(form, employee=self.employee)
        self.assertNotIn(self.doc_unrelated, qs)

    def test_non_admin_only_sees_own_department(self):
        """can_select_departmentがFalseの職員は自部署の文書のみ検索対象になる。"""
        other_department = Department.objects.create(
            branch_code="999", branch_name="別支店", section_code="", section_name=""
        )
        other_doc = self._create_document_in_department(other_department, "other dept doc")
        form = SearchForm(data={})
        qs = build_queryset(form, employee=self.employee)
        self.assertIn(self.doc_apple_banana, qs)
        self.assertNotIn(other_doc, qs)

    def test_non_admin_also_sees_department_granted_via_view_scope(self):
        """xlsx 検索・閲覧・変更!B48(Rev1.1)：部署統合・分割で閲覧部署範囲テーブルに追加された
        部署の文書も検索対象に含める（organizations.services.visible_department_ids）。"""
        from organizations.models import DepartmentViewScope

        other_department = Department.objects.create(
            branch_code="999", branch_name="別支店", section_code="", section_name=""
        )
        other_doc = self._create_document_in_department(other_department, "merged dept doc")
        DepartmentViewScope.objects.create(
            viewer_department=self.department, visible_department=other_department,
            action=DepartmentViewScope.ACTION_MERGE,
        )
        form = SearchForm(data={})
        qs = build_queryset(form, employee=self.employee)
        self.assertIn(other_doc, qs)

    def _create_document_in_department(self, department, title):
        from documents.models import Document

        doc = Document(
            title=title, department=department, group=self.group, category=self.category,
            year=2026, retention_period=self.retention_period, uploader=self.employee,
            expiry_date=datetime.date(2030, 1, 1),
        )
        doc.file.save("other.pdf", ContentFile(b"dummy"), save=False)
        doc.save()
        return doc

    def test_pks_filter_ignores_other_search_conditions(self):
        """保管完了ポップアップ「登録した文書を確認する」からの遷移（原本index.html:1665-1677
        renderSearchResultTableForAllUploadedFiles()相当）。指定pksのみを、他の検索条件に
        関係なく表示する（原本フィデリティ監査で発見：以前はpks絞り込み自体が未実装だった）。
        """
        form = SearchForm(data={"title": "絶対にヒットしない検索語"})
        qs = build_queryset(form, employee=self.employee, pks=[str(self.doc_apple_only.pk)])
        self.assertEqual(list(qs), [self.doc_apple_only])

    def test_pks_filter_ignores_invalid_values(self):
        """pksはURLパスコンバータを経由しない生文字列のため、改ざんや不正なリンクで数値以外が
        混入し得る。以前はpk__in評価時に未捕捉のValueErrorで画面がクラッシュしていたが、
        無効な値は除外し有効なpkのみで絞り込むよう修正した（監査で発見・修正）。
        """
        form = SearchForm(data={})
        qs = build_queryset(
            form, employee=self.employee, pks=[str(self.doc_apple_only.pk), "not-a-number", ""]
        )
        self.assertEqual(list(qs), [self.doc_apple_only])


class SearchFormRadioDefaultsInitialAccessTests(TestCase):
    """core.forms.apply_radio_defaults / core.widgets.InlineRadioSelectの「初回アクセス時
    （GETにtitle_match等のキーが無い状態）に原本index.html:383,387,395通りchecked状態で
    表示される」分岐は、本ファイルの既存テストが常にtitle_match等を明示指定しているため
    一度も経由されていなかった（テストカバレッジ棚卸しで発見、2026-08-26追加）。
    """

    def test_initial_access_without_params_defaults_to_checked_or_and_save(self):
        form = SearchForm(data={})
        or_label, and_label = str(form["title_match"]).split("</label>")[:2]
        self.assertIn("checked", or_label)
        self.assertNotIn("checked", and_label)

        save_label, expiry_label = str(form["save_day_kbn"]).split("</label>")[:2]
        self.assertIn("checked", save_label)
        self.assertNotIn("checked", expiry_label)


class SearchSortTests(TestCase):
    """screen-search列見出しソート（documents.search_services.apply_sort）の回帰テスト。
    「No.」列は原本sortTable(1,'num',...)と同じく、その行に紐付いた表示番号（display_no、
    既定表示順＝保存日が新しい順の通し番号）そのものを昇順/降順で数値比較する
    （2026-08-17ユーザー報告「番号が変わらない」を経て、原本フィデリティ優先の方針で
    この形に確定。昇順ソートの結果が既定表示順と一致するのは「行番号を行番号で並べ替える」
    以上、原本でも起きる自然な結果であり不具合ではない）。「保存情報」列は表示
    （部署名/年/カテゴリー）と無関係なbranch_codeで近似ソートしていたため並び替え結果が
    おかしく見える不具合、それぞれの回帰テスト。
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
        # 「保存情報」ソートのテストは部署をまたいだ文書を対象にするため、can_select_department
        # がTrueになる管理者ロールにしておく（自部署以外はbuild_queryset側で絞り込まれてしまう
        # ため、SearchQuerysetTests.test_non_admin_only_sees_own_department参照）。
        PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.ADMIN)
        self.group = Group.objects.create(code="A", name="分類Ａ", doc_kbn=DocKbn.DOCUMENT)
        self.category_a = Category.objects.create(
            code="001", name="カテゴリーＡ", group=self.group, doc_kbn=DocKbn.DOCUMENT
        )
        self.category_z = Category.objects.create(
            code="002", name="カテゴリーＺ", group=self.group, doc_kbn=DocKbn.DOCUMENT
        )
        self.retention_period = RetentionPeriod.objects.create(
            kbn=RetentionKbn.DOCUMENT, period_value=1, period_unit=RetentionPeriodUnit.YEAR, display_order=1
        )

    def _create_document(
        self, *, department, category, year=2026, save_date=None, retention_period=None, uploader=None
    ):
        from documents.models import Document

        doc = Document(
            title="テスト", department=department, group=self.group, category=category,
            year=year, retention_period=retention_period or self.retention_period,
            uploader=uploader or self.employee,
            expiry_date=datetime.date(2030, 1, 1),
        )
        doc.file.save("test.pdf", ContentFile(b"dummy"), save=False)
        doc.save()
        if save_date is not None:
            # save_dateはauto_now_addのため、テストで並び順を制御するにはDB更新で上書きする。
            from documents.models import Document as _Document

            _Document.objects.filter(pk=doc.pk).update(save_date=save_date)
            doc.refresh_from_db()
        return doc

    def test_no_sort_ascending_matches_default_order_descending_reverses_it(self):
        """「No.」列の昇順ソートは、display_no（既定表示順の通し番号）を昇順に数値比較した
        結果であり、既定表示順（保存日が新しい順）と一致するのが正しい（＝原本の
        `sortTable(1,'num',...)`も、行番号を昇順で並べ替えれば初期表示順に戻る）。降順は
        その逆順になることを確認する。
        """
        older = self._create_document(
            department=self.department_a, category=self.category_a,
            save_date=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
        )
        newer = self._create_document(
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

    def test_no_sort_reverses_rows_through_the_actual_search_view(self):
        """build_queryset単体だけでなく、実際にSearchViewへ`?sort=no&dir=desc`でアクセスした際に
        画面へ渡るpage_objの並びが反転することを確認する（ユーザー報告の切り分け用、
        ビュー・テンプレート込みのエンドツーエンド確認）。
        """
        older = self._create_document(
            department=self.department_a, category=self.category_a,
            save_date=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
        )
        newer = self._create_document(
            department=self.department_a, category=self.category_a,
            save_date=datetime.datetime(2026, 6, 1, tzinfo=datetime.timezone.utc),
        )
        self.client.force_login(self.employee)

        default_response = self.client.get("/documents/search/")
        self.assertEqual(list(default_response.context["page_obj"]), [newer, older])

        asc_response = self.client.get("/documents/search/", {"sort": "no", "dir": "asc"})
        self.assertEqual(list(asc_response.context["page_obj"]), [newer, older])

        desc_response = self.client.get("/documents/search/", {"sort": "no", "dir": "desc"})
        self.assertEqual(list(desc_response.context["page_obj"]), [older, newer])

    def test_no_column_number_travels_with_its_row_when_sorted(self):
        """「No.」欄の数字自体が行についてくることを確認する回帰テスト。原本sortTable()は
        DOM行を並べ替えるだけで各行のNo.セルの値は書き換えないため、番号は常にその行に紐付いた
        まま動く。以前はforloop.counter（ページ内の表示位置）で毎回振り直していたため、
        並び替えても「No.」欄の数字自体は常に1,2,3…のままで一切変化せず、ユーザーから
        「番号が変わらない」と再報告された（2026-08-17）。
        """
        older = self._create_document(
            department=self.department_a, category=self.category_a,
            save_date=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
        )
        newer = self._create_document(
            department=self.department_a, category=self.category_a,
            save_date=datetime.datetime(2026, 6, 1, tzinfo=datetime.timezone.utc),
        )
        self.client.force_login(self.employee)

        # 既定表示順（保存日が新しい順）でNo.1=newer、No.2=older。
        default_response = self.client.get("/documents/search/")
        display_nos = {d.pk: d.display_no for d in default_response.context["page_obj"]}
        self.assertEqual(display_nos[newer.pk], 1)
        self.assertEqual(display_nos[older.pk], 2)

        # 降順ソートで行の表示順は反転する（older, newer）が、各行のNo.自体は既定表示順の
        # 番号のままその行についてくるため、1番上の行にはolderのNo.=2が表示される
        # （ページ内の表示位置で振り直していれば、ここでも1になってしまう）。
        desc_response = self.client.get("/documents/search/", {"sort": "no", "dir": "desc"})
        desc_page = list(desc_response.context["page_obj"])
        self.assertEqual(desc_page, [older, newer])
        self.assertEqual(desc_page[0].display_no, 2)
        self.assertEqual(desc_page[1].display_no, 1)

    def test_info_sort_matches_displayed_department_year_category(self):
        """「保存情報」列は表示通り部署名→年→カテゴリー名の順で並ぶことを確認する
        （branch_codeでの近似ソートでは表示文字列と無関係な順序になっていた）。
        """
        doc_a = self._create_document(department=self.department_a, category=self.category_a)
        doc_z = self._create_document(department=self.department_b, category=self.category_z)
        form = SearchForm(data={})

        asc_qs = build_queryset(form, employee=self.employee, sort_key="info", sort_dir="asc")
        self.assertEqual(list(asc_qs), [doc_a, doc_z])

        desc_qs = build_queryset(form, employee=self.employee, sort_key="info", sort_dir="desc")
        self.assertEqual(list(desc_qs), [doc_z, doc_a])

    def test_retention_period_sort_uses_display_order_not_id(self):
        """「保存期間」列は__str__の文字列でもPKでもなく、意図された並び順
        （masters.RetentionPeriod.display_order、screen-retention-docのドロップダウン等と同じ
        並び）でソートされることを確認する。以前はPKでソートしていたため、作成順と表示順が
        食い違うと並び替え結果がおかしく見えていた。
        """
        retention_b = RetentionPeriod.objects.create(
            kbn=RetentionKbn.DOCUMENT, period_value=5, period_unit=RetentionPeriodUnit.YEAR, display_order=3
        )
        retention_a = RetentionPeriod.objects.create(
            kbn=RetentionKbn.DOCUMENT, period_value=1, period_unit=RetentionPeriodUnit.YEAR, display_order=2
        )
        # retention_bの方がpk（作成順）は小さいが、display_orderはretention_aの方が小さい
        # ことをテストの前提として明示する。
        self.assertLess(retention_b.pk, retention_a.pk)

        doc_b = self._create_document(
            department=self.department_a, category=self.category_a, retention_period=retention_b
        )
        doc_a = self._create_document(
            department=self.department_a, category=self.category_a, retention_period=retention_a
        )
        form = SearchForm(data={})

        asc_qs = build_queryset(form, employee=self.employee, sort_key="retention_period", sort_dir="asc")
        self.assertEqual(list(asc_qs), [doc_a, doc_b])

        desc_qs = build_queryset(form, employee=self.employee, sort_key="retention_period", sort_dir="desc")
        self.assertEqual(list(desc_qs), [doc_b, doc_a])

    def test_uploader_sort_matches_displayed_department_and_name(self):
        """「保管・更新者」列は表示通り部署名→氏名の順で並ぶことを確認する
        （search.html: `{{ document.uploader.department.section_name }}｜{{ document.uploader.name }}`。
        氏名のみでのソートでは、部署をまたぐと表示と食い違って見えていた）。
        """
        uploader_in_a = Employee.objects.create_user(
            employee_no="10", name="Zzz", password="x",
            department=self.department_a, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        uploader_in_b = Employee.objects.create_user(
            employee_no="11", name="Aaa", password="x",
            department=self.department_b, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        doc_uploader_a = self._create_document(
            department=self.department_a, category=self.category_a, uploader=uploader_in_a
        )
        doc_uploader_b = self._create_document(
            department=self.department_a, category=self.category_a, uploader=uploader_in_b
        )
        form = SearchForm(data={})

        asc_qs = build_queryset(form, employee=self.employee, sort_key="uploader", sort_dir="asc")
        self.assertEqual(list(asc_qs), [doc_uploader_a, doc_uploader_b])

        desc_qs = build_queryset(form, employee=self.employee, sort_key="uploader", sort_dir="desc")
        self.assertEqual(list(desc_qs), [doc_uploader_b, doc_uploader_a])


class NoticeFilterTests(TestCase):
    """メイン画面お知らせリンクからの遷移時の絞り込み（xlsx メイン画面!C42-46、
    documents.search_services._apply_notice_filter）。"""

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

    def _create_document(self, expiry_date):
        from documents.models import Document

        doc = Document(
            title="テスト", department=self.department, group=self.group, category=self.category,
            year=2026, retention_period=self.retention_period, uploader=self.employee,
            expiry_date=expiry_date,
        )
        doc.file.save("test.pdf", ContentFile(b"dummy"), save=False)
        doc.save()
        return doc

    @override_settings(NOTICE_EXPIRING_THRESHOLD_MONTHS=1)
    def test_expiring_soon_excludes_documents_beyond_threshold(self):
        """しきい値の上限が無いと未来の全文書がヒットしてしまうバグを修正した回帰テスト
        （2026-08-13監査で発見）。"""
        today = datetime.date.today()
        within = self._create_document(today + datetime.timedelta(days=10))
        beyond = self._create_document(today + datetime.timedelta(days=400))
        form = SearchForm(data={})
        qs = build_queryset(form, employee=self.employee, notice="expiring_soon")
        self.assertIn(within, qs)
        self.assertNotIn(beyond, qs)

    @override_settings(NOTICE_EXPIRING_THRESHOLD_MONTHS=6)
    def test_expiring_soon_threshold_is_configurable(self):
        today = datetime.date.today()
        within = self._create_document(today + datetime.timedelta(days=150))
        form = SearchForm(data={})
        qs = build_queryset(form, employee=self.employee, notice="expiring_soon")
        self.assertIn(within, qs)


class DeleteViewAjaxTests(TestCase):
    """詳細ポップアップ「削除」ボタン。common.jsのtriggerDeleteFromDetail()はX-Requested-With
    ヘッダー付きでfetch()しJSONレスポンスを期待するが、以前は常にredirect()を返しており
    r.json()のパースに失敗してUI側のフィードバックが一切動かないバグがあった
    （原本フィデリティ監査で発見・修正）。
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
        group = Group.objects.create(code="A", name="分類Ａ", doc_kbn=DocKbn.DOCUMENT)
        category = Category.objects.create(code="001", name="カテゴリーＡ", group=group, doc_kbn=DocKbn.DOCUMENT)
        retention_period = RetentionPeriod.objects.create(
            kbn=RetentionKbn.DOCUMENT, period_value=1, period_unit=RetentionPeriodUnit.YEAR, display_order=1
        )
        from documents.models import Document

        self.document = Document(
            title="削除対象", department=self.department, group=group, category=category,
            year=2026, retention_period=retention_period, uploader=self.employee,
            expiry_date=datetime.date(2030, 1, 1),
        )
        self.document.file.save("test.pdf", ContentFile(b"dummy"), save=False)
        self.document.save()

    def test_ajax_request_returns_json(self):
        response = self.client.post(
            f"/documents/{self.document.pk}/delete/", HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertEqual(response.json(), {"success": True, "message": "文書を削除しました。"})

    def test_first_delete_is_logical_delete_record_and_file_survive(self):
        """まだゴミ箱保管中でない文書に対する削除は論理削除のみ。DBレコード・ファイル実体とも
        残り、ユーザー依頼2026-08-12で追加した完全削除（ゴミ箱保管中からの再削除）とは別物。"""
        from documents.models import Document

        self.client.post(f"/documents/{self.document.pk}/delete/", HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.document.refresh_from_db()
        self.assertTrue(self.document.is_deleted)
        self.assertIsNotNone(self.document.deleted_at)
        self.assertTrue(Document.objects.filter(pk=self.document.pk).exists())
        self.assertTrue(self.document.file.storage.exists(self.document.file.name))

    def test_deleting_already_trashed_document_is_rejected(self):
        """Rev1.2（xlsx 検索・閲覧・変更!B331,B337「削除されている文書は、ボタンを非表示と
        する」）で、2026-08-12にユーザー依頼で追加した「ゴミ箱保管中の文書を削除ボタンで
        完全削除する」機能は2026-08-24に廃止された（documents.services.can_delete docstring
        参照）。既に削除済みの文書への削除操作はサーバー側でも拒否し、レコード・ファイルとも
        残ることを確認する。"""
        from documents.models import Document

        file_name = self.document.file.name
        self.document.is_deleted = True
        self.document.save(update_fields=["is_deleted", "deleted_at"])
        self.assertTrue(self.document.file.storage.exists(file_name))

        response = self.client.post(
            f"/documents/{self.document.pk}/delete/", HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.json()["success"])
        self.assertEqual(response.json()["message"], "この文書は既に削除されています。")
        self.assertTrue(Document.objects.filter(pk=self.document.pk).exists())
        self.assertTrue(self.document.file.storage.exists(file_name))

    def test_deleting_already_trashed_document_is_rejected_non_ajax(self):
        """test_deleting_already_trashed_document_is_rejectedの非AJAX版
        （テストカバレッジ棚卸しで発見：AJAX経路のみテストされ、非AJAX経路の
        PermissionDenied発生・ステータスコードは未検証だった）。"""
        from documents.models import Document

        self.document.is_deleted = True
        self.document.save(update_fields=["is_deleted", "deleted_at"])

        response = self.client.post(f"/documents/{self.document.pk}/delete/")
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Document.objects.filter(pk=self.document.pk).exists())

    def test_non_ajax_request_still_redirects(self):
        response = self.client.post(f"/documents/{self.document.pk}/delete/")
        self.assertEqual(response.status_code, 302)

    def test_ajax_request_returns_json_404_for_missing_document(self):
        """存在しない文書へのAJAX削除要求はJSONの404を返す（監査で発見・修正：以前はDjango標準の
        HTML 404ページが返り、common.js側のr.json()パースが壊れていた）。"""
        response = self.client.post(
            "/documents/999999/delete/", HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertFalse(response.json()["success"])

    def test_ajax_request_returns_json_error_on_db_failure(self):
        """document.save()がDB例外を送出した場合も、AJAX呼び出し時はJSONで失敗を返す
        （HTML 500だとcommon.js側のr.json()パースが壊れるため。監査で発見・修正）。"""
        from documents.models import Document

        with mock.patch.object(Document, "save", side_effect=DBError("db down")):
            response = self.client.post(
                f"/documents/{self.document.pk}/delete/", HTTP_X_REQUESTED_WITH="XMLHttpRequest"
            )
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertFalse(response.json()["success"])


class DownloadViewTests(TestCase):
    """screen-search「ダウンロード」ボタン（単体）。ダウンロード操作自体は監査ログに一切
    記録されていなかった（未実装改善候補の棚卸しで発見、2026-08-12追加対応）。
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
        self.client.login(username="1", password="pass1234")

        from documents.models import Document

        self.document = Document(
            title="DL対象", department=self.department, group=self.group, category=self.category,
            year=2026, retention_period=self.retention_period, uploader=self.employee,
            expiry_date=datetime.date(2030, 1, 1),
        )
        self.document.file.save("dl.txt", ContentFile(b"hello"), save=False)
        self.document.save()

    def test_download_creates_audit_log(self):
        PermissionProfile.objects.create(
            employee=self.employee, role=PermissionRole.STAFF, doc_download=True
        )
        response = self.client.get(f"/documents/{self.document.pk}/download/")
        self.assertEqual(response.status_code, 200)
        entry = AuditLog.objects.get(action="文書検索 ダウンロード")
        self.assertEqual(entry.employee_no, "1")
        self.assertIn("DL対象", entry.event_message)

    def test_denied_download_does_not_create_audit_log(self):
        response = self.client.get(f"/documents/{self.document.pk}/download/")
        self.assertEqual(response.status_code, 403)
        self.assertFalse(AuditLog.objects.filter(action="文書検索 ダウンロード").exists())

    def test_download_audit_log_records_document_privacy_flag_value(self):
        """core.record_views.BaseFileServeView.audit_extra_kwargs()（documents側の
        personal_info_flag付与）はDocument.privacy_flagの値をそのまま渡すが、既存の
        test_download_creates_audit_logはaction/employee_no/event_messageのみ確認しており
        personal_info_flagの値自体は未検証だった（テストカバレッジ棚卸しで発見、2026-08-26追加）。
        既定値(True)ではなくFalseを明示設定し、ハードコードされた固定値でないことを確認する。
        """
        PermissionProfile.objects.create(
            employee=self.employee, role=PermissionRole.STAFF, doc_download=True
        )
        self.document.privacy_flag = False
        self.document.save(update_fields=["privacy_flag"])
        self.client.get(f"/documents/{self.document.pk}/download/")
        entry = AuditLog.objects.get(action="文書検索 ダウンロード")
        self.assertFalse(entry.personal_info_flag)

    def test_display_name_strips_uuid_prefix(self):
        """core.models.UuidPrefixedFilenameMixin.display_name（ダウンロード時のfilenameとして
        BaseFileServeView内部で使われる）。contracts.RelatedFile側は値自体を直接検証済みだが、
        Document本体側はDownloadViewTestsがレスポンスの成否のみを見ており、値自体
        （UUIDプレフィックス除去後の元ファイル名）を確認するテストが無かった
        （テストカバレッジ棚卸しで発見、2026-08-26追加）。"""
        basename = self.document.file.name.rsplit("/", 1)[-1]
        self.assertIn("_", basename)  # storage_paths側でUUIDプレフィックスが付与されていること
        self.assertEqual(self.document.display_name, "dl.txt")

    def test_deleted_document_download_returns_404(self):
        """xlsx 検索・閲覧・変更!B331(Rev1.2)「削除されている(削除フラグがTrue)文書は、ボタンを
        非表示とする」のURL直打ち対策（DocumentEditView.get_object()と同じ
        is_deleted=Falseパターン）。"""
        PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.STAFF, doc_download=True)
        self.document.is_deleted = True
        self.document.save(update_fields=["is_deleted"])
        response = self.client.get(f"/documents/{self.document.pk}/download/")
        self.assertEqual(response.status_code, 404)

    def test_missing_file_returns_404(self):
        """PreviewViewTests.test_missing_file_returns_404と同型のOSError境界（テストカバレッジ
        棚卸しで発見：DownloadView側は同じexcept OSError節を持つのに未テストだった）。"""
        PermissionProfile.objects.create(
            employee=self.employee, role=PermissionRole.STAFF, doc_download=True
        )
        with mock.patch(
            "django.db.models.fields.files.FieldFile.open", side_effect=OSError("missing")
        ):
            response = self.client.get(f"/documents/{self.document.pk}/download/")
        self.assertEqual(response.status_code, 404)


class BulkButtonsHiddenForRecentlyDeletedNoticeTests(TestCase):
    """Rev1.2（xlsx 検索・閲覧・変更!B260,B267「メイン画面「お知らせ」の"直近Xヵ月以内で
    削除された文書"リンクから遷移した場合は、ボタンを非表示にする」、2026-08-24反映）。
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

    def test_bulk_buttons_hidden_when_notice_is_recently_deleted(self):
        response = self.client.get("/documents/search/", {"notice": "recently_deleted"})
        self.assertNotContains(response, "一括ダウンロード")
        self.assertNotContains(response, "一括編集")
        self.assertNotContains(response, "一括選択")

    def test_bulk_buttons_shown_for_normal_search(self):
        response = self.client.get("/documents/search/")
        self.assertContains(response, "一括ダウンロード")
        self.assertContains(response, "一括編集")
        self.assertContains(response, "一括選択")


class BulkDownloadViewTests(TestCase):
    """screen-search「一括ダウンロード」（xlsx 検索・閲覧・変更!B264-265、要再確認No.20）。"""

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
        self.client.login(username="1", password="pass1234")

    def _create_document(self, title):
        from documents.models import Document

        doc = Document(
            title=title, department=self.department, group=self.group, category=self.category,
            year=2026, retention_period=self.retention_period, uploader=self.employee,
            expiry_date=datetime.date(2030, 1, 1),
        )
        doc.file.save(f"{title}.txt", ContentFile(b"hello"), save=False)
        doc.save()
        return doc

    def test_download_without_permission_denied(self):
        doc = self._create_document("test1")
        response = self.client.post("/documents/bulk-download/", {"pks": [doc.pk]})
        self.assertEqual(response.status_code, 403)

    def test_download_with_permission_returns_zip(self):
        import zipfile
        from io import BytesIO

        PermissionProfile.objects.create(
            employee=self.employee, role=PermissionRole.STAFF, doc_download=True
        )
        doc1 = self._create_document("test1")
        doc2 = self._create_document("test2")
        response = self.client.post("/documents/bulk-download/", {"pks": [doc1.pk, doc2.pk]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/zip")
        zf = zipfile.ZipFile(BytesIO(response.content))
        names = zf.namelist()
        self.assertEqual(len(names), 2)
        self.assertTrue(any("test1" in n for n in names))
        self.assertTrue(any("test2" in n for n in names))
        entry = AuditLog.objects.get(action="文書検索 一括ダウンロード")
        self.assertIn("2件", entry.event_message)

    def test_no_selection_redirects_with_message(self):
        response = self.client.post("/documents/bulk-download/", {})
        self.assertRedirects(response, "/documents/search/")

    def test_invalid_pks_values_are_ignored_not_crashing(self):
        """pksに数値以外の値が混ざっても未捕捉のValueErrorで500にならず、有効なpkのみで
        ZIPを作る（監査で発見・修正）。"""
        import zipfile
        from io import BytesIO

        PermissionProfile.objects.create(
            employee=self.employee, role=PermissionRole.STAFF, doc_download=True
        )
        doc = self._create_document("test1")
        response = self.client.post("/documents/bulk-download/", {"pks": [str(doc.pk), "abc"]})
        self.assertEqual(response.status_code, 200)
        zf = zipfile.ZipFile(BytesIO(response.content))
        self.assertEqual(len(zf.namelist()), 1)

    def test_missing_file_entity_is_skipped_with_warning_but_others_succeed(self):
        """テストカバレッジ棚卸しで発見：1件のファイル実体欠損でZIP全体を失敗させない
        （views.BulkDownloadView.postのexcept FileNotFoundError:節）設計が未テストだった。
        欠損分はスキップした上でmessages.warningを出し、残りは正常にZIPへ含まれることを確認する。"""
        import zipfile
        from io import BytesIO

        from django.contrib.messages import get_messages

        PermissionProfile.objects.create(
            employee=self.employee, role=PermissionRole.STAFF, doc_download=True
        )
        doc1 = self._create_document("present")
        doc2 = self._create_document("missing")
        doc2.file.delete(save=False)  # ストレージ上の実体だけ消し、DBレコードは残す

        response = self.client.post("/documents/bulk-download/", {"pks": [doc1.pk, doc2.pk]})
        self.assertEqual(response.status_code, 200)
        zf = zipfile.ZipFile(BytesIO(response.content))
        names = zf.namelist()
        self.assertEqual(len(names), 1)
        self.assertTrue(any("present" in n for n in names))
        warnings = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertTrue(any("1件のファイルが見つからなかった" in m for m in warnings))


class BulkEditViewTests(TestCase):
    """screen-search「一括編集」（html4差分で初めて仕様が提示された機能、
    HTML_REIMPL_CHECKLIST_ARCHIVE.md「検索結果一覧 一括編集の実装」参照）。save-as-you-go方式で、各ステップの送信ごとに
    その文書を都度保存し、AuditLogも文書ごとに1件ずつ記録されることを確認する
    （一括ダウンロードのような集約1件ではない）。"""

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
        self.client.login(username="1", password="pass1234")

    def _create_document(self, title):
        from documents.models import Document

        doc = Document(
            title=title, department=self.department, group=self.group, category=self.category,
            year=2026, retention_period=self.retention_period, uploader=self.employee,
            expiry_date=datetime.date(2030, 1, 1),
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

    def _step_data(self, title, bulk_nav=None):
        data = {
            "token": self._get_token(),
            "department": self.department.pk,
            "group": self.group.pk,
            "category": self.category.pk,
            "year": 2026,
            "retention_period": self.retention_period.pk,
            "privacy_flag": "False",
            "memo": "",
            "title_0": title,
        }
        if bulk_nav:
            data["bulk_nav"] = bulk_nav
        return data

    def test_start_without_selection_redirects_with_message(self):
        response = self.client.post("/documents/bulk-edit/start/", {})
        self.assertRedirects(response, "/documents/search/")

    def test_start_with_invalid_pks_ignored_not_crashing(self):
        doc = self._create_document("test1")
        response = self.client.post(
            "/documents/bulk-edit/start/", {"pks": [str(doc.pk), "abc"]}
        )
        self.assertRedirects(response, "/documents/bulk-edit/")

    def test_start_with_all_pks_invalid_or_deleted_redirects_to_search(self):
        """テストカバレッジ棚卸しで発見：数値以外の混入は上のテストでカバーされていたが、
        「有効な数値pkだが全て削除済み」等でordered_pksが空になる境界は未検証だった
        （BulkEditStartView.postの`if not ordered_pks:`分岐）。"""
        doc = self._create_document("deleted")
        doc.is_deleted = True
        doc.save(update_fields=["is_deleted"])
        response = self.client.post("/documents/bulk-edit/start/", {"pks": [doc.pk, "abc"]})
        self.assertRedirects(response, "/documents/search/")
        self.assertIsNone(self.client.session.get("documents_bulk_edit"))

    def test_direct_access_without_session_state_redirects(self):
        response = self.client.get("/documents/bulk-edit/")
        self.assertRedirects(response, "/documents/search/")

    def test_walk_through_two_documents_saves_each_and_records_per_item_audit_log(self):
        doc1 = self._create_document("doc1")
        doc2 = self._create_document("doc2")
        self.client.post("/documents/bulk-edit/start/", {"pks": [doc1.pk, doc2.pk]})

        # 1件目: 内容を編集して「次へ」
        get_response = self.client.get("/documents/bulk-edit/")
        self.assertContains(get_response, "1 / 2")
        response = self.client.post(
            "/documents/bulk-edit/", self._step_data("doc1-編集後")
        )
        self.assertRedirects(response, "/documents/bulk-edit/")
        doc1.refresh_from_db()
        self.assertEqual(doc1.title, "doc1-編集後")

        # 2件目（最終ステップ）: 内容を編集して「更新」→completeが返る
        get_response = self.client.get("/documents/bulk-edit/")
        self.assertContains(get_response, "2 / 2")
        response = self.client.post(
            "/documents/bulk-edit/", self._step_data("doc2-編集後")
        )
        self.assertEqual(response.status_code, 200)
        doc2.refresh_from_db()
        self.assertEqual(doc2.title, "doc2-編集後")
        created = response.context["complete"]["created"]
        self.assertEqual([d.pk for d in created], [doc1.pk, doc2.pk])

        entries = AuditLog.objects.filter(action="保管画面２ 更新").order_by("timestamp")
        self.assertEqual(entries.count(), 2)
        self.assertIn("doc1-編集後", entries[0].event_message)
        self.assertIn("doc2-編集後", entries[1].event_message)

        # 完了後はセッション状態がクリアされ、直接アクセスすると検索画面に戻される
        response = self.client.get("/documents/bulk-edit/")
        self.assertRedirects(response, "/documents/search/")

    def test_prev_navigation_also_saves_current_step(self):
        doc1 = self._create_document("doc1")
        doc2 = self._create_document("doc2")
        self.client.post("/documents/bulk-edit/start/", {"pks": [doc1.pk, doc2.pk]})
        self.client.get("/documents/bulk-edit/")
        self.client.post("/documents/bulk-edit/", self._step_data("doc1-編集後"))

        # 2件目に来たら内容を変更し、保存されないまま「＜」で1件目に戻る
        self.client.get("/documents/bulk-edit/")
        response = self.client.post(
            "/documents/bulk-edit/", self._step_data("doc2-編集後", bulk_nav="prev")
        )
        self.assertRedirects(response, "/documents/bulk-edit/")
        doc2.refresh_from_db()
        self.assertEqual(doc2.title, "doc2-編集後")

        get_response = self.client.get("/documents/bulk-edit/")
        self.assertContains(get_response, "1 / 2")

    def test_step_db_failure_shows_error_and_does_not_update_document(self):
        """テストカバレッジ棚卸し（review_test_doc_contract.txt指摘1）で発見：
        BulkEditView.postの`except DBError:`が未検証だった。ステップ再描画（200）で
        エラーメッセージが出て、対象文書が更新されないことを確認する。"""
        from django.contrib.messages import get_messages

        from documents.models import Document

        doc1 = self._create_document("doc1")
        self.client.post("/documents/bulk-edit/start/", {"pks": [doc1.pk]})
        self.client.get("/documents/bulk-edit/")

        with mock.patch.object(Document, "save", side_effect=DBError("db down")):
            response = self.client.post("/documents/bulk-edit/", self._step_data("doc1-編集後"))

        self.assertEqual(response.status_code, 200)
        texts = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertTrue(any("更新に失敗しました" in t for t in texts))
        doc1.refresh_from_db()
        self.assertEqual(doc1.title, "doc1")


class DeletedDocumentDirectAccessTests(TestCase):
    """テストカバレッジ棚卸しで発見：DocumentEditView/BulkEditViewはDownloadViewと同じ
    is_deleted=Falseパターンのget_object_or_404を使っているが、削除済み文書への直接URLアクセスが
    実際に404/検索画面への案内になることは（DetailAPIViewのedit_url=None化を通じて間接的に
    しか）検証されていなかった。"""

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
        self.client.login(username="1", password="pass1234")

        from documents.models import Document

        self.document = Document(
            title="削除済み文書", department=self.department, group=self.group, category=self.category,
            year=2026, retention_period=self.retention_period, uploader=self.employee,
            expiry_date=datetime.date(2030, 1, 1), is_deleted=True,
        )
        self.document.file.save("doc.pdf", ContentFile(b"dummy"), save=False)
        self.document.save()

    def test_edit_screen_direct_access_returns_404(self):
        response = self.client.get(f"/documents/{self.document.pk}/edit/")
        self.assertEqual(response.status_code, 404)

    def test_bulk_edit_start_silently_excludes_deleted_pk(self):
        """一括編集開始時、削除済み文書のpkは（BulkDownloadViewと同じ方針で）静かに除外される。"""
        response = self.client.post("/documents/bulk-edit/start/", {"pks": [self.document.pk]})
        self.assertRedirects(response, "/documents/search/")

    def test_bulk_edit_direct_access_to_deleted_document_returns_404(self):
        """セッション状態を直接構築してBulkEditViewへ削除済みpkを混入させた場合
        （通常はBulkEditStartViewが除外するため到達しないはずのURL直打ち相当）も404になる。"""
        from core import bulk_edit_services

        session = self.client.session
        bulk_edit_services.start_bulk_edit(session, "documents_bulk_edit", [self.document.pk])
        session.save()
        response = self.client.get("/documents/bulk-edit/")
        self.assertEqual(response.status_code, 404)


class PreviewViewTests(TestCase):
    """screen-search「文書イメージ」欄。原本には無い機能（ユーザー要望で追加）だが、権限は
    ダウンロードと同じ`doc_download`で保護する（BulkDownloadViewTestsと同じ権限パターン）。
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
        self.client.login(username="1", password="pass1234")

        from documents.models import Document

        self.document = Document(
            title="プレビュー対象", department=self.department, group=self.group, category=self.category,
            year=2026, retention_period=self.retention_period, uploader=self.employee,
            expiry_date=datetime.date(2030, 1, 1),
        )
        self.document.file.save("preview.pdf", ContentFile(b"%PDF-1.4 dummy"), save=False)
        self.document.save()

    def test_without_permission_denied(self):
        response = self.client.get(f"/documents/{self.document.pk}/preview/")
        self.assertEqual(response.status_code, 403)

    def test_with_permission_returns_inline_content_disposition(self):
        PermissionProfile.objects.create(
            employee=self.employee, role=PermissionRole.STAFF, doc_download=True
        )
        response = self.client.get(f"/documents/{self.document.pk}/preview/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("inline", response["Content-Disposition"])
        self.assertNotIn("attachment", response["Content-Disposition"])
        self.assertTrue(AuditLog.objects.filter(action="文書検索 プレビュー").exists())

    def test_missing_file_returns_404(self):
        PermissionProfile.objects.create(
            employee=self.employee, role=PermissionRole.STAFF, doc_download=True
        )
        with mock.patch(
            "django.db.models.fields.files.FieldFile.open", side_effect=OSError("missing")
        ):
            response = self.client.get(f"/documents/{self.document.pk}/preview/")
        self.assertEqual(response.status_code, 404)

    def test_deleted_document_preview_returns_404(self):
        """xlsx 検索・閲覧・変更!B331(Rev1.2)「削除されている(削除フラグがTrue)文書は、ボタンを
        非表示とする」のURL直打ち対策（品質レビューで発見：DownloadViewは既にis_deleted=False
        パターンだったが、PreviewViewだけ漏れていたため削除済み文書の中身がプレビュー経由で
        そのまま閲覧できていた。2026-08-25修正）。"""
        PermissionProfile.objects.create(
            employee=self.employee, role=PermissionRole.STAFF, doc_download=True
        )
        self.document.is_deleted = True
        self.document.save(update_fields=["is_deleted"])
        response = self.client.get(f"/documents/{self.document.pk}/preview/")
        self.assertEqual(response.status_code, 404)


class ImagePreviewTests(TestCase):
    """保管画面２（登録前）・編集画面の実プレビュー機能（ユーザー依頼2026-08-12で追加、
    当初は画像のみだったが同日中にPDFにも対応した）。原本index.htmlのpdf-mock-pageは
    固定モックのみだったが、対象が画像／PDF（core.file_type_services.get_preview_kind）
    かつcan_download権限がある場合のみ実データの<img>/<iframe>表示に切り替える。
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
        self.client.login(username="1", password="pass1234")

    def _upload_pending(self, filename, content, content_type):
        self.client.post(
            "/documents/upload/step1/",
            {"files": [SimpleUploadedFile(filename, content, content_type=content_type)]},
        )

    def test_pending_preview_without_permission_denied(self):
        self._upload_pending("a.png", b"PNGDATA", "image/png")
        response = self.client.get("/documents/upload/step2/preview/0/")
        self.assertEqual(response.status_code, 403)

    def test_pending_preview_returns_uploaded_file_bytes(self):
        PermissionProfile.objects.create(
            employee=self.employee, role=PermissionRole.STAFF, doc_download=True
        )
        self._upload_pending("a.png", b"PNGDATA", "image/png")
        response = self.client.get("/documents/upload/step2/preview/0/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"PNGDATA")

    def test_pending_preview_out_of_range_index_returns_404(self):
        PermissionProfile.objects.create(
            employee=self.employee, role=PermissionRole.STAFF, doc_download=True
        )
        self._upload_pending("a.png", b"PNGDATA", "image/png")
        response = self.client.get("/documents/upload/step2/preview/5/")
        self.assertEqual(response.status_code, 404)

    def test_storage2_context_flags_image_and_builds_preview_url(self):
        PermissionProfile.objects.create(
            employee=self.employee, role=PermissionRole.STAFF, doc_download=True
        )
        self._upload_pending("a.png", b"PNGDATA", "image/png")
        response = self.client.get("/documents/upload/step2/")
        self.assertEqual(response.context["preview_kinds"], ["image"])
        self.assertEqual(response.context["preview_urls"], ["/documents/upload/step2/preview/0/"])

    def test_storage2_context_flags_pdf_and_builds_preview_url(self):
        PermissionProfile.objects.create(
            employee=self.employee, role=PermissionRole.STAFF, doc_download=True
        )
        self._upload_pending("a.pdf", b"%PDF-1.4", "application/pdf")
        response = self.client.get("/documents/upload/step2/")
        self.assertEqual(response.context["preview_kinds"], ["pdf"])
        self.assertEqual(response.context["preview_urls"], ["/documents/upload/step2/preview/0/"])

    def test_storage2_unsupported_extension_yields_no_preview_kind(self):
        self._upload_pending("a.docx", b"dummy", "application/octet-stream")
        response = self.client.get("/documents/upload/step2/")
        self.assertEqual(response.context["preview_kinds"], [""])

    def test_storage2_without_permission_yields_no_preview_urls(self):
        """can_download権限が無いユーザーには、拡張子判定（preview_kinds）自体は返しても
        preview_urlsは空にする。JS側はurlが無ければ従来のモック表示にフォールバックする。"""
        self._upload_pending("a.png", b"PNGDATA", "image/png")
        response = self.client.get("/documents/upload/step2/")
        self.assertEqual(response.context["preview_kinds"], ["image"])
        self.assertEqual(response.context["preview_urls"], [])

    def test_edit_screen_shows_image_preview_only_with_permission_and_image_file(self):
        from documents.models import Document

        document = Document(
            title="画像文書", department=self.department, group=self.group, category=self.category,
            year=2026, retention_period=self.retention_period, uploader=self.employee,
            expiry_date=datetime.date(2030, 1, 1),
        )
        document.file.save("photo.png", ContentFile(b"PNGDATA"), save=False)
        document.save()

        # 権限が無い間は、拡張子判定（preview_kind）自体は返しつつ権限不足を明示する文言を表示する
        # （2026-08-13ユーザー報告対応：権限不足でモック文言のまま表示され「動いていない」と
        # 誤解された）。
        response = self.client.get(f"/documents/{document.pk}/edit/")
        self.assertEqual(response.context["preview_kind"], "image")
        self.assertFalse(response.context["can_download"])
        self.assertContains(response, "文書-ダウンロード」権限が必要です")

        PermissionProfile.objects.create(
            employee=self.employee, role=PermissionRole.STAFF, doc_download=True
        )
        response = self.client.get(f"/documents/{document.pk}/edit/")
        self.assertEqual(response.context["preview_kind"], "image")
        self.assertTrue(response.context["can_download"])
        self.assertContains(response, f'src="/documents/{document.pk}/preview/"')
        # base.htmlのpopup-detail用<iframe id="detail-preview-frame">は全ページ共通で常に
        # 出力される（空src・display:none）ため、"<iframe"の有無ではなく編集画面自身の
        # プレビュー用iframe（該当pkをsrcに持つもの）が無いことをピンポイントで確認する。
        self.assertNotContains(response, f'<iframe src="/documents/{document.pk}/preview/"')

    def test_edit_screen_shows_pdf_preview_only_with_permission_and_pdf_file(self):
        from documents.models import Document

        document = Document(
            title="PDF文書", department=self.department, group=self.group, category=self.category,
            year=2026, retention_period=self.retention_period, uploader=self.employee,
            expiry_date=datetime.date(2030, 1, 1),
        )
        document.file.save("doc.pdf", ContentFile(b"%PDF-1.4"), save=False)
        document.save()

        response = self.client.get(f"/documents/{document.pk}/edit/")
        self.assertEqual(response.context["preview_kind"], "pdf")
        self.assertFalse(response.context["can_download"])
        self.assertContains(response, "文書-ダウンロード」権限が必要です")

        PermissionProfile.objects.create(
            employee=self.employee, role=PermissionRole.STAFF, doc_download=True
        )
        response = self.client.get(f"/documents/{document.pk}/edit/")
        self.assertEqual(response.context["preview_kind"], "pdf")
        self.assertTrue(response.context["can_download"])
        self.assertContains(response, f'<iframe src="/documents/{document.pk}/preview/"')

    def test_edit_screen_unsupported_extension_keeps_mock_even_with_permission(self):
        from documents.models import Document

        PermissionProfile.objects.create(
            employee=self.employee, role=PermissionRole.STAFF, doc_download=True
        )
        document = Document(
            title="不明拡張子文書", department=self.department, group=self.group, category=self.category,
            year=2026, retention_period=self.retention_period, uploader=self.employee,
            expiry_date=datetime.date(2030, 1, 1),
        )
        document.file.save("doc.docx", ContentFile(b"dummy"), save=False)
        document.save()

        response = self.client.get(f"/documents/{document.pk}/edit/")
        self.assertIsNone(response.context["preview_kind"])
        self.assertContains(response, "擬似PDFプレビュー")


class EditScreenYearFieldTests(TestCase):
    """編集画面「年」フィールド（documents.forms.UploadStep2Form.year、core.forms.
    year_choices_with_existing）。年の選択肢は実行時の直近6年分のみを動的生成するため、対象文書の
    年がその範囲外（保存期間が長く何年も前に登録された文書等）だと、原本フィデリティ監査で発見した
    不具合が起きていた：<select>のどのoptionにもselected属性が付かずブラウザが先頭optionを自動選択
    してしまうため、年欄に一切触れずフォームを送信しただけで年が意図せず書き換わる。
    """

    def setUp(self):
        from documents.models import Document

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
            kbn=RetentionKbn.DOCUMENT, period_value=10, period_unit=RetentionPeriodUnit.YEAR, display_order=1
        )
        self.client.login(username="1", password="pass1234")
        self.old_year = datetime.date.today().year - 10
        self.document = Document(
            title="古い年の文書", department=self.department, group=self.group, category=self.category,
            year=self.old_year, retention_period=self.retention_period, uploader=self.employee,
            expiry_date=datetime.date(2099, 1, 1),
        )
        self.document.file.save("old.pdf", ContentFile(b"%PDF-1.4"), save=False)
        self.document.save()

    def test_edit_screen_marks_out_of_range_year_as_selected_option(self):
        response = self.client.get(f"/documents/{self.document.pk}/edit/")
        self.assertContains(response, f'value="{self.old_year}" selected')

    def test_submitting_edit_form_unchanged_preserves_out_of_range_year(self):
        get_response = self.client.get(f"/documents/{self.document.pk}/edit/")
        token = get_response.context["token"]
        response = self.client.post(
            f"/documents/{self.document.pk}/edit/",
            {
                "token": token,
                "department": self.department.pk,
                "group": self.group.pk,
                "category": self.category.pk,
                "year": self.old_year,
                "title_0": self.document.title,
                "retention_period": self.retention_period.pk,
                "privacy_flag": "True",
                "memo": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["form"].errors)
        self.document.refresh_from_db()
        self.assertEqual(self.document.year, self.old_year)


class DocumentEditViewDBErrorTests(TestCase):
    """テストカバレッジ棚卸し（review_test_doc_contract.txt指摘1）で発見：
    DocumentEditView.postの`except DBError:`は、DeleteViewAjaxTests.
    test_ajax_request_returns_json_error_on_db_failureと同じ書き込み失敗系分岐だが、
    こちらは一度もDBErrorをモックした検証が無かった。messages.errorの文言・
    リダイレクト先・DBに変更が反映されないことを確認する。"""

    def setUp(self):
        from documents.models import Document

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
        self.client.login(username="1", password="pass1234")
        self.document = Document(
            title="元のタイトル", department=self.department, group=self.group, category=self.category,
            year=2026, retention_period=self.retention_period, uploader=self.employee,
            expiry_date=datetime.date(2030, 1, 1),
        )
        self.document.file.save("original.pdf", ContentFile(b"AAAA"), save=False)
        self.document.save()

    def test_edit_view_db_failure_shows_error_and_does_not_update_document(self):
        from django.contrib.messages import get_messages

        from documents.models import Document

        get_response = self.client.get(f"/documents/{self.document.pk}/edit/")
        token = get_response.context["token"]

        with mock.patch.object(Document, "save", side_effect=DBError("db down")):
            response = self.client.post(
                f"/documents/{self.document.pk}/edit/",
                {
                    "token": token,
                    "department": self.department.pk,
                    "group": self.group.pk,
                    "category": self.category.pk,
                    "year": 2026,
                    "title_0": "更新後タイトル",
                    "retention_period": self.retention_period.pk,
                    "privacy_flag": "False",
                    "memo": "",
                },
            )

        self.assertRedirects(response, f"/documents/{self.document.pk}/edit/")
        texts = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertTrue(any("更新に失敗しました" in t for t in texts))
        self.document.refresh_from_db()
        self.assertEqual(self.document.title, "元のタイトル")


class EditScreenRetentionPermissionTests(TestCase):
    """xlsx 権限管理!B172-175(Rev1.1)「文書管理-文書-保存満了日変更」。OFFの場合、保存済み
    文書の保存期間は編集できない（documents.forms.UploadStep2Form、permissions.services.
    can_edit_retention）。新規保管（UploadStep2View）はedit_mode=Falseのため対象外。
    """

    def setUp(self):
        from documents.models import Document

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
        self.retention_1y = RetentionPeriod.objects.create(
            kbn=RetentionKbn.DOCUMENT, period_value=1, period_unit=RetentionPeriodUnit.YEAR, display_order=1
        )
        self.retention_3y = RetentionPeriod.objects.create(
            kbn=RetentionKbn.DOCUMENT, period_value=3, period_unit=RetentionPeriodUnit.YEAR, display_order=2
        )
        self.client.login(username="1", password="pass1234")
        self.document = Document(
            title="保存期間変更確認用", department=self.department, group=self.group, category=self.category,
            year=2026, retention_period=self.retention_1y, uploader=self.employee,
            expiry_date=datetime.date(2099, 1, 1),
        )
        self.document.file.save("doc.pdf", ContentFile(b"%PDF-1.4"), save=False)
        self.document.save()

    def _post_edit(self, retention_period):
        get_response = self.client.get(f"/documents/{self.document.pk}/edit/")
        token = get_response.context["token"]
        return self.client.post(
            f"/documents/{self.document.pk}/edit/",
            {
                "token": token,
                "department": self.department.pk,
                "group": self.group.pk,
                "category": self.category.pk,
                "year": self.document.year,
                "title_0": self.document.title,
                "retention_period": retention_period.pk,
                "privacy_flag": "True",
                "memo": "",
            },
        )

    def test_without_permission_retention_change_is_ignored(self):
        PermissionProfile.objects.create(
            employee=self.employee, role=PermissionRole.STAFF, doc_retention_edit=False
        )
        self._post_edit(self.retention_3y)
        self.document.refresh_from_db()
        self.assertEqual(self.document.retention_period, self.retention_1y)

    def test_with_permission_retention_change_is_applied(self):
        PermissionProfile.objects.create(
            employee=self.employee, role=PermissionRole.STAFF, doc_retention_edit=True
        )
        self._post_edit(self.retention_3y)
        self.document.refresh_from_db()
        self.assertEqual(self.document.retention_period, self.retention_3y)

    def test_admin_can_change_retention_without_flag(self):
        PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.ADMIN)
        self._post_edit(self.retention_3y)
        self.document.refresh_from_db()
        self.assertEqual(self.document.retention_period, self.retention_3y)


class UploadStep2FormDepartmentInitialTests(TestCase):
    """xlsx 保管!B78-82「部署名欄の初期値はログインユーザーの部署名をセット」（管理者は加えて
    「選択」ボタンで別部署に変更可能）。新規登録画面（edit_mode=False）は権限に関わらず常に
    ログインユーザーの部署が初期値になるが、編集画面（edit_mode=True）は既存文書の部署を
    view側がinitialで渡すため、ここで上書きしてはいけない（documents.forms.UploadStep2Form
    参照。上書きすると年欄で修正済みの「触れていないのに値が変わる」のと同種の事故になる）。
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
        from documents.forms import UploadStep2Form

        form = UploadStep2Form(employee=self.admin, edit_mode=False)
        self.assertEqual(form["department"].value(), self.admin.department_id)

    def test_staff_new_registration_defaults_to_own_department(self):
        from documents.forms import UploadStep2Form

        form = UploadStep2Form(employee=self.staff, edit_mode=False)
        self.assertEqual(form["department"].value(), self.staff.department_id)
        self.assertTrue(form.fields["department"].disabled)

    def test_admin_edit_screen_keeps_documents_own_department(self):
        """管理者が自部署とは異なる部署の文書を編集する場合、初期値は文書側の部署のままで
        管理者自身の部署に書き換わらないこと。"""
        from documents.forms import UploadStep2Form

        form = UploadStep2Form(
            employee=self.admin, edit_mode=True, initial={"department": self.other_department.pk}
        )
        self.assertEqual(form["department"].value(), self.other_department.pk)

    def test_staff_edit_screen_is_forced_to_own_department_regardless_of_initial(self):
        """非管理者は編集画面でも「選択」ボタン非表示・自部署固定（documents.views.
        DocumentEditView.postがcan_select_department=Falseの場合department値自体を強制上書き
        することと対応、改ざん防止のため一貫して自部署のみが初期値・送信値になる）。"""
        from documents.forms import UploadStep2Form

        form = UploadStep2Form(
            employee=self.staff, edit_mode=True, initial={"department": self.other_department.pk}
        )
        self.assertEqual(form["department"].value(), self.staff.department_id)
        self.assertTrue(form.fields["department"].disabled)


class UploadStep2FormGroupCategoryScopeTests(TestCase):
    """documents.forms.UploadStep2Form/SearchFormの分類(group)/カテゴリー(category)絞り込み
    （Rev1.2部署スコープ、core.forms.scoped_group_and_category_querysets）。
    """

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
        PermissionProfile.objects.create(employee=self.staff, role=PermissionRole.STAFF)
        self.own_group = Group.objects.create(
            code="A", name="自部署の分類", doc_kbn=DocKbn.DOCUMENT, department=self.department
        )
        self.own_category = Category.objects.create(
            code="001", name="自部署のカテゴリー", group=self.own_group, doc_kbn=DocKbn.DOCUMENT
        )
        self.other_group = Group.objects.create(
            code="B", name="他部署の分類", doc_kbn=DocKbn.DOCUMENT, department=self.other_department
        )
        self.other_category = Category.objects.create(
            code="002", name="他部署のカテゴリー", group=self.other_group, doc_kbn=DocKbn.DOCUMENT,
            department=self.other_department,
        )
        self.retention_period = RetentionPeriod.objects.create(
            kbn=RetentionKbn.DOCUMENT, period_value=1, period_unit=RetentionPeriodUnit.YEAR, display_order=1
        )
        self.client.login(username="1", password="x")

    def test_posting_out_of_scope_group_id_is_rejected_by_form_validation(self):
        """テストカバレッジ棚卸しで発見：分類/カテゴリーの部署スコープはクライアント側の
        queryset絞り込み（プルダウン非表示）だけでなく、ModelChoiceField.clean()が
        POSTされたpkそのものをqueryset外として拒否することをHTTP経由で確認する
        （CLAUDE.mdが繰り返し警告する「クライアント側非表示≠サーバー側強制」の実証）。"""
        self.client.post(
            "/documents/upload/step1/",
            {"files": [SimpleUploadedFile("a.pdf", b"dummy", content_type="application/pdf")]},
        )
        step2 = self.client.get("/documents/upload/step2/")
        token = step2.context["token"]
        response = self.client.post(
            "/documents/upload/step2/",
            {
                "token": token,
                "department": self.department.pk,
                "group": self.other_group.pk,
                "category": self.other_category.pk,
                "year": 2026,
                "retention_period": self.retention_period.pk,
                "privacy_flag": "False",
                "memo": "",
                "title_0": "テスト文書",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["form"].is_valid())
        self.assertIn("group", response.context["form"].errors)
        self.assertIn("category", response.context["form"].errors)

    def test_department_scope_overrides_cross_department_doc_visible_groups_grant(self):
        """documents/forms.pyの部署スコープ導入時、権限管理でdoc_visible_groupsに他部署の
        分類を明示的に許可していた場合との優先順位が未確定だった（品質レビューで発見）。
        2026-08-25にユーザーへ確認し「部署スコープを常に優先する」で確定したため、
        この意図した挙動を固定するリグレッションテストとして残す
        （core.forms.scoped_group_and_category_querysets docstring参照）。"""
        from documents.forms import UploadStep2Form

        profile = PermissionProfile.objects.get(employee=self.staff)
        profile.doc_visible_groups.add(self.own_group, self.other_group)

        form = UploadStep2Form(employee=self.staff)
        group_ids = set(form.fields["group"].queryset.values_list("pk", flat=True))
        self.assertIn(self.own_group.pk, group_ids)
        self.assertNotIn(self.other_group.pk, group_ids)


class DetailAPIViewTests(TestCase):
    """popup-detail（検索・閲覧画面の一覧ダブルクリックで開く詳細ポップアップ）用のJSON API。
    2026-08-12、ユーザー依頼でpreview_url/preview_kindを追加した（documents.api.DetailAPIView）。
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
        self.client.login(username="1", password="pass1234")

        from documents.models import Document

        self.document = Document(
            title="詳細確認用", department=self.department, group=self.group, category=self.category,
            year=2026, retention_period=self.retention_period, uploader=self.employee,
            expiry_date=datetime.date(2030, 1, 1),
        )
        self.document.file.save("photo.png", ContentFile(b"PNGDATA"), save=False)
        self.document.save()

    def test_without_permission_preview_url_is_null_but_kind_is_returned(self):
        # 2026-08-13ユーザー報告対応：popup-detail側で「権限不足で表示できない」と案内するには
        # 拡張子判定（preview_kind）自体は権限に関わらず必要。preview_urlは実データを指すため
        # 引き続き権限gatingする（documents.api.DetailAPIView参照）。
        response = self.client.get(f"/documents/api/{self.document.pk}/")
        data = response.json()
        self.assertIsNone(data["preview_url"])
        self.assertEqual(data["preview_kind"], "image")

    def test_with_permission_returns_preview_url_and_kind(self):
        PermissionProfile.objects.create(
            employee=self.employee, role=PermissionRole.STAFF, doc_download=True
        )
        response = self.client.get(f"/documents/api/{self.document.pk}/")
        data = response.json()
        self.assertEqual(data["preview_url"], f"/documents/{self.document.pk}/preview/")
        self.assertEqual(data["preview_kind"], "image")

    def test_unsupported_extension_yields_null_preview_kind_even_with_permission(self):
        from documents.models import Document

        PermissionProfile.objects.create(
            employee=self.employee, role=PermissionRole.STAFF, doc_download=True
        )
        document = Document(
            title="不明拡張子", department=self.department, group=self.group, category=self.category,
            year=2026, retention_period=self.retention_period, uploader=self.employee,
            expiry_date=datetime.date(2030, 1, 1),
        )
        document.file.save("doc.docx", ContentFile(b"dummy"), save=False)
        document.save()

        response = self.client.get(f"/documents/api/{document.pk}/")
        data = response.json()
        self.assertIsNotNone(data["preview_url"])
        self.assertIsNone(data["preview_kind"])

    def test_deleted_document_yields_null_edit_and_delete_urls(self):
        """削除済み文書一覧の詳細ポップアップで「変更」が404になっていた不具合の修正
        （2026-08-12ユーザー報告）：DocumentEditView.get_object()がis_deleted=Falseでしか対象を
        取得できない以上、API側でedit_urlをNoneにしてボタンを無効化するのが正しい対応。delete_urlも
        Rev1.2（xlsx 検索・閲覧・変更!B331,B337,B342「削除されている(削除フラグがTrue)文書は、
        ボタンを非表示とする」）でNoneになるよう変更した（documents.services.can_delete docstring
        参照。以前は「ゴミ箱保管中の削除ボタンで完全削除」機能のため常に返していたが、その機能は
        廃止した）。download_urlも同じB331の対象（2026-08-24追加分の再監査で発見：以前は
        can_download権限のみを見ておりis_deleted判定が漏れていたため、削除済み文書でも
        ダウンロードボタンが表示され続けていた）。"""
        self.document.is_deleted = True
        self.document.save(update_fields=["is_deleted"])

        response = self.client.get(f"/documents/api/{self.document.pk}/")
        data = response.json()
        self.assertIsNone(data["edit_url"])
        self.assertIsNone(data["delete_url"])
        self.assertIsNone(data["download_url"])

    def test_non_deleted_document_still_has_edit_and_delete_urls(self):
        PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.STAFF, doc_download=True)
        response = self.client.get(f"/documents/api/{self.document.pk}/")
        data = response.json()
        self.assertEqual(data["edit_url"], f"/documents/{self.document.pk}/edit/")
        self.assertEqual(data["delete_url"], f"/documents/{self.document.pk}/delete/")
        self.assertEqual(data["download_url"], f"/documents/{self.document.pk}/download/")

    def test_deleted_document_yields_null_preview_url_even_with_permission(self):
        """テストカバレッジ棚卸しで発見：download_url/edit_url/delete_urlの
        is_deleted=Trueゲーティングはdoc_downloadあり/なし両方でテストされていたが、
        preview_urlは常にcan_download=False（権限無し）の状態でしかテストされておらず、
        「権限はあるがis_deletedで弾かれる」経路が未検証だった。"""
        PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.STAFF, doc_download=True)
        self.document.is_deleted = True
        self.document.save(update_fields=["is_deleted"])

        response = self.client.get(f"/documents/api/{self.document.pk}/")
        data = response.json()
        self.assertIsNone(data["preview_url"])

    def test_cross_department_document_access_is_denied(self):
        """テストカバレッジ棚卸しで発見：DetailAPIView.getの他部署アクセス拒否分岐
        （can_select_departmentがFalseかつdepartment不一致）が一度もテストで発火していなかった。
        回帰時（条件の反転等）に他部署の文書メタ情報が漏れても検知できない状態だった。"""
        other_department = Department.objects.create(
            branch_code="999", branch_name="別支店", section_code="", section_name=""
        )
        from documents.models import Document

        other_document = Document(
            title="他部署の文書", department=other_department, group=self.group, category=self.category,
            year=2026, retention_period=self.retention_period, uploader=self.employee,
            expiry_date=datetime.date(2030, 1, 1),
        )
        other_document.file.save("other.pdf", ContentFile(b"dummy"), save=False)
        other_document.save()

        response = self.client.get(f"/documents/api/{other_document.pk}/")
        self.assertEqual(response.status_code, 403)

    def test_document_past_delete_window_yields_null_delete_url(self):
        """xlsx 保管!B300,B581・検索・閲覧・変更!B339-340「初回登録から1週間以上経過している
        ものは削除不可。ボタンを非表示にする」（documents.services.can_delete）。"""
        from documents.models import Document

        Document.objects.filter(pk=self.document.pk).update(
            save_date=timezone.now() - datetime.timedelta(days=8)
        )
        response = self.client.get(f"/documents/api/{self.document.pk}/")
        data = response.json()
        self.assertIsNone(data["delete_url"])

    def test_deleted_document_past_delete_window_yields_null_delete_url(self):
        """ゴミ箱保管中（is_deleted=True）は1週間制限を待つまでもなく、Rev1.2で削除不可
        （delete_url None）になる（documents.services.can_delete docstring参照）。"""
        from documents.models import Document

        Document.objects.filter(pk=self.document.pk).update(
            save_date=timezone.now() - datetime.timedelta(days=30), is_deleted=True
        )
        response = self.client.get(f"/documents/api/{self.document.pk}/")
        data = response.json()
        self.assertIsNone(data["delete_url"])


class DepartmentScopeAccessControlTests(TestCase):
    """セキュリティレビューで発見：documents.search_services.build_querysetは部署スコープ
    （organizations.services.visible_department_ids）を適用済みだったが、ダウンロード・
    プレビュー・編集・削除・一括編集・一括ダウンロードの各ビューには適用されておらず、
    doc_download権限さえあれば部署をまたいだ直接pkアクセスで他部署の文書を閲覧・編集・削除
    できてしまっていた（documents.services.scoped_get_object_or_404導入で修正、2026-08-25。
    contracts.tests.DepartmentScopeAccessControlTestsと同じ設計）。
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
        # 閲覧部署範囲テーブルとも未設定の、最も一般的な非管理者
        # （document_searchable_department_ids(employee) == {own_department.pk}のみ）。
        PermissionProfile.objects.create(
            employee=self.employee, role=PermissionRole.STAFF, doc_download=True
        )
        self.client.login(username="1", password="pass1234")

        group = Group.objects.create(code="A", name="分類Ａ", doc_kbn=DocKbn.DOCUMENT)
        category = Category.objects.create(code="001", name="カテゴリーＡ", group=group, doc_kbn=DocKbn.DOCUMENT)
        retention_period = RetentionPeriod.objects.create(
            kbn=RetentionKbn.DOCUMENT, period_value=1, period_unit=RetentionPeriodUnit.YEAR, display_order=1
        )
        from documents.models import Document

        self.other_document = Document(
            title="他部署の文書", department=self.other_department, group=group, category=category,
            year=2026, retention_period=retention_period, uploader=self.employee,
            expiry_date=datetime.date(2036, 1, 1),
        )
        self.other_document.file.save("other.pdf", ContentFile(b"dummy"), save=False)
        self.other_document.save()

    def test_download_of_other_department_document_returns_404(self):
        response = self.client.get(f"/documents/{self.other_document.pk}/download/")
        self.assertEqual(response.status_code, 404)

    def test_preview_of_other_department_document_returns_404(self):
        response = self.client.get(f"/documents/{self.other_document.pk}/preview/")
        self.assertEqual(response.status_code, 404)

    def test_edit_screen_of_other_department_document_returns_404(self):
        response = self.client.get(f"/documents/{self.other_document.pk}/edit/")
        self.assertEqual(response.status_code, 404)

    def test_delete_of_other_department_document_returns_404(self):
        from documents.models import Document

        response = self.client.post(
            f"/documents/{self.other_document.pk}/delete/", HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(response.status_code, 404)
        self.other_document.refresh_from_db()
        self.assertFalse(self.other_document.is_deleted)
        self.assertTrue(Document.objects.filter(pk=self.other_document.pk, is_deleted=False).exists())

    def test_bulk_edit_start_silently_excludes_other_department_pk(self):
        response = self.client.post(
            "/documents/bulk-edit/start/", {"pks": [self.other_document.pk]}
        )
        self.assertRedirects(response, "/documents/search/")
        self.assertIsNone(self.client.session.get("documents_bulk_edit"))

    def test_bulk_edit_direct_access_to_other_department_document_returns_404(self):
        """BulkEditStartViewが通常は除外するが、セッション状態を直接構築した場合
        （URL直打ち相当）もBulkEditView自体が部署スコープを検証する。"""
        from core import bulk_edit_services

        session = self.client.session
        bulk_edit_services.start_bulk_edit(session, "documents_bulk_edit", [self.other_document.pk])
        session.save()
        response = self.client.get("/documents/bulk-edit/")
        self.assertEqual(response.status_code, 404)

    def test_bulk_download_silently_excludes_other_department_document(self):
        import zipfile
        from io import BytesIO

        own_group = Group.objects.create(code="B", name="自部署分類", doc_kbn=DocKbn.DOCUMENT)
        own_category = Category.objects.create(
            code="002", name="自部署カテゴリー", group=own_group, doc_kbn=DocKbn.DOCUMENT
        )
        own_retention_period = RetentionPeriod.objects.create(
            kbn=RetentionKbn.DOCUMENT, period_value=1, period_unit=RetentionPeriodUnit.YEAR, display_order=2
        )
        from documents.models import Document

        own_document = Document(
            title="own", department=self.own_department, group=own_group, category=own_category,
            year=2026, retention_period=own_retention_period, uploader=self.employee,
            expiry_date=datetime.date(2036, 1, 1),
        )
        own_document.file.save("own.txt", ContentFile(b"hello"), save=False)
        own_document.save()

        response = self.client.post(
            "/documents/bulk-download/", {"pks": [own_document.pk, self.other_document.pk]}
        )
        self.assertEqual(response.status_code, 200)
        zf = zipfile.ZipFile(BytesIO(response.content))
        names = zf.namelist()
        self.assertEqual(len(names), 1)
        self.assertTrue(any("own" in n for n in names))

    def test_admin_can_access_other_department_document(self):
        """部署スコープは非管理者のみに適用される（管理者はcan_select_departmentがTrueを
        返し、document_searchable_department_idsがNone＝無制限になるため、従来通り全部署に
        アクセスできる）。"""
        admin = Employee.objects.create_user(
            employee_no="2", name="管理者", password="pass1234",
            department=self.own_department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        PermissionProfile.objects.create(employee=admin, role=PermissionRole.ADMIN)
        self.client.login(username="2", password="pass1234")

        response = self.client.get(f"/documents/{self.other_document.pk}/download/")
        self.assertEqual(response.status_code, 200)


class DeleteViewWindowTests(TestCase):
    """documents.views.DeleteView.postのサーバー側1週間経過チェック。"""

    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.employee = Employee.objects.create_user(
            employee_no="1", name="テスト太郎", password="pass1234",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        group = Group.objects.create(code="A", name="分類Ａ", doc_kbn=DocKbn.DOCUMENT)
        category = Category.objects.create(code="001", name="カテゴリーＡ", group=group, doc_kbn=DocKbn.DOCUMENT)
        retention_period = RetentionPeriod.objects.create(
            kbn=RetentionKbn.DOCUMENT, period_value=1, period_unit=RetentionPeriodUnit.YEAR, display_order=1
        )
        self.client.login(username="1", password="pass1234")

        from documents.models import Document

        self.document = Document(
            title="削除期限確認用", department=self.department, group=group, category=category,
            year=2026, retention_period=retention_period, uploader=self.employee,
            expiry_date=datetime.date(2030, 1, 1),
        )
        self.document.file.save("doc.pdf", ContentFile(b"dummy"), save=False)
        self.document.save()
        Document.objects.filter(pk=self.document.pk).update(
            save_date=timezone.now() - datetime.timedelta(days=8)
        )

    def test_delete_rejected_after_window_via_ajax(self):
        response = self.client.post(
            f"/documents/{self.document.pk}/delete/", HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.json()["success"])
        self.document.refresh_from_db()
        self.assertFalse(self.document.is_deleted)

    def test_delete_rejected_after_window_non_ajax(self):
        response = self.client.post(f"/documents/{self.document.pk}/delete/")
        self.assertEqual(response.status_code, 403)
        self.document.refresh_from_db()
        self.assertFalse(self.document.is_deleted)


class UploadFileIOErrorTests(TestCase):
    """アップロード時のファイルI/O例外（ディスク容量不足・一時ファイル欠損等）を捕捉し、
    利用者にエラーメッセージを表示する（監査で発見・修正：以前は未捕捉のまま伝播していた）。
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

    def test_step1_save_failure_shows_error_message(self):
        from django.contrib.messages import get_messages
        from django.core.files.uploadedfile import SimpleUploadedFile

        from core.upload_services import PendingFileStorageError

        with mock.patch(
            "documents.views.upload_services.save_pending_files",
            side_effect=PendingFileStorageError("disk full"),
        ):
            response = self.client.post(
                "/documents/upload/step1/",
                {"files": [SimpleUploadedFile("a.pdf", b"AAAA", content_type="application/pdf")]},
            )
        self.assertEqual(response.status_code, 200)
        texts = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertTrue(any("ファイルの保存に失敗しました" in t for t in texts))

    def test_step2_open_pending_file_failure_rolls_back_and_shows_error(self):
        """保管画面２のファイルI/O失敗時、transaction.atomic()によりDocumentが1件も
        作成されないこと（部分登録の防止）を確認する。"""
        import re

        from django.core.files.uploadedfile import SimpleUploadedFile

        from documents.models import Document

        group = Group.objects.create(code="A", name="分類Ａ", doc_kbn=DocKbn.DOCUMENT)
        category = Category.objects.create(
            code="001", name="カテゴリーＡ", group=group, doc_kbn=DocKbn.DOCUMENT
        )
        retention_period = RetentionPeriod.objects.create(
            kbn=RetentionKbn.DOCUMENT, period_value=1, period_unit=RetentionPeriodUnit.YEAR, display_order=1
        )
        self.client.post(
            "/documents/upload/step1/",
            {"files": [SimpleUploadedFile("a.pdf", b"AAAA", content_type="application/pdf")]},
        )
        step2 = self.client.get("/documents/upload/step2/")
        token = re.search(r'name="token" value="([^"]+)"', step2.content.decode("utf-8")).group(1)

        before = set(Document.objects.values_list("pk", flat=True))
        with mock.patch(
            "documents.views.upload_services.open_pending_file", side_effect=OSError("temp file missing")
        ):
            response = self.client.post(
                "/documents/upload/step2/",
                {
                    "token": token,
                    "department": self.department.pk,
                    "group": group.pk,
                    "category": category.pk,
                    "year": 2026,
                    "retention_period": retention_period.pk,
                    "privacy_flag": "True",
                    "title_0": "テスト文書",
                },
            )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/documents/upload/step2/")
        self.assertEqual(set(Document.objects.values_list("pk", flat=True)), before)


class UploadStep2ViewValidationTests(TestCase):
    """保管画面２のフォームバリデーション・二重送信対策（テストカバレッジ棚卸しで発見：
    UploadStep2View/DocumentEditView/BulkEditView共通のform.is_valid()==False再描画経路・
    consume_token失敗経路のいずれもテストが無かった。ここではUploadStep2Viewを代表として
    検証する）。"""

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
        self.client.login(username="1", password="pass1234")
        self.client.post(
            "/documents/upload/step1/",
            {"files": [SimpleUploadedFile("a.pdf", b"dummy", content_type="application/pdf")]},
        )

    def _valid_data(self, token):
        return {
            "token": token,
            "department": self.department.pk,
            "group": self.group.pk,
            "category": self.category.pk,
            "year": 2026,
            "retention_period": self.retention_period.pk,
            "privacy_flag": "False",
            "memo": "",
            "title_0": "テスト文書",
        }

    def test_invalid_form_data_re_renders_with_errors(self):
        """必須項目（分類）欠落時、200で再描画されform.errorsに反映されること。"""
        step2 = self.client.get("/documents/upload/step2/")
        data = self._valid_data(step2.context["token"])
        del data["group"]
        response = self.client.post("/documents/upload/step2/", data)
        self.assertEqual(response.status_code, 200)
        self.assertIn("group", response.context["form"].errors)

        from documents.models import Document

        self.assertFalse(Document.objects.exists())

    def test_wrong_token_rejects_with_error_message_and_redirect(self):
        """二重送信対策トークンが不一致の場合、保管せずstep1へリダイレクトしエラーメッセージを出す。"""
        from django.contrib.messages import get_messages

        from documents.models import Document

        self.client.get("/documents/upload/step2/")  # トークン発行
        response = self.client.post("/documents/upload/step2/", self._valid_data("invalid-token"))
        self.assertRedirects(response, "/documents/upload/step1/")
        texts = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertTrue(any("二重に送信された可能性がある" in t for t in texts))
        self.assertFalse(Document.objects.exists())


class UploadStep2ImmediateExtractionTests(TestCase):
    """保管画面２登録後、core.text_extraction_services.try_immediate_text_layer_extractionが
    呼ばれ、テキスト層のあるPDFはその場でextracted_textが埋まることを確認する
    （全文検索基盤、2026-08-10追加）。pdfplumberの解析自体はモック化する。
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
        self.client.login(username="1", password="pass1234")
        self.group = Group.objects.create(code="A", name="分類Ａ", doc_kbn=DocKbn.DOCUMENT)
        self.category = Category.objects.create(
            code="001", name="カテゴリーＡ", group=self.group, doc_kbn=DocKbn.DOCUMENT
        )
        self.retention_period = RetentionPeriod.objects.create(
            kbn=RetentionKbn.DOCUMENT, period_value=1, period_unit=RetentionPeriodUnit.YEAR, display_order=1
        )
        self.client.post(
            "/documents/upload/step1/",
            {"files": [SimpleUploadedFile("a.pdf", b"AAAA", content_type="application/pdf")]},
        )
        step2 = self.client.get("/documents/upload/step2/")
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
        from documents.models import Document

        with mock.patch(
            "core.text_extraction_services.pdfplumber.open",
            return_value=self._mock_pdfplumber("十分な文字数を含む本文テキストです。"),
        ):
            response = self.client.post(
                "/documents/upload/step2/",
                {
                    "token": self.token,
                    "department": self.department.pk,
                    "group": self.group.pk,
                    "category": self.category.pk,
                    "year": 2026,
                    "retention_period": self.retention_period.pk,
                    "privacy_flag": "True",
                    "title_0": "テスト文書",
                },
            )
        self.assertEqual(response.status_code, 200)
        document = Document.objects.get(title="テスト文書")
        self.assertEqual(document.extracted_text, "十分な文字数を含む本文テキストです。")


class ChunkUploadAPITests(TestCase):
    """screen-storage1のチャンク分割アップロードAPI（documents:upload_chunk）。
    ja_pj_oldから移植した、大容量ファイルをMAX_UPLOAD_SIZE_BYTES超過時に5MBずつ分割送信する機能。
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

    def _post_chunk(self, upload_id, chunk_index, total_chunks, data, file_name="big.pdf"):
        return self.client.post(
            "/documents/upload/chunk/",
            {
                "upload_id": upload_id,
                "file_name": file_name,
                "chunk_index": chunk_index,
                "total_chunks": total_chunks,
                "file": SimpleUploadedFile("chunk", data),
            },
        )

    def test_all_chunks_received_registers_pending_file_for_step2(self):
        """2チャンクとも正常に送ると、GET/POSTを介さずセッションの保留ファイル一覧に登録され、
        保管画面１のPOSTが通常ファイル0件でもそのファイルを引き継いで保管画面２へ進めること。
        """
        response1 = self._post_chunk("upload-id-1", 0, 2, b"A" * 10)
        self.assertEqual(json.loads(response1.content)["status"], "chunk_received")

        response2 = self._post_chunk("upload-id-1", 1, 2, b"B" * 10)
        self.assertEqual(json.loads(response2.content)["status"], "completed")

        # 通常のfile input経由のファイルが0件でも、チャンク経由で登録済みのファイルがあるため
        # ファイル未選択エラーにならずstep2へ進む（documents.views.UploadStep1View.post参照）。
        step1_response = self.client.post("/documents/upload/step1/", {})
        self.assertRedirects(step1_response, "/documents/upload/step2/")

        step2_response = self.client.get("/documents/upload/step2/")
        self.assertContains(step2_response, "big")

    def test_missing_chunk_returns_error_and_does_not_register(self):
        """チャンク0を送らずいきなりチャンク1（最終チャンク）を送ると、結合時にチャンク0の
        欠落が検出されエラーになり、保留ファイル一覧には何も登録されないこと。"""
        response = self._post_chunk("upload-id-2", 1, 2, b"B" * 10)
        data = json.loads(response.content)
        self.assertEqual(data["status"], "error")
        self.assertIn("チャンク 0", data["message"])

        step1_response = self.client.post("/documents/upload/step1/", {})
        self.assertContains(step1_response, "ファイルが選択されていません")

    def test_invalid_upload_id_rejected(self):
        """upload_idはファイルパスの一部にそのまま使うため、英数字・ハイフン以外を含む値
        （ディレクトリトラバーサルの試み等）は400で拒否する。"""
        response = self._post_chunk("../../etc", 0, 1, b"A")
        self.assertEqual(response.status_code, 400)

    def test_malformed_request_returns_400(self):
        response = self.client.post("/documents/upload/chunk/", {"upload_id": "abc"})
        self.assertEqual(response.status_code, 400)


class OptionsAPIViewTests(TestCase):
    """popup-select（部署/分類/年/カテゴリー選択、screen-storage2/screen-searchで使用）の
    データ元であるcore.api.BaseOptionListAPIView（documents.api.OptionListAPIView経由）のHTTPテスト。
    監査で発見：_department_items()がcan_select_department（管理者のみ部署選択可）を適用しておらず、
    _group_items()のvisible_groups適用と非対称だった。以前はウィジェットのオフラインrender()しか
    テストされておらず、実際に叩かれるエンドポイント自体の検証が無かった。
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
        response = self.client.get("/documents/api/options/", {"type": "dept"})
        items = response.json()["items"]
        self.assertEqual([i["value"] for i in items], [self.department.pk])

    def test_type_dept_no_profile_only_sees_own_department(self):
        """PermissionProfile未作成の職員は最も制限の強い一般ロール扱い（permissions.services.
        get_role）のため、こちらも自部署のみになること。"""
        response = self.client.get("/documents/api/options/", {"type": "dept"})
        items = response.json()["items"]
        self.assertEqual([i["value"] for i in items], [self.department.pk])

    def test_type_dept_admin_sees_all_departments(self):
        PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.ADMIN)
        response = self.client.get("/documents/api/options/", {"type": "dept"})
        items = response.json()["items"]
        self.assertEqual(
            {i["value"] for i in items}, {self.department.pk, self.other_department.pk}
        )

    def test_type_group_filtered_by_visible_groups(self):
        visible = Group.objects.create(code="A", name="分類Ａ", doc_kbn=DocKbn.DOCUMENT)
        hidden = Group.objects.create(code="B", name="分類Ｂ", doc_kbn=DocKbn.DOCUMENT)
        profile = PermissionProfile.objects.create(employee=self.employee, role=PermissionRole.STAFF)
        profile.doc_visible_groups.add(visible)

        response = self.client.get("/documents/api/options/", {"type": "group"})
        items = response.json()["items"]
        self.assertEqual([i["value"] for i in items], [visible.pk])
        self.assertNotIn(hidden.pk, [i["value"] for i in items])

    def test_type_group_no_restriction_returns_all_document_groups(self):
        Group.objects.create(code="A", name="分類Ａ", doc_kbn=DocKbn.DOCUMENT)
        Group.objects.create(code="B", name="分類Ｂ", doc_kbn=DocKbn.DOCUMENT)
        # 契約書側の分類は対象外（doc_kbnで絞り込まれること）。
        Group.objects.create(code="C", name="契約分類Ｃ", doc_kbn=DocKbn.CONTRACT)

        response = self.client.get("/documents/api/options/", {"type": "group"})
        items = response.json()["items"]
        self.assertEqual(len(items), 2)

    def test_type_category_returns_items_for_document_kbn_only(self):
        group = Group.objects.create(code="A", name="分類Ａ", doc_kbn=DocKbn.DOCUMENT)
        Category.objects.create(code="001", name="カテゴリーＡ", group=group, doc_kbn=DocKbn.DOCUMENT)
        Category.objects.create(code="002", name="契約カテゴリー", group=group, doc_kbn=DocKbn.CONTRACT)

        response = self.client.get("/documents/api/options/", {"type": "category"})
        items = response.json()["items"]
        self.assertEqual([i["label"] for i in items], ["カテゴリーＡ"])

    def test_type_year_returns_recent_years_including_current(self):
        current = datetime.date.today().year
        response = self.client.get("/documents/api/options/", {"type": "year"})
        values = [i["value"] for i in response.json()["items"]]
        self.assertIn(current, values)

    def test_invalid_type_returns_400(self):
        response = self.client.get("/documents/api/options/", {"type": "unknown"})
        self.assertEqual(response.status_code, 400)

    def test_requires_login(self):
        self.client.logout()
        response = self.client.get("/documents/api/options/", {"type": "dept"})
        self.assertEqual(response.status_code, 302)


class DocumentSaveNormalizationTests(TestCase):
    """documents.models.Document.saveの`update_fields`正規化カラム同期
    （テストカバレッジ棚卸しで発見：docstringが説明する「update_fieldsにtitle_normalized等を
    追加し忘れるとDBへ反映されない」バグクラスに対する直接のリグレッションテストが無かった）。
    """

    def setUp(self):
        self.department = Department.objects.create(
            branch_code="000", branch_name="本店", section_code="01", section_name="総務部"
        )
        self.employee = Employee.objects.create_user(
            employee_no="1", name="テスト太郎", password="x",
            department=self.department, rank=Rank.KOSAYAKU, position=Position.KACHO,
        )
        group = Group.objects.create(code="A", name="分類Ａ", doc_kbn=DocKbn.DOCUMENT)
        category = Category.objects.create(code="001", name="カテゴリーＡ", group=group, doc_kbn=DocKbn.DOCUMENT)
        retention_period = RetentionPeriod.objects.create(
            kbn=RetentionKbn.DOCUMENT, period_value=1, period_unit=RetentionPeriodUnit.YEAR, display_order=1
        )
        from documents.models import Document

        self.document = Document(
            title="旧タイトル", department=self.department, group=group, category=category,
            year=2026, retention_period=retention_period, uploader=self.employee,
            expiry_date=datetime.date(2030, 1, 1),
        )
        self.document.file.save("doc.pdf", ContentFile(b"dummy"), save=False)
        self.document.save()

    def test_update_fields_title_only_still_persists_normalized_shadow_column(self):
        from core.text_normalization import normalize_for_search
        from documents.models import Document

        self.document.title = "新タイトルＡＢＣ"
        self.document.save(update_fields=["title"])

        reloaded = Document.objects.get(pk=self.document.pk)
        self.assertEqual(reloaded.title, "新タイトルＡＢＣ")
        self.assertEqual(reloaded.title_normalized, normalize_for_search("新タイトルＡＢＣ"))

    def test_update_fields_extracted_text_only_still_persists_normalized_shadow_column(self):
        from core.text_normalization import normalize_for_search
        from documents.models import Document

        self.document.extracted_text = "本文サンプルＸＹＺ"
        self.document.save(update_fields=["extracted_text"])

        reloaded = Document.objects.get(pk=self.document.pk)
        self.assertEqual(reloaded.extracted_text, "本文サンプルＸＹＺ")
        self.assertEqual(reloaded.extracted_text_normalized, normalize_for_search("本文サンプルＸＹＺ"))


class StoragePathTests(TestCase):
    """documents.storage_paths（テストカバレッジ棚卸しで発見：専用テストが1件も無く、
    パス構成のtypoや構造変更〈UUIDプレフィックスの脱落等〉が検知できない状態だった）。"""

    def setUp(self):
        self.department = Department.objects.create(
            branch_code="001", branch_name="本店", section_code="02", section_name="経理部"
        )
        group = Group.objects.create(code="A", name="分類Ａ", doc_kbn=DocKbn.DOCUMENT)
        self.category = Category.objects.create(
            code="010", name="カテゴリーＸ", group=group, doc_kbn=DocKbn.DOCUMENT
        )

    def test_document_upload_path_structure(self):
        from documents.storage_paths import document_upload_path

        instance = mock.Mock(year=2026, department=self.department, category=self.category)
        path = document_upload_path(instance, "報告書.pdf")
        prefix = "documents/2026/001-02/010/"
        self.assertTrue(path.startswith(prefix), path)
        remainder = path[len(prefix):]
        uuid_part, _, filename_part = remainder.partition("_")
        self.assertEqual(len(uuid_part), 32)
        self.assertEqual(filename_part, "報告書.pdf")

    def test_document_searchable_upload_path_uses_separate_directory(self):
        from documents.storage_paths import document_searchable_upload_path

        instance = mock.Mock(year=2026, department=self.department, category=self.category)
        path = document_searchable_upload_path(instance, "報告書.pdf")
        self.assertTrue(path.startswith("documents/2026/001-02/010/searchable/"), path)
        self.assertTrue(path.endswith("_報告書.pdf"))

    def test_upload_paths_are_unique_per_call_via_uuid(self):
        from documents.storage_paths import document_upload_path

        instance = mock.Mock(year=2026, department=self.department, category=self.category)
        path1 = document_upload_path(instance, "同名.pdf")
        path2 = document_upload_path(instance, "同名.pdf")
        self.assertNotEqual(path1, path2)
