import logging

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Case, Count, F, IntegerField, Q, When
from django.db.utils import IntegrityError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import urlencode
from django.views import View

from audit import services as audit_services
from core.double_submit import consume_token, issue_token
from masters.forms import CategoryForm, CategorySearchForm, GroupForm, GroupSearchForm, RetentionPeriodForm
from masters.models import Category, DocKbn, EapprovalDocName, Group, RetentionKbn, RetentionPeriod
from masters.services import department_scope_ids, scope_queryset_by_department
from permissions.mixins import SettingsMenuAccessMixin
from permissions.models import PermissionRole
from permissions.services import get_role

logger = logging.getLogger(__name__)


# 書類管理区分(doc_kbn)の並び順は「文書管理、契約書管理の順」（xlsx 分類管理!H53、
# カテゴリー管理!H54）。doc_kbnの実値は"document"/"contract"で、文字列としては
# "contract" < "document"のため単純にorder_by("doc_kbn")すると契約書管理が先に来てしまう
# （2026-08-17、xlsxの「▲▼ボタン」列見出しソート追加作業中に発見・修正）。Caseで
# 文書管理=0/契約書管理=1に読み替えてから並べる。
_DOC_KBN_ORDER = Case(When(doc_kbn=DocKbn.DOCUMENT, then=0), default=1, output_field=IntegerField())


def _group_queryset_with_counts():
    """一覧の「文書件数」列。書類管理区分(doc_kbn)によって数える対象がdocuments.Documentか
    contracts.Contractかで異なるため、Count集計を2種類（related_name違い）annotateしてから
    doc_kbnに応じてどちらを使うかを`item_count`にまとめる（表示されている「文書件数」列と
    ソート対象を一致させるため。xlsx 分類管理!B58「文書件数」参照）。
    """
    return Group.objects.filter(is_deleted=False).select_related("department").annotate(
        doc_count=Count("documents", distinct=True), contract_count=Count("contracts", distinct=True)
    ).annotate(
        item_count=Case(
            When(doc_kbn=DocKbn.DOCUMENT, then=F("doc_count")),
            default=F("contract_count"),
            output_field=IntegerField(),
        )
    )


# screen-class-listのソート対象列（xlsx 分類管理!B55-58「下記項目に▲▼ボタンにて昇順/降順
# 切替が可能なようにする。(文書検索画面の一覧表示部と機能同等)」）。"department"はRev1.2で追加
# （xlsx B58「部署　※部署名ではなく、部課コードで昇順/降順」）、GroupListView.getで複合ソート
# として特殊扱いする（AUTHORITY_SORT_FIELDSのdepartment扱いと同じパターン）。
GROUP_SORT_FIELDS = {
    "code": "code",
    "name": "name",
    "count": "item_count",
}


class GroupListView(LoginRequiredMixin, SettingsMenuAccessMixin, View):
    """screen-class-list。1ページ100件目安（xlsx B62、Rev1.1で50→100件）。列見出しの▲▼ソート
    （分類コード/分類名/文書件数）は、文書検索画面と同じsort_url/sort_arrowの仕組みを使う
    （2026-08-17、xlsxユーザー指示により追加）。

    Rev1.2で「部署」検索プルダウン（管理者のみ表示）と部署単位の閲覧範囲が追加された
    （xlsx B35,B73-75）。管理者は全部署、それ以外は自部署のみを閲覧できる
    （masters.services.department_scope_ids）。一覧の「部署」列も非管理者には表示しない
    （xlsx B75「一覧の「部署」を非表示」）。
    """

    template_name = "masters/class_list.html"
    PAGE_SIZE = 100
    settings_menu_key = "class_management"

    def get(self, request):
        # request.GET or Noneは避ける（accounts.services.filter_staff_querysetのコメント参照）。
        form = GroupSearchForm(request.GET)
        sort_key = request.GET.get("sort")
        sort_dir = request.GET.get("dir", "asc")
        is_admin = get_role(request.user) == PermissionRole.ADMIN
        qs = _group_queryset_with_counts()
        dept_ids = department_scope_ids(request.user)
        qs = scope_queryset_by_department(qs, dept_ids)
        if form.is_valid():
            if is_admin and form.cleaned_data.get("department"):
                qs = qs.filter(department=form.cleaned_data["department"])
            if form.cleaned_data.get("name"):
                qs = qs.filter(name__icontains=form.cleaned_data["name"])
            if form.cleaned_data.get("doc_kbn"):
                qs = qs.filter(doc_kbn=form.cleaned_data["doc_kbn"])
        if sort_key == "department":
            # xlsx B54,58: 部署名ではなく本支所コード→部課コードの複合キーでソート
            # （permissions.services.filter_authority_querysetの"department"特殊扱いと同じ理由）。
            prefix = "-" if sort_dir == "desc" else ""
            qs = qs.order_by(f"{prefix}department__branch_code", f"{prefix}department__section_code", "code")
        else:
            field = GROUP_SORT_FIELDS.get(sort_key)
            if field:
                prefix = "-" if sort_dir == "desc" else ""
                qs = qs.order_by(f"{prefix}{field}", "code")
            else:
                # xlsx B48-53(Rev1.2): 初期ソート順は部課コード(本支所コード+部課コードの5桁)→
                # 分類コード→書類管理区分(文書管理→契約書管理の順)。
                qs = qs.order_by(
                    "department__branch_code", "department__section_code", "code", _DOC_KBN_ORDER
                )
        paginator = Paginator(qs, self.PAGE_SIZE)
        page_obj = paginator.get_page(request.GET.get("page"))
        return render(
            request,
            self.template_name,
            {
                "form": form,
                "page_obj": page_obj,
                "sort_key": sort_key,
                "sort_dir": sort_dir,
                "is_admin_viewer": is_admin,
            },
        )


class GroupRegistView(LoginRequiredMixin, SettingsMenuAccessMixin, View):
    """screen-class-regist。Rev1.2で「部署」プルダウン（管理者のみ表示）が追加された
    （xlsx B116-117）。非管理者が登録する分類は自動的に自部署が設定される
    （フィールド自体をフォームから外し、view側で明示的にセットする。GroupForm docstring参照）。
    """

    template_name = "masters/class_regist.html"
    form_id = "masters_class_regist"
    settings_menu_key = "class_management"

    def get(self, request):
        is_admin = get_role(request.user) == PermissionRole.ADMIN
        form = GroupForm(show_department=is_admin)
        return render(request, self.template_name, {"form": form, "token": issue_token(request.session, self.form_id)})

    def post(self, request):
        submitted_token = request.POST.get("token", "")
        if not consume_token(request.session, self.form_id, submitted_token):
            messages.error(request, "二重に送信された可能性があるため処理を中断しました。もう一度やり直してください。")
            return redirect("masters:class_regist")

        is_admin = get_role(request.user) == PermissionRole.ADMIN
        form = GroupForm(request.POST, show_department=is_admin)
        if not form.is_valid():
            token = issue_token(request.session, self.form_id)
            return render(request, self.template_name, {"form": form, "token": token})
        if not is_admin:
            form.instance.department = request.user.department

        # GroupForm.clean_codeのアプリ層重複チェックは、同一コードでの同時送信という
        # TOCTOU（検証後・保存前の競合）までは防げない。最終的な一意性はmodels.Groupの
        # UniqueConstraint(unique_group_code)がDB側で保証しているため、それに違反した場合の
        # IntegrityErrorをここで捕捉し、生の例外ではなく利用者にわかるメッセージを返す。
        # transaction.atomic()でsave()を囲むのは、IntegrityErrorをtry/exceptで捕捉するだけでは
        # DBコネクションが「ロールバック待ち」状態のまま残り、直後のクエリ（テンプレート内の
        # 関連オブジェクト参照等）がTransactionManagementErrorで失敗するため
        # （atomic()がSAVEPOINTを張り、例外発生時はそこまでロールバックして後続処理を継続可能にする）。
        try:
            with transaction.atomic():
                group = form.save()
        except IntegrityError:
            logger.exception("分類コードの重複によりDB制約違反が発生しました: code=%s", form.cleaned_data.get("code"))
            # class_regist.htmlはmessages機構ではなくform.non_field_errors/form.code.errorsしか
            # 描画しないため、messages.error()ではなくform.add_error()で伝える
            # （clean_codeが検出した場合の重複エラーと同じ見た目・同じ表示場所になる）。
            form.add_error("code", "この分類コードは既に登録されています。")
            token = issue_token(request.session, self.form_id)
            return render(request, self.template_name, {"form": form, "token": token})

        logger.info("分類を新規登録しました: code=%s", group.code)
        # 原本index.html:3220の操作履歴ログサンプル「カテゴリー管理　新規登録」と同種の
        # マスタ登録操作。documents/contractsだけでなくmasters系の登録・更新・削除も記録する。
        audit_services.log(
            employee=request.user,
            action="分類管理 新規登録",
            event_message=f"No.{group.code},分類名：{group.name},書類管理区分：{group.get_doc_kbn_display()}",
        )
        messages.success(request, f"分類「{group.name}」を登録しました。")
        return redirect("masters:class_list")


class GroupEditView(LoginRequiredMixin, SettingsMenuAccessMixin, View):
    """screen-class-edit。Rev1.2で「部署」プルダウン（管理者のみ表示）が追加された。
    非管理者が編集できる対象自体も自部署の分類のみに絞る（xlsx B73-75「非管理者は自部署のみ
    閲覧可」を一覧だけでなく編集アクセスにも適用し、URL直叩きでの他部署分類編集を防ぐ。
    一覧側で既に自部署以外が表示されないため実際には到達しにくいが、
    permissions.services.can_manage_target等と同じ「サーバー側でも強制する」方針を踏襲）。
    """

    template_name = "masters/class_edit.html"
    form_id = "masters_class_edit"
    settings_menu_key = "class_management"

    def _get_object(self, request, pk):
        qs = Group.objects.filter(is_deleted=False)
        dept_ids = department_scope_ids(request.user)
        qs = scope_queryset_by_department(qs, dept_ids)
        return get_object_or_404(qs, pk=pk)

    def get(self, request, pk):
        group = self._get_object(request, pk)
        is_admin = get_role(request.user) == PermissionRole.ADMIN
        form = GroupForm(instance=group, show_department=is_admin)
        return render(
            request, self.template_name, {"form": form, "group": group, "token": issue_token(request.session, self.form_id)}
        )

    def post(self, request, pk):
        group = self._get_object(request, pk)
        submitted_token = request.POST.get("token", "")
        if not consume_token(request.session, self.form_id, submitted_token):
            messages.error(request, "二重に送信された可能性があるため処理を中断しました。もう一度やり直してください。")
            return redirect("masters:class_edit", pk=pk)

        is_admin = get_role(request.user) == PermissionRole.ADMIN
        form = GroupForm(request.POST, instance=group, show_department=is_admin)
        if not form.is_valid():
            token = issue_token(request.session, self.form_id)
            return render(request, self.template_name, {"form": form, "group": group, "token": token})

        # GroupRegistView.postと同じ理由でIntegrityErrorを捕捉する
        # （clean_codeのexclude(pk=...)チェック後・save()前の同時更新レース対策）。
        # atomic()で囲む理由もGroupRegistView.postと同じ（SAVEPOINTで後続処理を継続可能にする）。
        try:
            with transaction.atomic():
                form.save()
        except IntegrityError:
            logger.exception("分類コードの重複によりDB制約違反が発生しました: code=%s", form.cleaned_data.get("code"))
            # class_edit.htmlも同様にform.non_field_errors/form.code.errorsしか描画しないため
            # form.add_error()を使う（GroupRegistView.postと同じ理由）。
            form.add_error("code", "この分類コードは既に登録されています。")
            token = issue_token(request.session, self.form_id)
            return render(request, self.template_name, {"form": form, "group": group, "token": token})

        logger.info("分類を更新しました: code=%s", group.code)
        audit_services.log(
            employee=request.user,
            action="分類管理 更新",
            event_message=f"No.{group.code},分類名：{group.name},書類管理区分：{group.get_doc_kbn_display()}",
        )
        messages.success(request, f"分類「{group.name}」を更新しました。")
        return redirect("masters:class_list")


class GroupDeleteView(LoginRequiredMixin, SettingsMenuAccessMixin, View):
    """screen-class-delete。xlsx B204「分類マスタから論理削除とする」。文書件数0件のときのみ
    削除可（xlsx B68、一覧側でもボタンをdisabled化しているが、URL直叩き対策でサーバー側でも検証）。
    """

    template_name = "masters/class_delete.html"
    form_id = "masters_class_delete"
    settings_menu_key = "class_management"

    def _get_object(self, request, pk):
        # GroupEditView._get_objectと同じ理由（Rev1.2で追加、非管理者は自部署のみ）。
        qs = _group_queryset_with_counts()
        dept_ids = department_scope_ids(request.user)
        qs = scope_queryset_by_department(qs, dept_ids)
        return get_object_or_404(qs, pk=pk)

    def get(self, request, pk):
        group = self._get_object(request, pk)
        return render(
            request, self.template_name, {"group": group, "token": issue_token(request.session, self.form_id)}
        )

    def post(self, request, pk):
        group = self._get_object(request, pk)
        submitted_token = request.POST.get("token", "")
        if not consume_token(request.session, self.form_id, submitted_token):
            messages.error(request, "二重に送信された可能性があるため処理を中断しました。もう一度やり直してください。")
            return redirect("masters:class_delete", pk=pk)

        count = group.doc_count if group.doc_kbn == DocKbn.DOCUMENT else group.contract_count
        if count > 0:
            logger.warning("文書件数が0件でない分類の削除が試行されました: code=%s count=%s", group.code, count)
            messages.error(request, "この分類には紐づくデータが存在するため削除できません。")
            return redirect("masters:class_list")

        group.is_deleted = True
        group.save(update_fields=["is_deleted", "updated_at"])
        logger.info("分類を削除しました: code=%s", group.code)
        audit_services.log(
            employee=request.user, action="分類管理 削除", event_message=f"No.{group.code},分類名：{group.name}"
        )
        messages.success(request, f"分類「{group.name}」を削除しました。")
        return redirect("masters:class_list")


def _category_queryset_with_counts():
    return Category.objects.filter(is_deleted=False).select_related("group", "department").annotate(
        doc_count=Count("documents", distinct=True), contract_count=Count("contracts", distinct=True)
    ).annotate(
        item_count=Case(
            When(doc_kbn=DocKbn.DOCUMENT, then=F("doc_count")),
            default=F("contract_count"),
            output_field=IntegerField(),
        )
    )


# screen-cat-listのソート対象列（xlsx カテゴリー管理!B57-61「下記項目に▲▼ボタンにて昇順/降順
# 切替が可能なようにする」）。"group"（分類コード・分類名の2項目）は特殊扱い
# （下記CategoryListView.get参照）、単体では未使用。
CATEGORY_SORT_FIELDS = {
    "code": "code",
    "group": "group__code",
    "name": "name",
    "count": "item_count",
}


class CategoryListView(LoginRequiredMixin, View):
    """screen-cat-list。1ページ100件目安（Rev1.1で50→100件）。列見出しの▲▼ソート（カテゴリーコード/分類/文書件数）は
    文書検索画面と同じsort_url/sort_arrowの仕組みを使う（2026-08-17、xlsxユーザー指示により追加）。

    xlsxは▲▼ソート対象として「分類コード」「分類名」を別項目として列挙しているが、一覧画面
    （原本HTML・本実装とも）には分類コードを表示する専用列が無く、分類名のみを表示する単一の
    「分類」列しか無い（新しい列を追加すると原本の画面構成から逸脱するため追加しない）。
    そのため、この「分類」列のソートは分類コード→分類名の複合キーとして扱い、xlsxが列挙する
    2つの並び替え基準を1つの列見出しで両立させる（documents/contracts検索の「保存情報」列と
    同様の複合ソートパターン）。

    Rev1.2で「部署」検索プルダウン（管理者のみ表示）と部署単位の閲覧範囲が追加された
    （xlsx B35,B78-80）。GroupListViewと同じ方針（masters.services.department_scope_ids）。
    """

    template_name = "masters/cat_list.html"
    PAGE_SIZE = 100

    def get(self, request):
        # request.GET or Noneは避ける（accounts.services.filter_staff_querysetのコメント参照）。
        form = CategorySearchForm(request.GET)
        sort_key = request.GET.get("sort")
        sort_dir = request.GET.get("dir", "asc")
        is_admin = get_role(request.user) == PermissionRole.ADMIN
        qs = _category_queryset_with_counts()
        dept_ids = department_scope_ids(request.user)
        qs = scope_queryset_by_department(qs, dept_ids)
        if form.is_valid():
            if is_admin and form.cleaned_data.get("department"):
                qs = qs.filter(department=form.cleaned_data["department"])
            if form.cleaned_data.get("name"):
                qs = qs.filter(name__icontains=form.cleaned_data["name"])
            if form.cleaned_data.get("group"):
                qs = qs.filter(group=form.cleaned_data["group"])
            if form.cleaned_data.get("doc_kbn"):
                qs = qs.filter(doc_kbn=form.cleaned_data["doc_kbn"])
        if sort_key == "group":
            prefix = "-" if sort_dir == "desc" else ""
            qs = qs.order_by(f"{prefix}group__code", f"{prefix}group__name", "code")
        elif sort_key == "department":
            # GroupListView.getの"department"特殊扱いと同じ理由（xlsx B62）。
            prefix = "-" if sort_dir == "desc" else ""
            qs = qs.order_by(f"{prefix}department__branch_code", f"{prefix}department__section_code", "code")
        else:
            field = CATEGORY_SORT_FIELDS.get(sort_key)
            if field:
                prefix = "-" if sort_dir == "desc" else ""
                qs = qs.order_by(f"{prefix}{field}", "code")
            else:
                # xlsx B55-59(Rev1.2): 初期ソート順は部課コード(本支所コード+部課コードの5桁)→
                # カテゴリーコード→書類管理区分(文書管理→契約書管理の順)→分類コード。
                qs = qs.order_by(
                    "department__branch_code", "department__section_code", "code", _DOC_KBN_ORDER, "group__code"
                )
        paginator = Paginator(qs, self.PAGE_SIZE)
        page_obj = paginator.get_page(request.GET.get("page"))
        return render(
            request,
            self.template_name,
            {
                "form": form,
                "page_obj": page_obj,
                "sort_key": sort_key,
                "sort_dir": sort_dir,
                "is_admin_viewer": is_admin,
            },
        )


class CategoryRegistView(LoginRequiredMixin, View):
    """screen-cat-regist。Rev1.2で「部署」プルダウン（管理者のみ表示）が追加された
    （xlsx B109-110）。GroupRegistViewと同じ方針（非管理者が登録するカテゴリーは自動的に
    自部署が設定される）。
    """

    template_name = "masters/cat_regist.html"
    form_id = "masters_cat_regist"

    def get(self, request):
        is_admin = get_role(request.user) == PermissionRole.ADMIN
        form = CategoryForm(show_department=is_admin)
        return render(request, self.template_name, {"form": form, "token": issue_token(request.session, self.form_id)})

    def post(self, request):
        submitted_token = request.POST.get("token", "")
        if not consume_token(request.session, self.form_id, submitted_token):
            messages.error(request, "二重に送信された可能性があるため処理を中断しました。もう一度やり直してください。")
            return redirect("masters:cat_regist")

        is_admin = get_role(request.user) == PermissionRole.ADMIN
        form = CategoryForm(request.POST, show_department=is_admin)
        if not form.is_valid():
            token = issue_token(request.session, self.form_id)
            return render(request, self.template_name, {"form": form, "token": token})
        if not is_admin:
            form.instance.department = request.user.department

        # CategoryForm.clean_codeと同じくアプリ層チェックのみではTOCTOU競合を防げないため、
        # models.CategoryのUniqueConstraint(unique_category_code)違反時のIntegrityErrorを捕捉する
        # （GroupRegistViewと同じ方針。atomic()で囲む理由も同じ）。
        try:
            with transaction.atomic():
                category = form.save()
        except IntegrityError:
            logger.exception(
                "カテゴリーコードの重複によりDB制約違反が発生しました: code=%s", form.cleaned_data.get("code")
            )
            # cat_regist.htmlもmessages機構を描画しないため、GroupRegistView.postと同じ理由で
            # form.add_error()を使う。
            form.add_error("code", "このカテゴリーコードは既に登録されています。")
            token = issue_token(request.session, self.form_id)
            return render(request, self.template_name, {"form": form, "token": token})

        logger.info("カテゴリーを新規登録しました: code=%s", category.code)
        audit_services.log(
            employee=request.user,
            action="カテゴリー管理 新規登録",
            event_message=(
                f"No.{category.code},カテゴリー名：{category.name},"
                f"書類管理区分：{category.get_doc_kbn_display()},分類：{category.group.name}"
            ),
        )
        messages.success(request, f"カテゴリー「{category.name}」を登録しました。")
        return redirect("masters:cat_list")


class CategoryEditView(LoginRequiredMixin, View):
    """screen-cat-edit。GroupEditViewと同じ方針（Rev1.2で「部署」プルダウンが追加され、
    非管理者の編集対象・可視範囲を自部署のみに絞る）。"""

    template_name = "masters/cat_edit.html"
    form_id = "masters_cat_edit"

    def _get_object(self, request, pk):
        qs = Category.objects.filter(is_deleted=False)
        dept_ids = department_scope_ids(request.user)
        qs = scope_queryset_by_department(qs, dept_ids)
        return get_object_or_404(qs, pk=pk)

    def get(self, request, pk):
        category = self._get_object(request, pk)
        is_admin = get_role(request.user) == PermissionRole.ADMIN
        form = CategoryForm(instance=category, show_department=is_admin)
        return render(
            request,
            self.template_name,
            {"form": form, "category": category, "token": issue_token(request.session, self.form_id)},
        )

    def post(self, request, pk):
        category = self._get_object(request, pk)
        submitted_token = request.POST.get("token", "")
        if not consume_token(request.session, self.form_id, submitted_token):
            messages.error(request, "二重に送信された可能性があるため処理を中断しました。もう一度やり直してください。")
            return redirect("masters:cat_edit", pk=pk)

        is_admin = get_role(request.user) == PermissionRole.ADMIN
        form = CategoryForm(request.POST, instance=category, show_department=is_admin)
        if not form.is_valid():
            token = issue_token(request.session, self.form_id)
            return render(request, self.template_name, {"form": form, "category": category, "token": token})

        # CategoryRegistView.postと同じ理由でIntegrityErrorを捕捉する（atomic()で囲む理由も同じ）。
        try:
            with transaction.atomic():
                form.save()
        except IntegrityError:
            logger.exception(
                "カテゴリーコードの重複によりDB制約違反が発生しました: code=%s", form.cleaned_data.get("code")
            )
            # cat_edit.htmlも同様の理由でform.add_error()を使う。
            form.add_error("code", "このカテゴリーコードは既に登録されています。")
            token = issue_token(request.session, self.form_id)
            return render(request, self.template_name, {"form": form, "category": category, "token": token})

        logger.info("カテゴリーを更新しました: code=%s", category.code)
        audit_services.log(
            employee=request.user,
            action="カテゴリー管理 更新",
            event_message=(
                f"No.{category.code},カテゴリー名：{category.name},"
                f"書類管理区分：{category.get_doc_kbn_display()},分類：{category.group.name}"
            ),
        )
        messages.success(request, f"カテゴリー「{category.name}」を更新しました。")
        return redirect("masters:cat_list")


class CategoryDeleteView(LoginRequiredMixin, View):
    """screen-cat-delete。xlsx B196「カテゴリーマスタから論理削除とする」。
    GroupDeleteViewと同じ方針（Rev1.2で非管理者は自部署のカテゴリーのみ削除可）。
    """

    template_name = "masters/cat_delete.html"
    form_id = "masters_cat_delete"

    def _get_object(self, request, pk):
        qs = _category_queryset_with_counts()
        dept_ids = department_scope_ids(request.user)
        qs = scope_queryset_by_department(qs, dept_ids)
        return get_object_or_404(qs, pk=pk)

    def get(self, request, pk):
        category = self._get_object(request, pk)
        return render(
            request, self.template_name, {"category": category, "token": issue_token(request.session, self.form_id)}
        )

    def post(self, request, pk):
        category = self._get_object(request, pk)
        submitted_token = request.POST.get("token", "")
        if not consume_token(request.session, self.form_id, submitted_token):
            messages.error(request, "二重に送信された可能性があるため処理を中断しました。もう一度やり直してください。")
            return redirect("masters:cat_delete", pk=pk)

        count = category.doc_count if category.doc_kbn == DocKbn.DOCUMENT else category.contract_count
        if count > 0:
            logger.warning(
                "文書件数が0件でないカテゴリーの削除が試行されました: code=%s count=%s", category.code, count
            )
            messages.error(request, "このカテゴリーには紐づくデータが存在するため削除できません。")
            return redirect("masters:cat_list")

        category.is_deleted = True
        category.save(update_fields=["is_deleted", "updated_at"])
        logger.info("カテゴリーを削除しました: code=%s", category.code)
        audit_services.log(
            employee=request.user,
            action="カテゴリー管理 削除",
            event_message=f"No.{category.code},カテゴリー名：{category.name}",
        )
        messages.success(request, f"カテゴリー「{category.name}」を削除しました。")
        return redirect("masters:cat_list")


def _retention_list_url(kbn, doc_name=""):
    """一覧画面(retention_list.html)の区分(kbn)・書類名(doc_name)選択状態を維持したまま
    戻るためのURL。原本はSPAでDOMを破棄しないため区分選択がJS変数として残るが、本実装は
    実際に別画面へ遷移するため、登録/編集/削除の完了・キャンセルで一覧に戻る際は選択状態を
    クエリパラメータで引き継ぎ、サーバー側で選択中のラジオボタンとして描画し直す
    （ユーザー指摘：編集画面から戻ると選択が原本と異なり解除されてしまう不具合の修正）。
    """
    return f"{reverse('masters:retention_list')}?{urlencode({'kbn': kbn, 'doc_name': doc_name})}"


class RetentionListView(LoginRequiredMixin, SettingsMenuAccessMixin, View):
    """screen-retention-doc。原本は文書用/電子決裁(稟議書)/電子決裁(経費支出伺)の3tbodyを
    すべて事前描画しラジオ・プルダウンでJS表示切替する構成のため、同じ方式（3種類とも
    サーバー側で取得してテンプレートに渡し、クライアント側で表示切替）を踏襲する。
    """

    template_name = "masters/retention_list.html"
    settings_menu_key = "retention_setting"

    def get(self, request):
        selected_kbn = request.GET.get("kbn", RetentionKbn.DOCUMENT)
        if selected_kbn not in RetentionKbn.values:
            selected_kbn = RetentionKbn.DOCUMENT
        selected_doc_name = request.GET.get("doc_name", EapprovalDocName.RINGISHO)
        if selected_doc_name not in EapprovalDocName.values:
            selected_doc_name = EapprovalDocName.RINGISHO
        context = {
            "doc_periods": RetentionPeriod.objects.filter(
                kbn=RetentionKbn.DOCUMENT, is_deleted=False
            ).order_by("display_order"),
            "ringisho_periods": RetentionPeriod.objects.filter(
                kbn=RetentionKbn.EAPPROVAL, doc_name=EapprovalDocName.RINGISHO, is_deleted=False
            ).order_by("display_order"),
            "keihi_periods": RetentionPeriod.objects.filter(
                kbn=RetentionKbn.EAPPROVAL, doc_name=EapprovalDocName.KEIHI, is_deleted=False
            ).order_by("display_order"),
            "selected_kbn": selected_kbn,
            "selected_doc_name": selected_doc_name,
        }
        return render(request, self.template_name, context)


class RetentionRegistView(LoginRequiredMixin, SettingsMenuAccessMixin, View):
    """screen-retention-regist-doc。原本はタイトル・書類名欄をJSで書き換える1画面共用構成だが、
    区分(kbn)・書類名(doc_name)は一覧側の現在の選択状態からクエリパラメータで引き継ぎ、
    サーバー側で直接正しい表示に出し分ける（JSでの後書き換えより確実なため）。
    """

    settings_menu_key = "retention_setting"

    template_name = "masters/retention_regist.html"
    form_id = "masters_retention_regist"

    def _initial(self, request):
        kbn = request.GET.get("kbn", RetentionKbn.DOCUMENT)
        doc_name = request.GET.get("doc_name", "") if kbn == RetentionKbn.EAPPROVAL else ""
        return {"kbn": kbn, "doc_name": doc_name}

    def get(self, request):
        form = RetentionPeriodForm(initial=self._initial(request))
        return render(request, self.template_name, {"form": form, "token": issue_token(request.session, self.form_id)})

    def post(self, request):
        submitted_token = request.POST.get("token", "")
        if not consume_token(request.session, self.form_id, submitted_token):
            messages.error(request, "二重に送信された可能性があるため処理を中断しました。もう一度やり直してください。")
            initial = self._initial(request)
            return redirect(_retention_list_url(initial["kbn"], initial["doc_name"]))

        form = RetentionPeriodForm(request.POST)
        if not form.is_valid():
            token = issue_token(request.session, self.form_id)
            return render(request, self.template_name, {"form": form, "token": token})

        # RetentionPeriodForm.clean_display_orderのアプリ層チェックも同時送信のTOCTOU競合までは
        # 防げないため、models.RetentionPeriodのUniqueConstraint(unique_retention_display_order)
        # 違反時のIntegrityErrorを捕捉する（Group/Category系のform.save()と同じ方針。
        # atomic()で囲む理由も同じ）。
        try:
            with transaction.atomic():
                period = form.save()
        except IntegrityError:
            logger.exception(
                "保存期間設定の表示順の重複によりDB制約違反が発生しました: kbn=%s doc_name=%s display_order=%s",
                form.cleaned_data.get("kbn"),
                form.cleaned_data.get("doc_name"),
                form.cleaned_data.get("display_order"),
            )
            # retention_regist.htmlもmessages機構ではなくform.display_order.errors等しか
            # 描画しないため、GroupRegistView.postと同じ理由でform.add_error()を使う。
            form.add_error("display_order", "この表示順は既に使用されています。")
            token = issue_token(request.session, self.form_id)
            return render(request, self.template_name, {"form": form, "token": token})

        logger.info("保存期間設定を新規登録しました: id=%s %s", period.pk, period)
        audit_services.log(
            employee=request.user,
            action="保存期間設定 新規登録",
            event_message=f"区分：{period.get_kbn_display()},保存期間：{period}",
        )
        messages.success(request, "保存期間設定を登録しました。")
        return redirect(_retention_list_url(period.kbn, period.doc_name))


class RetentionEditView(LoginRequiredMixin, SettingsMenuAccessMixin, View):
    template_name = "masters/retention_edit.html"
    form_id = "masters_retention_edit"
    settings_menu_key = "retention_setting"

    def get(self, request, pk):
        period = get_object_or_404(RetentionPeriod, pk=pk, is_deleted=False)
        form = RetentionPeriodForm(instance=period)
        return render(
            request, self.template_name, {"form": form, "period": period, "token": issue_token(request.session, self.form_id)}
        )

    def post(self, request, pk):
        period = get_object_or_404(RetentionPeriod, pk=pk, is_deleted=False)
        submitted_token = request.POST.get("token", "")
        if not consume_token(request.session, self.form_id, submitted_token):
            messages.error(request, "二重に送信された可能性があるため処理を中断しました。もう一度やり直してください。")
            return redirect("masters:retention_edit", pk=pk)

        form = RetentionPeriodForm(request.POST, instance=period)
        if not form.is_valid():
            token = issue_token(request.session, self.form_id)
            return render(request, self.template_name, {"form": form, "period": period, "token": token})

        # RetentionRegistView.postと同じ理由でIntegrityErrorを捕捉する（atomic()で囲む理由も同じ）。
        try:
            with transaction.atomic():
                form.save()
        except IntegrityError:
            logger.exception(
                "保存期間設定の表示順の重複によりDB制約違反が発生しました: kbn=%s doc_name=%s display_order=%s",
                form.cleaned_data.get("kbn"),
                form.cleaned_data.get("doc_name"),
                form.cleaned_data.get("display_order"),
            )
            # retention_edit.htmlも同様の理由でform.add_error()を使う。
            form.add_error("display_order", "この表示順は既に使用されています。")
            token = issue_token(request.session, self.form_id)
            return render(request, self.template_name, {"form": form, "period": period, "token": token})

        logger.info("保存期間設定を更新しました: id=%s %s", period.pk, period)
        audit_services.log(
            employee=request.user,
            action="保存期間設定 更新",
            event_message=f"区分：{period.get_kbn_display()},保存期間：{period}",
        )
        messages.success(request, "保存期間設定を更新しました。")
        return redirect(_retention_list_url(period.kbn, period.doc_name))


class RetentionDeleteView(LoginRequiredMixin, SettingsMenuAccessMixin, View):
    """screen-retention-delete。xlsx B146/B271「保存期間マスタから論理削除とする」通り、
    Group/Categoryと同じ論理削除（is_deleted=True）にする。行自体は消さないため、既存の
    文書・契約書がretention_period外部キー(on_delete=PROTECT)で参照していても削除できる。
    """

    template_name = "masters/retention_delete.html"
    form_id = "masters_retention_delete"
    settings_menu_key = "retention_setting"

    def get(self, request, pk):
        period = get_object_or_404(RetentionPeriod, pk=pk, is_deleted=False)
        # 「No.」は一覧画面(retention_list.html)と同じ「同一区分内での表示順に基づく行位置」で
        # 表示する。display_orderをそのまま「No.」に流用すると、欠番がある場合に一覧の行位置と
        # 食い違うため、同一kbn/doc_name内での順位を都度計算する。
        no = RetentionPeriod.objects.filter(
            kbn=period.kbn, doc_name=period.doc_name, display_order__lte=period.display_order, is_deleted=False
        ).count()
        return render(
            request,
            self.template_name,
            {"period": period, "no": no, "token": issue_token(request.session, self.form_id)},
        )

    def post(self, request, pk):
        period = get_object_or_404(RetentionPeriod, pk=pk, is_deleted=False)
        submitted_token = request.POST.get("token", "")
        if not consume_token(request.session, self.form_id, submitted_token):
            messages.error(request, "二重に送信された可能性があるため処理を中断しました。もう一度やり直してください。")
            return redirect("masters:retention_delete", pk=pk)

        period.is_deleted = True
        period.save(update_fields=["is_deleted"])
        logger.info("保存期間設定を削除しました: id=%s", pk)
        audit_services.log(
            employee=request.user,
            action="保存期間設定 削除",
            event_message=f"区分：{period.get_kbn_display()},保存期間：{period}",
        )
        messages.success(request, "保存期間設定を削除しました。")
        return redirect(_retention_list_url(period.kbn, period.doc_name))
