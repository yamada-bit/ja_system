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
        form = GroupForm(
            data={"code": "1", "name": "分類Ａ改名", "doc_kbn": DocKbn.DOCUMENT}, instance=self.existing
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_deleted_group_code_can_be_reused(self):
        """論理削除(is_deleted)済みの分類コードは重複チェックの対象外とする。"""
        self.existing.is_deleted = True
        self.existing.save()
        form = GroupForm(data={"code": "1", "name": "新しい分類Ａ", "doc_kbn": DocKbn.DOCUMENT})
        self.assertTrue(form.is_valid(), form.errors)

    def test_fullwidth_code_converted_to_halfwidth(self):
        """xlsx 分類管理!B116(Rev1.1)「半角数字のみ許可する。(全角の場合は登録時に半角へ変換)」。"""
        form = GroupForm(data={"code": "３", "name": "分類Ｃ", "doc_kbn": DocKbn.DOCUMENT})
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

    def test_fullwidth_code_converted_to_halfwidth(self):
        """xlsx カテゴリー管理!B113(Rev1.1)「半角数字のみ許可する。(全角の場合は登録時に半角へ変換)」。"""
        form = CategoryForm(
            data={"code": "００２", "name": "新カテゴリー", "group": self.group.pk, "doc_kbn": DocKbn.DOCUMENT}
        )
        self.assertTrue(form.is_valid(), form.errors)
        category = form.save()
        self.assertEqual(category.code, "002")

    def test_non_digit_code_rejected(self):
        form = CategoryForm(
            data={"code": "CA1", "name": "新カテゴリー", "group": self.group.pk, "doc_kbn": DocKbn.DOCUMENT}
        )
        self.assertFalse(form.is_valid())


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
                {"token": token, "code": "A", "name": "重複分類", "doc_kbn": DocKbn.DOCUMENT},
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
                    "group": group.pk, "doc_kbn": DocKbn.DOCUMENT,
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
