import logging

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Case, Count, F, IntegerField, When
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import urlencode
from django.views import View

from audit import services as audit_services
from core import master_views
from core.double_submit import issue_token, reject_if_resubmitted
from core.form_services import save_or_none
from masters.forms import CategoryForm, CategorySearchForm, GroupForm, GroupSearchForm, RetentionPeriodForm
from masters.models import Category, DocKbn, EapprovalDocName, Group, RetentionKbn, RetentionPeriod
from masters.services import department_scope_ids, scope_queryset_by_department, scoped_get_object_or_404
from permissions.mixins import SettingsMenuAccessMixin

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
# （xlsx B58「部署　※部署名ではなく、部課コードで昇順/降順」）、BaseScopedMasterListViewで
# 複合ソートとして特殊扱いする（AUTHORITY_SORT_FIELDSのdepartment扱いと同じパターン）。
GROUP_SORT_FIELDS = {
    "code": "code",
    "name": "name",
    "count": "item_count",
}


class GroupListView(LoginRequiredMixin, SettingsMenuAccessMixin, master_views.BaseScopedMasterListView):
    """screen-class-list。1ページ100件目安（xlsx B62、Rev1.1で50→100件）。列見出しの▲▼ソート
    （分類コード/分類名/文書件数）は、文書検索画面と同じsort_url/sort_arrowの仕組みを使う
    （2026-08-17、xlsxユーザー指示により追加）。

    Rev1.2で「部署」検索プルダウン（管理者のみ表示）と部署単位の閲覧範囲が追加された
    （xlsx B35,B73-75）。管理者は全部署、それ以外は自部署のみを閲覧できる
    （masters.services.department_scope_ids）。一覧の「部署」列も非管理者には表示しない
    （xlsx B75「一覧の「部署」を非表示」）。

    Group/Category一覧・登録・編集・削除の4画面がモデル名以外ほぼ完全に同一ロジックで
    コピペ実装されていたため、共通実装はcore.master_views.BaseScopedMasterListViewへ集約した
    （documents/contracts側のcore.record_views.BaseDeleteView等と同じ横展開。品質レビューで
    発見、2026-08-25修正）。
    """

    template_name = "masters/class_list.html"
    settings_menu_key = "class_management"
    sort_fields = GROUP_SORT_FIELDS
    dept_scope_resolver = staticmethod(department_scope_ids)
    scope_queryset = staticmethod(scope_queryset_by_department)

    def base_queryset(self):
        return _group_queryset_with_counts()

    def build_search_form(self, request):
        # request.GET or Noneは避ける（accounts.services.filter_staff_querysetのコメント参照）。
        return GroupSearchForm(request.GET)

    def apply_search_filters(self, qs, form, is_admin):
        if is_admin and form.cleaned_data.get("department"):
            qs = qs.filter(department=form.cleaned_data["department"])
        if form.cleaned_data.get("name"):
            qs = qs.filter(name__icontains=form.cleaned_data["name"])
        if form.cleaned_data.get("doc_kbn"):
            qs = qs.filter(doc_kbn=form.cleaned_data["doc_kbn"])
        return qs

    def default_order_by(self, qs):
        # xlsx B48-53(Rev1.2): 初期ソート順は部課コード(本支所コード+部課コードの5桁)→
        # 分類コード→書類管理区分(文書管理→契約書管理の順)。
        return qs.order_by("department__branch_code", "department__section_code", "code", _DOC_KBN_ORDER)


class GroupRegistView(LoginRequiredMixin, SettingsMenuAccessMixin, master_views.BaseScopedMasterRegistView):
    """screen-class-regist。Rev1.2で「部署」プルダウン（管理者のみ表示）が追加された
    （xlsx B116-117）。非管理者が登録する分類は自動的に自部署が設定される
    （フィールド自体をフォームから外し、view側で明示的にセットする。GroupForm docstring参照）。

    共通実装はcore.master_views.BaseScopedMasterRegistView参照（GroupListView docstring参照）。
    """

    template_name = "masters/class_regist.html"
    form_class = GroupForm
    form_id = "masters_class_regist"
    settings_menu_key = "class_management"
    own_url_name = "masters:class_regist"
    list_url_name = "masters:class_list"
    unique_error_message = "この分類コードは既に登録されています。"
    audit_action = "分類管理　新規登録"
    entity_label = "分類"

    def audit_event_message(self, obj):
        # 原本index.html:3220の操作履歴ログサンプル「カテゴリー管理　新規登録」と同種の
        # マスタ登録操作。documents/contractsだけでなくmasters系の登録・更新・削除も記録する。
        return (
            f"No.{obj.code},分類名：{obj.name},書類管理区分：{obj.get_doc_kbn_display()},"
            f"部署：{obj.department}"
        )

    def success_message(self, obj):
        return f"分類「{obj.name}」を登録しました。"

    def log_message(self):
        return "分類コードの重複によりDB制約違反が発生しました: code=%s"


class GroupEditView(LoginRequiredMixin, SettingsMenuAccessMixin, master_views.BaseScopedMasterEditView):
    """screen-class-edit。Rev1.2で「部署」プルダウン（管理者のみ表示）が追加された。
    非管理者が編集できる対象自体も自部署の分類のみに絞る（xlsx B73-75「非管理者は自部署のみ
    閲覧可」を一覧だけでなく編集アクセスにも適用し、URL直叩きでの他部署分類編集を防ぐ。
    一覧側で既に自部署以外が表示されないため実際には到達しにくいが、
    permissions.services.can_manage_target等と同じ「サーバー側でも強制する」方針を踏襲）。

    共通実装はcore.master_views.BaseScopedMasterEditView参照（GroupListView docstring参照）。
    """

    template_name = "masters/class_edit.html"
    form_class = GroupForm
    form_id = "masters_class_edit"
    settings_menu_key = "class_management"
    context_object_name = "group"
    own_url_name = "masters:class_edit"
    list_url_name = "masters:class_list"
    unique_error_message = "この分類コードは既に登録されています。"
    audit_action = "分類管理　更新"
    entity_label = "分類"

    def scoped_lookup(self, request, pk):
        return scoped_get_object_or_404(Group.objects.filter(is_deleted=False), request.user, pk)

    def audit_event_message(self, obj, before):
        # xlsx 操作履歴ログ!B69-70＜職員マスタ更新　例＞と同じ「更新した項目名：更新前データ ->
        # 更新後データ」形式（原本フィデリティ監査で発見：以前は更新後の値のスナップショットのみで
        # 何がどう変わったか記録していなかった）。
        changes = []
        if obj.code != before.code:
            changes.append(("分類コード", before.code, obj.code))
        if obj.name != before.name:
            changes.append(("分類名", before.name, obj.name))
        if obj.doc_kbn != before.doc_kbn:
            changes.append(("書類管理区分", before.get_doc_kbn_display(), obj.get_doc_kbn_display()))
        if obj.department_id != before.department_id:
            changes.append(("部署", before.department, obj.department))
        return audit_services.build_diff_message(f"No.{obj.code},分類名：{obj.name}", changes)

    def success_message(self, obj):
        return f"分類「{obj.name}」を更新しました。"

    def log_message(self):
        return "分類コードの重複によりDB制約違反が発生しました: code=%s"


class GroupDeleteView(LoginRequiredMixin, SettingsMenuAccessMixin, master_views.BaseScopedMasterDeleteView):
    """screen-class-delete。xlsx B204「分類マスタから論理削除とする」。文書件数0件のときのみ
    削除可（xlsx B68、一覧側でもボタンをdisabled化しているが、URL直叩き対策でサーバー側でも検証）。

    共通実装はcore.master_views.BaseScopedMasterDeleteView参照（GroupListView docstring参照）。
    """

    template_name = "masters/class_delete.html"
    form_id = "masters_class_delete"
    settings_menu_key = "class_management"
    context_object_name = "group"
    own_url_name = "masters:class_delete"
    list_url_name = "masters:class_list"
    audit_action = "分類管理　削除"
    entity_label = "分類"

    def scoped_lookup(self, request, pk):
        # GroupEditView.scoped_lookupと同じ理由（Rev1.2で追加、非管理者は自部署のみ）。
        return scoped_get_object_or_404(_group_queryset_with_counts(), request.user, pk)

    def blocking_count(self, obj):
        return obj.doc_count if obj.doc_kbn == DocKbn.DOCUMENT else obj.contract_count


def _category_queryset_with_counts():
    """一覧の「文書件数」列。_group_queryset_with_countsと同じ理由（doc_kbnに応じて
    doc_count/contract_countのどちらを使うかをitem_countにまとめる）。
    """
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
# （下記CategoryListView.apply_special_sort参照）、単体では未使用。
CATEGORY_SORT_FIELDS = {
    "code": "code",
    "group": "group__code",
    "name": "name",
    "count": "item_count",
}


class CategoryListView(LoginRequiredMixin, SettingsMenuAccessMixin, master_views.BaseScopedMasterListView):
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

    共通実装はcore.master_views.BaseScopedMasterListView参照（GroupListView docstring参照）。
    """

    template_name = "masters/cat_list.html"
    settings_menu_key = "category_management"
    sort_fields = CATEGORY_SORT_FIELDS
    dept_scope_resolver = staticmethod(department_scope_ids)
    scope_queryset = staticmethod(scope_queryset_by_department)

    def base_queryset(self):
        return _category_queryset_with_counts()

    def build_search_form(self, request):
        return CategorySearchForm(request.GET, employee=request.user)

    def apply_search_filters(self, qs, form, is_admin):
        if is_admin and form.cleaned_data.get("department"):
            qs = qs.filter(department=form.cleaned_data["department"])
        if form.cleaned_data.get("name"):
            qs = qs.filter(name__icontains=form.cleaned_data["name"])
        if form.cleaned_data.get("group"):
            qs = qs.filter(group=form.cleaned_data["group"])
        if form.cleaned_data.get("doc_kbn"):
            qs = qs.filter(doc_kbn=form.cleaned_data["doc_kbn"])
        return qs

    def apply_special_sort(self, qs, sort_key, sort_dir):
        if sort_key != "group":
            return None
        prefix = "-" if sort_dir == "desc" else ""
        return qs.order_by(f"{prefix}group__code", f"{prefix}group__name", "code")

    def default_order_by(self, qs):
        # xlsx B55-59(Rev1.2): 初期ソート順は部課コード(本支所コード+部課コードの5桁)→
        # カテゴリーコード→書類管理区分(文書管理→契約書管理の順)→分類コード。
        return qs.order_by(
            "department__branch_code", "department__section_code", "code", _DOC_KBN_ORDER, "group__code"
        )


class CategoryRegistView(LoginRequiredMixin, SettingsMenuAccessMixin, master_views.BaseScopedMasterRegistView):
    """screen-cat-regist。Rev1.2で「部署」プルダウン（管理者のみ表示）が追加された
    （xlsx B109-110）。GroupRegistViewと同じ方針（非管理者が登録するカテゴリーは自動的に
    自部署が設定される）。

    共通実装はcore.master_views.BaseScopedMasterRegistView参照（GroupListView docstring参照）。
    """

    template_name = "masters/cat_regist.html"
    form_class = CategoryForm
    form_id = "masters_cat_regist"
    settings_menu_key = "category_management"
    own_url_name = "masters:cat_regist"
    list_url_name = "masters:cat_list"
    unique_error_message = "このカテゴリーコードは既に登録されています。"
    audit_action = "カテゴリー管理　新規登録"
    entity_label = "カテゴリー"

    def extra_form_kwargs(self, request, is_admin):
        return {"employee": request.user}

    def audit_event_message(self, obj):
        return (
            f"No.{obj.code},カテゴリー名：{obj.name},"
            f"書類管理区分：{obj.get_doc_kbn_display()},分類：{obj.group.name},"
            f"部署：{obj.department}"
        )

    def success_message(self, obj):
        return f"カテゴリー「{obj.name}」を登録しました。"

    def log_message(self):
        return "カテゴリーコードの重複によりDB制約違反が発生しました: code=%s"


class CategoryEditView(LoginRequiredMixin, SettingsMenuAccessMixin, master_views.BaseScopedMasterEditView):
    """screen-cat-edit。GroupEditViewと同じ方針（Rev1.2で「部署」プルダウンが追加され、
    非管理者の編集対象・可視範囲を自部署のみに絞る）。

    共通実装はcore.master_views.BaseScopedMasterEditView参照（GroupListView docstring参照）。
    """

    template_name = "masters/cat_edit.html"
    form_class = CategoryForm
    form_id = "masters_cat_edit"
    settings_menu_key = "category_management"
    context_object_name = "category"
    own_url_name = "masters:cat_edit"
    list_url_name = "masters:cat_list"
    unique_error_message = "このカテゴリーコードは既に登録されています。"
    audit_action = "カテゴリー管理　更新"
    entity_label = "カテゴリー"

    def scoped_lookup(self, request, pk):
        return scoped_get_object_or_404(Category.objects.filter(is_deleted=False), request.user, pk)

    def extra_form_kwargs(self, request, is_admin):
        return {"employee": request.user}

    def audit_event_message(self, obj, before):
        # GroupEditView.audit_event_messageと同じ理由・同じ形式。
        changes = []
        if obj.code != before.code:
            changes.append(("カテゴリーコード", before.code, obj.code))
        if obj.name != before.name:
            changes.append(("カテゴリー名", before.name, obj.name))
        if obj.doc_kbn != before.doc_kbn:
            changes.append(("書類管理区分", before.get_doc_kbn_display(), obj.get_doc_kbn_display()))
        if obj.group_id != before.group_id:
            changes.append(("分類", before.group, obj.group))
        if obj.department_id != before.department_id:
            changes.append(("部署", before.department, obj.department))
        return audit_services.build_diff_message(f"No.{obj.code},カテゴリー名：{obj.name}", changes)

    def success_message(self, obj):
        return f"カテゴリー「{obj.name}」を更新しました。"

    def log_message(self):
        return "カテゴリーコードの重複によりDB制約違反が発生しました: code=%s"


class CategoryDeleteView(LoginRequiredMixin, SettingsMenuAccessMixin, master_views.BaseScopedMasterDeleteView):
    """screen-cat-delete。xlsx B196「カテゴリーマスタから論理削除とする」。
    GroupDeleteViewと同じ方針（Rev1.2で非管理者は自部署のカテゴリーのみ削除可）。

    共通実装はcore.master_views.BaseScopedMasterDeleteView参照（GroupListView docstring参照）。
    """

    template_name = "masters/cat_delete.html"
    form_id = "masters_cat_delete"
    settings_menu_key = "category_management"
    context_object_name = "category"
    own_url_name = "masters:cat_delete"
    list_url_name = "masters:cat_list"
    audit_action = "カテゴリー管理　削除"
    entity_label = "カテゴリー"

    def scoped_lookup(self, request, pk):
        return scoped_get_object_or_404(_category_queryset_with_counts(), request.user, pk)

    def blocking_count(self, obj):
        return obj.doc_count if obj.doc_kbn == DocKbn.DOCUMENT else obj.contract_count


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
        initial = self._initial(request)
        resp = reject_if_resubmitted(
            request, self.form_id, _retention_list_url(initial["kbn"], initial["doc_name"])
        )
        if resp is not None:
            return resp

        form = RetentionPeriodForm(request.POST)
        if not form.is_valid():
            token = issue_token(request.session, self.form_id)
            return render(request, self.template_name, {"form": form, "token": token})

        # RetentionPeriodForm側のアプリ層チェック（clean_display_order/clean）も同時送信の
        # TOCTOU競合までは防げないため、models.RetentionPeriodのUniqueConstraint
        # （unique_retention_display_order/period_value/permanent）違反時のIntegrityErrorを
        # save_or_noneで捕捉する（Group/Category系のform.save()と同じ方針）。
        period = save_or_none(
            form,
            log_message="保存期間設定の重複によりDB制約違反が発生しました: kbn=%s doc_name=%s period=%s%s display_order=%s",
            log_args=(
                form.cleaned_data.get("kbn"), form.cleaned_data.get("doc_name"),
                form.cleaned_data.get("period_value"), form.cleaned_data.get("period_unit"),
                form.cleaned_data.get("display_order"),
            ),
        )
        if period is None:
            # retention_regist.htmlはmessages機構ではなくform.non_field_errors/period_value/
            # display_orderのerrorsしか描画しないため、GroupRegistView.postと同じ理由で
            # form.add_error()を使う。どちらの一意制約に触れたかはここでは判別しないため非フィールド
            # エラーにまとめる。
            form.add_error(None, "保存期間または表示順が他の設定と重複しています。")
            token = issue_token(request.session, self.form_id)
            return render(request, self.template_name, {"form": form, "token": token})

        logger.info("保存期間設定を新規登録しました: id=%s %s", period.pk, period)
        audit_services.log(
            employee=request.user,
            action="保存期間設定　新規登録",
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
        resp = reject_if_resubmitted(request, self.form_id, "masters:retention_edit", pk=pk)
        if resp is not None:
            return resp

        # GroupEditView/CategoryEditViewと同じ理由（core.master_views.BaseScopedMasterEditView.post
        # docstring参照）。RetentionPeriodはBaseScopedMasterEditViewを使わない独自実装のため、
        # ここでも同様にフォーム上書き前の値をスナップショットする。__str__(period_value+
        # period_unitの組み合わせ)を「保存期間」欄の比較に使う。
        before_str = str(period)
        before_display_order = period.display_order

        form = RetentionPeriodForm(request.POST, instance=period)
        if not form.is_valid():
            token = issue_token(request.session, self.form_id)
            return render(request, self.template_name, {"form": form, "period": period, "token": token})

        # RetentionRegistView.postと同じ理由でIntegrityErrorをsave_or_noneで捕捉する。
        if save_or_none(
            form,
            log_message="保存期間設定の重複によりDB制約違反が発生しました: kbn=%s doc_name=%s period=%s%s display_order=%s",
            log_args=(
                form.cleaned_data.get("kbn"), form.cleaned_data.get("doc_name"),
                form.cleaned_data.get("period_value"), form.cleaned_data.get("period_unit"),
                form.cleaned_data.get("display_order"),
            ),
        ) is None:
            # retention_edit.htmlも同様の理由でform.add_error()を使う（RetentionRegistView参照）。
            form.add_error(None, "保存期間または表示順が他の設定と重複しています。")
            token = issue_token(request.session, self.form_id)
            return render(request, self.template_name, {"form": form, "period": period, "token": token})

        logger.info("保存期間設定を更新しました: id=%s %s", period.pk, period)
        # xlsx 操作履歴ログ!B69-70＜職員マスタ更新　例＞と同じ「更新した項目名：更新前データ ->
        # 更新後データ」形式（原本フィデリティ監査で発見：以前は更新後の値のスナップショットのみ）。
        changes = []
        if str(period) != before_str:
            changes.append(("保存期間", before_str, str(period)))
        if period.display_order != before_display_order:
            changes.append(("表示順", before_display_order, period.display_order))
        audit_services.log(
            employee=request.user,
            action="保存期間設定　更新",
            event_message=audit_services.build_diff_message(
                f"区分：{period.get_kbn_display()},保存期間名：{period.doc_name}", changes
            ),
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
        resp = reject_if_resubmitted(request, self.form_id, "masters:retention_delete", pk=pk)
        if resp is not None:
            return resp

        period.is_deleted = True
        # updated_atも更新する（auto_now=Trueはupdate_fieldsに明示しないと発火しない。
        # Group/CategoryのBaseScopedMasterDeleteViewと挙動を揃える。review_pending.txt No.24）。
        period.save(update_fields=["is_deleted", "updated_at"])
        logger.info("保存期間設定を削除しました: id=%s", pk)
        audit_services.log(
            employee=request.user,
            action="保存期間設定　削除",
            event_message=f"区分：{period.get_kbn_display()},保存期間：{period}",
        )
        messages.success(request, "保存期間設定を削除しました。")
        return redirect(_retention_list_url(period.kbn, period.doc_name))
