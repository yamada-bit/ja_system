import copy
import logging

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import Error as DBError
from django.shortcuts import redirect, render
from django.views import View

from audit import services as audit_services
from core.double_submit import issue_token, reject_if_resubmitted
from core.form_services import save_or_none
from organizations.services import department_composite_order_by
from permissions.services import is_admin as _is_admin

logger = logging.getLogger(__name__)


class BaseScopedMasterListView(View):
    """部署スコープ・書類管理区分(doc_kbn)を持つマスタ一覧画面（masters.Group/Category）の
    共通実装。一覧・登録・編集・削除の4画面がモデル名以外ほぼ完全に同一ロジックで
    コピペ実装されていたため、documents/contracts側で確立済みのパラメータ化基底クラス方針
    （core.record_views.BaseDeleteView等）を横展開して集約した（品質レビューで発見、
    2026-08-25修正）。

    `template_name`/`sort_fields`/`department_sort_tiebreaker`をクラス変数で、
    `dept_scope_resolver`（employee→許可部署ID集合、管理者等で無制限ならNone）・
    `scope_queryset`（qs, dept_ids→qs、NULL許容の絞り込み方式）を`staticmethod()`でラップして
    指定する（documents/contracts側のscoped_lookupと同じ注入パターン）。`base_queryset()`・
    `build_search_form()`・`apply_search_filters()`・`default_order_by()`は必須のオーバーライド。
    「department」列での複合ソート（xlsx各所「部署　※部署名ではなく、部課コードで昇順/降順」）と、
    その列自体が非管理者には非表示のためのis_adminゲートは本クラスに共通実装している。
    """

    template_name = None
    page_size = 100
    sort_fields = {}
    department_sort_tiebreaker = "code"
    dept_scope_resolver = None
    scope_queryset = None

    def base_queryset(self):
        raise NotImplementedError

    def build_search_form(self, request):
        raise NotImplementedError

    def apply_search_filters(self, qs, form, is_admin):
        raise NotImplementedError

    def apply_special_sort(self, qs, sort_key, sort_dir):
        """"department"以外の特殊ソート（CategoryListViewの"group"複合ソート等）用フック。
        処理した場合はqsを返し、対象外ならNoneを返す。
        """
        return None

    def default_order_by(self, qs):
        raise NotImplementedError

    def get(self, request):
        # request.GET or Noneは避ける（accounts.services.filter_staff_querysetのコメント参照）。
        form = self.build_search_form(request)
        sort_key = request.GET.get("sort")
        sort_dir = request.GET.get("dir", "asc")
        is_admin = _is_admin(request.user)
        qs = self.base_queryset()
        dept_ids = self.dept_scope_resolver(request.user)
        qs = self.scope_queryset(qs, dept_ids)
        if form.is_valid():
            qs = self.apply_search_filters(qs, form, is_admin)
        special = self.apply_special_sort(qs, sort_key, sort_dir)
        if special is not None:
            qs = special
        elif sort_key == "department" and is_admin:
            # xlsx各所「部署　※部署名ではなく、部課コードで昇順/降順」。「部署」列自体が
            # 非管理者には非表示のため、is_adminでもゲートする（コード監査で発見：以前は
            # 非表示のはずの並び替えがsort=department直指定で非管理者でも到達できた、
            # 2026-08-24修正）。
            qs = department_composite_order_by(qs, sort_dir, self.department_sort_tiebreaker)
        else:
            field = self.sort_fields.get(sort_key)
            if field:
                prefix = "-" if sort_dir == "desc" else ""
                qs = qs.order_by(f"{prefix}{field}", self.department_sort_tiebreaker)
            else:
                qs = self.default_order_by(qs)
        paginator = Paginator(qs, self.page_size)
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


class BaseScopedMasterRegistView(View):
    """masters.Group/Categoryの登録画面共通実装。Rev1.2で追加された「部署」プルダウン
    （管理者のみ表示、非管理者は自動的に自部署が設定される）を含む。

    `template_name`/`form_class`/`form_id`/`own_url_name`（二重送信リダイレクト先＝自分自身）/
    `list_url_name`（成功後のリダイレクト先）/`unique_error_field`/`unique_error_message`/
    `audit_action`/`entity_label`（ログ文言用「分類」「カテゴリー」）をクラス変数で指定する。
    `extra_form_kwargs()`はCategoryForm特有の`employee=`引数などフォーム個別のkwargsを追加する
    フック。`audit_event_message()`/`success_message()`/`log_message()`は必須のオーバーライド。
    """

    template_name = None
    form_class = None
    form_id = None
    own_url_name = None
    list_url_name = None
    unique_error_field = "code"
    unique_error_message = None
    audit_action = None
    entity_label = None

    def extra_form_kwargs(self, request, is_admin):
        return {}

    def build_form(self, request, is_admin, data=None):
        return self.form_class(data=data, show_department=is_admin, **self.extra_form_kwargs(request, is_admin))

    def audit_event_message(self, obj):
        raise NotImplementedError

    def success_message(self, obj):
        raise NotImplementedError

    def log_message(self):
        raise NotImplementedError

    def log_args(self, form):
        return (form.cleaned_data.get("code"),)

    def get(self, request):
        is_admin = _is_admin(request.user)
        form = self.build_form(request, is_admin)
        return render(request, self.template_name, {"form": form, "token": issue_token(request.session, self.form_id)})

    def post(self, request):
        resp = reject_if_resubmitted(request, self.form_id, self.own_url_name)
        if resp is not None:
            return resp

        is_admin = _is_admin(request.user)
        form = self.build_form(request, is_admin, data=request.POST)
        if not form.is_valid():
            token = issue_token(request.session, self.form_id)
            return render(request, self.template_name, {"form": form, "token": token})
        if not is_admin:
            form.instance.department = request.user.department

        # アプリ層のclean_code等は検証後・保存前のTOCTOU競合までは防げないため、最終的な
        # 一意性はDBのUniqueConstraintに委ねる（save_or_none docstring参照）。
        obj = save_or_none(form, log_message=self.log_message(), log_args=self.log_args(form))
        if obj is None:
            # 各画面のテンプレートはmessages機構ではなくform.non_field_errors/form.<field>.errorsしか
            # 描画しないため、messages.error()ではなくform.add_error()で伝える（clean_codeが検出
            # した場合の重複エラーと同じ見た目・同じ表示場所になる）。
            form.add_error(self.unique_error_field, self.unique_error_message)
            token = issue_token(request.session, self.form_id)
            return render(request, self.template_name, {"form": form, "token": token})

        logger.info("%sを新規登録しました: code=%s", self.entity_label, obj.code)
        audit_services.log(employee=request.user, action=self.audit_action, event_message=self.audit_event_message(obj))
        messages.success(request, self.success_message(obj))
        return redirect(self.list_url_name)


class BaseScopedMasterEditView(View):
    """masters.Group/Categoryの編集画面共通実装。非管理者が編集できる対象自体も自部署のみに
    絞る（xlsx「非管理者は自部署のみ閲覧可」を一覧だけでなく編集アクセスにも適用し、URL直叩きでの
    他部署レコード編集を防ぐ。permissions.services.can_manage_target等と同じ「サーバー側でも
    強制する」方針を踏襲）。

    `template_name`/`form_class`/`form_id`/`context_object_name`（テンプレートに渡す変数名、
    "group"/"category"）/`own_url_name`/`list_url_name`/`unique_error_field`/
    `unique_error_message`/`audit_action`/`entity_label`をクラス変数で指定する。
    `scoped_lookup()`はBaseScopedMasterListViewと同じ理由でオーバーライド必須。
    """

    template_name = None
    form_class = None
    form_id = None
    context_object_name = None
    own_url_name = None
    list_url_name = None
    unique_error_field = "code"
    unique_error_message = None
    audit_action = None
    entity_label = None

    def scoped_lookup(self, request, pk):
        raise NotImplementedError

    def extra_form_kwargs(self, request, is_admin):
        return {}

    def build_form(self, request, obj, is_admin, data=None):
        return self.form_class(
            data=data, instance=obj, show_department=is_admin, **self.extra_form_kwargs(request, is_admin)
        )

    def audit_event_message(self, obj, before):
        raise NotImplementedError

    def success_message(self, obj):
        raise NotImplementedError

    def log_message(self):
        raise NotImplementedError

    def log_args(self, form):
        return (form.cleaned_data.get("code"),)

    def get(self, request, pk):
        obj = self.scoped_lookup(request, pk)
        is_admin = _is_admin(request.user)
        form = self.build_form(request, obj, is_admin)
        return render(
            request,
            self.template_name,
            {"form": form, self.context_object_name: obj, "token": issue_token(request.session, self.form_id)},
        )

    def post(self, request, pk):
        obj = self.scoped_lookup(request, pk)
        resp = reject_if_resubmitted(request, self.form_id, self.own_url_name, pk=pk)
        if resp is not None:
            return resp

        # xlsx 操作履歴ログ!B69-70＜職員マスタ更新　例＞の「更新した項目名：更新前データ ->
        # 更新後データ」形式をGroup/Category更新にも適用するため、フォームで上書きされる前の
        # 値をスナップショットしておく（浅いコピーで足りる。department等のFKはスカラーの
        # `<field>_id`しか__dict__に残らないため、書き換え後でも`before.department`は
        # コピー時点のIDで独立にDBから引き直され、正しく「更新前」の関連オブジェクトになる）。
        before = copy.copy(obj)
        is_admin = _is_admin(request.user)
        form = self.build_form(request, obj, is_admin, data=request.POST)
        if not form.is_valid():
            token = issue_token(request.session, self.form_id)
            return render(request, self.template_name, {"form": form, self.context_object_name: obj, "token": token})

        # BaseScopedMasterRegistView.postと同じ理由でIntegrityErrorをsave_or_noneで捕捉する
        # （clean_codeのexclude(pk=...)チェック後・save()前の同時更新レース対策）。
        if save_or_none(form, log_message=self.log_message(), log_args=self.log_args(form)) is None:
            form.add_error(self.unique_error_field, self.unique_error_message)
            token = issue_token(request.session, self.form_id)
            return render(request, self.template_name, {"form": form, self.context_object_name: obj, "token": token})

        logger.info("%sを更新しました: code=%s", self.entity_label, obj.code)
        audit_services.log(
            employee=request.user, action=self.audit_action, event_message=self.audit_event_message(obj, before)
        )
        messages.success(request, self.success_message(obj))
        return redirect(self.list_url_name)


class BaseScopedMasterDeleteView(View):
    """masters.Group/Categoryの削除確認画面共通実装。論理削除（is_deleted=True）のみ行う。
    紐づくデータ（文書/契約書）が0件のときのみ削除可（一覧側でもボタンをdisabled化しているが、
    URL直叩き対策でサーバー側でも検証する）。

    `template_name`/`form_id`/`context_object_name`/`own_url_name`/`list_url_name`/
    `audit_action`/`entity_label`をクラス変数で指定する。`scoped_lookup()`・`blocking_count()`
    （紐づくデータ件数、doc_kbnに応じてdoc_count/contract_countのどちらを見るか）は
    必須のオーバーライド。
    """

    template_name = None
    form_id = None
    context_object_name = None
    own_url_name = None
    list_url_name = None
    audit_action = None
    entity_label = None

    def scoped_lookup(self, request, pk):
        raise NotImplementedError

    def blocking_count(self, obj):
        raise NotImplementedError

    def get(self, request, pk):
        obj = self.scoped_lookup(request, pk)
        return render(
            request,
            self.template_name,
            {
                self.context_object_name: obj,
                "token": issue_token(request.session, self.form_id),
                # 一覧・登録・編集と同じゲーティング（xlsx「一覧の「部署」を非表示」、フィデリティ
                # 監査で発見：削除確認画面だけ条件無しで部署を表示していた不具合の再発防止）。
                "is_admin_viewer": _is_admin(request.user),
            },
        )

    def post(self, request, pk):
        obj = self.scoped_lookup(request, pk)
        resp = reject_if_resubmitted(request, self.form_id, self.own_url_name, pk=pk)
        if resp is not None:
            return resp

        count = self.blocking_count(obj)
        if count > 0:
            # count は文書/契約書件数（doc_count/contract_count）とは限らない。GroupDeleteView.
            # blocking_countのように配下カテゴリー等の別要因も加算されうるため、「文書件数」と
            # 決め打ちせず「紐づくデータ」という表現にする（品質チェック指摘、2026-09-16）。
            logger.warning(
                "紐づくデータが残っている%sの削除が試行されました: code=%s count=%s", self.entity_label, obj.code, count
            )
            messages.error(request, f"この{self.entity_label}には紐づくデータが存在するため削除できません。")
            return redirect(self.list_url_name)

        obj.is_deleted = True
        try:
            obj.save(update_fields=["is_deleted", "updated_at"])
        except DBError:
            # DB接続断・制約違反等。兄弟のBaseScopedMasterRegistView/EditView（save_or_none経由）や
            # core.record_views.BaseDeleteView（documents/contracts側の同種「削除」）と同じく、
            # 生の500応答にせずユーザーへ案内した上で一覧へ戻す（品質レビューで発見、2026-08-26修正）。
            logger.exception("%sの削除処理に失敗しました: code=%s", self.entity_label, obj.code)
            messages.error(request, "削除に失敗しました。もう一度お試しください。")
            return redirect(self.list_url_name)

        logger.info("%sを削除しました: code=%s", self.entity_label, obj.code)
        audit_services.log(
            employee=request.user,
            action=self.audit_action,
            event_message=f"No.{obj.code},{self.entity_label}名：{obj.name}",
        )
        messages.success(request, f"{self.entity_label}「{obj.name}」を削除しました。")
        return redirect(self.list_url_name)
