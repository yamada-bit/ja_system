import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import DatabaseError, IntegrityError, connection
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import TemplateView

from audit import services as audit_services
from core.double_submit import consume_token, issue_token
from core.forms import LogoutTimeForm, MenuItemSettingForm, OtherPassForm
from core.notice_services import get_notice_counts
from masters.models import SystemSetting
from organizations.models import Department, MenuItemSetting
from permissions.models import PermissionRole
from permissions.services import get_role, visible_settings_menu_items

logger = logging.getLogger(__name__)


class MenuView(LoginRequiredMixin, TemplateView):
    """screen-menu。ログイン後の起点画面。"""

    template_name = "core/menu.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["notice_counts"] = get_notice_counts(self.request.user)
        # xlsx メイン画面!N65-67(Rev1.1)は「○は表示、×は非表示」という制御方針を文言で示すのみで、
        # 原本HTML（screen-menu）自体はメニューボタンを常に静的表示するモックのまま
        # （SettingsMenuView docstring「HTML確定版自体にもボタン出し分けのJSは実装されていない」と
        # 同じ状況）。organizations.MenuItemSettingを実際にメイン画面へ連動させる試みを一度入れたが、
        # 未設定部署でボタンが全て消えてしまい原本の見た目から大きく逸脱したため撤回した
        # （2026-08-19ユーザー指摘）。
        # 原本index.html:121-122の「X ヶ月」は実際にはJSでも一度も置換されない静的モック文言
        # だったが（原本フィデリティ監査で発見）、件数側は既に実データを表示しているため、
        # こちらも実際の設定値（settings.NOTICE_EXPIRING_THRESHOLD_MONTHS/
        # NOTICE_DELETED_THRESHOLD_MONTHS）を表示するようにする（2026-08-13ユーザー指摘）。
        context["notice_expiring_threshold_months"] = settings.NOTICE_EXPIRING_THRESHOLD_MONTHS
        context["notice_deleted_threshold_months"] = settings.NOTICE_DELETED_THRESHOLD_MONTHS
        return context


class SettingsMenuView(LoginRequiredMixin, TemplateView):
    """screen-settings。各種マスタ管理・システム設定への入口。

    xlsx 設定メニュー!B31「『権限管理』メニューで設定する"権限"によって、メニューボタン
    表示/非表示を制御する」の詳細（B46以降、埋め込み画像の表）に基づき、システム権限
    （管理者/所属長/一般）ごとにボタンの表示/非表示を出し分ける
    （permissions.services.visible_settings_menu_items参照）。
    """

    template_name = "core/settings.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["menu_visibility"] = visible_settings_menu_items(self.request.user)
        return context


class OtherSettingsView(LoginRequiredMixin, View):
    """screen-other-pass / screen-other-main。原本は`onEnterOtherSettings()`がログインユーザーの
    デモ用固定id(`login-user`が"2"/"3"か否か)で管理者向け(screen-other-main)か一般向け
    (screen-other-pass)かを振り分けるモック実装。本実装ではその「意図」を実際の権限ロールに
    置き換え、`PermissionRole.ADMIN`かどうかで同じURLの表示内容を振り分ける
    （原本のダミーID分岐をそのまま持ち込むのではなく、既に導入済みの実権限概念にマッピングする）。
    """

    template_name_admin = "core/other_main.html"
    template_name_staff = "core/other_pass.html"
    form_id = "core_other_pass"
    PAGE_SIZE = 100

    def get(self, request):
        if get_role(request.user) == PermissionRole.ADMIN:
            return self._render_main(request)
        form = OtherPassForm(employee=request.user)
        return render(
            request,
            self.template_name_staff,
            {"form": form, "token": issue_token(request.session, self.form_id)},
        )

    def post(self, request):
        if get_role(request.user) == PermissionRole.ADMIN:
            # OtherMainEditView.dispatch()/OtherLogoutEditView.dispatch()と同様、権限拒否分岐は
            # logger.warningで記録する（原本フィデリティ再監査で発見：本分岐のみ記録漏れ）。
            logger.warning(
                "管理者による一般向けパスワード変更エンドポイントへのアクセス: employee_no=%s",
                request.user.employee_no,
            )
            raise PermissionDenied("この画面では操作できません。")

        submitted_token = request.POST.get("token", "")
        if not consume_token(request.session, self.form_id, submitted_token):
            messages.error(request, "二重に送信された可能性があるため処理を中断しました。もう一度やり直してください。")
            return redirect("core:other_settings")

        form = OtherPassForm(request.POST, employee=request.user)
        if not form.is_valid():
            token = issue_token(request.session, self.form_id)
            return render(request, self.template_name_staff, {"form": form, "token": token})

        request.user.set_password(form.cleaned_data["new_password"])
        try:
            request.user.save(update_fields=["password"])
        except (IntegrityError, DatabaseError):
            # パスワード保存はDB書き込みという外部境界であり、接続断・制約違反等で失敗しうる。
            # 失敗すると認証情報が不整合な状態のまま処理を続けるのは危険なので、ここで打ち切り
            # 利用者にわかるエラーを返す（本質的でない処理ではなく本処理そのものの失敗のため
            # 握りつぶさない）。
            logger.exception("パスワードの保存に失敗しました: employee_no=%s", request.user.employee_no)
            messages.error(request, "パスワードの更新に失敗しました。時間をおいて再度お試しください。")
            return redirect("core:other_settings")
        logger.info("パスワードを更新しました: employee_no=%s", request.user.employee_no)
        # set_password後はセッションのハッシュが古くなり次のリクエストでログアウトされるため、
        # 現在のセッションを新しいパスワードハッシュに合わせて更新する。
        update_session_auth_hash(request, request.user)
        # 原本index.html:3225の操作履歴ログサンプルに「パスワード　更新」行があるが、
        # 実際のパスワード値（旧→新）はハッシュ化前提の規約上ログに残さない。
        audit_services.log(employee=request.user, action="パスワード 更新", event_message="パスワードを更新しました。")
        messages.success(request, "パスワードを更新しました。")
        return redirect("core:other_settings")

    def _render_main(self, request):
        # 他の一覧画面（分類管理・カテゴリー管理・操作履歴ログ等）と同じくDjango Paginatorで
        # ページングする（原本フィデリティ監査で発見：本画面のみ静的な「1ページ固定・次へ/前へ
        # 常時disabled」のページャー描画のままで、部署数が増えても実際のページングが機能しない
        # 一貫性の欠如があった）。
        rows = []
        for department in Department.objects.order_by("branch_code", "section_code"):
            setting = getattr(department, "menu_item_setting", None)
            rows.append({"department": department, "setting": setting})
        logout_setting, _ = SystemSetting.objects.get_or_create(pk=1)
        paginator = Paginator(rows, self.PAGE_SIZE)
        page_obj = paginator.get_page(request.GET.get("page"))
        # 「メイン画面項目」/「自動ログアウト時間」のタブ選択は原本はSPAでDOMを破棄しないため
        # 保持されるが、本実装は編集画面へ実際に遷移するため、選択状態をクエリパラメータで
        # 引き継ぎサーバー側で選択中のラジオボタンとして描画し直す（ユーザー指摘：編集画面から
        # 戻るとタブ選択が原本と異なり解除されてしまう不具合の修正）。
        selected_tab = request.GET.get("tab", "main")
        if selected_tab not in ("main", "logout"):
            selected_tab = "main"
        return render(
            request,
            self.template_name_admin,
            {"page_obj": page_obj, "logout_setting": logout_setting, "selected_tab": selected_tab},
        )


class OtherMainEditView(LoginRequiredMixin, View):
    """screen-other-main-edit（管理者のみ、xlsx その他設定[2]）。"""

    template_name = "core/other_main_edit.html"
    form_id = "core_other_main_edit"

    def dispatch(self, request, *args, **kwargs):
        if get_role(request.user) != PermissionRole.ADMIN:
            logger.warning("管理者以外によるメイン画面項目編集アクセス: employee_no=%s", request.user.employee_no)
            raise PermissionDenied("この画面は管理者のみ操作できます。")
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, pk):
        department = get_object_or_404(Department, pk=pk)
        setting, _ = MenuItemSetting.objects.get_or_create(department=department)
        form = MenuItemSettingForm(instance=setting)
        # 「No.」は一覧画面(other_main.html)と同じ並び順（branch_code, section_code）での
        # 行位置を表示する。department.pk（作成順の主キー）をそのまま表示すると、一覧で見た
        # 行番号と編集画面の「No.」が食い違い、同じ行を編集しているか利用者が確認できなくなる
        # バグがあった（原本フィデリティ監査で発見。保存期間設定削除確認と同種のバグパターン）。
        ordered_ids = list(
            Department.objects.order_by("branch_code", "section_code").values_list("pk", flat=True)
        )
        no = ordered_ids.index(department.pk) + 1
        return render(
            request,
            self.template_name,
            {"form": form, "department": department, "no": no, "token": issue_token(request.session, self.form_id)},
        )

    def post(self, request, pk):
        department = get_object_or_404(Department, pk=pk)
        # xlsx B73「未設定・新規登録された部署のデフォルトは全てチェックボックスOFF状態」通り、
        # 未設定の部署は全項目Falseの新規レコードとして扱う。
        setting, _ = MenuItemSetting.objects.get_or_create(department=department)
        submitted_token = request.POST.get("token", "")
        if not consume_token(request.session, self.form_id, submitted_token):
            messages.error(request, "二重に送信された可能性があるため処理を中断しました。もう一度やり直してください。")
            return redirect("core:other_main_edit", pk=pk)

        form = MenuItemSettingForm(request.POST, instance=setting)
        if not form.is_valid():
            token = issue_token(request.session, self.form_id)
            return render(request, self.template_name, {"form": form, "department": department, "token": token})

        try:
            form.save()
        except (IntegrityError, DatabaseError):
            # DB書き込み境界。接続断・制約違反等で失敗した場合、握りつぶさず利用者にわかる
            # エラーを返す（二重送信自体はトークンで防止済みだが、それとDB書き込みの成否は別問題）。
            logger.exception("メイン画面項目設定の更新に失敗しました: department_id=%s", department.pk)
            messages.error(request, "メイン画面項目設定の更新に失敗しました。時間をおいて再度お試しください。")
            return redirect("core:other_settings")
        logger.info("メイン画面項目設定を更新しました: department_id=%s", department.pk)
        audit_services.log(
            employee=request.user,
            action="メイン画面項目設定 更新",
            event_message=f"部署：{department}",
        )
        messages.success(request, f"「{department}」のメイン画面項目を更新しました。")
        return redirect("core:other_settings")


class OtherLogoutEditView(LoginRequiredMixin, View):
    """screen-other-logout-edit（管理者のみ、xlsx その他設定[3]）。"""

    template_name = "core/other_logout_edit.html"
    form_id = "core_other_logout_edit"

    def dispatch(self, request, *args, **kwargs):
        if get_role(request.user) != PermissionRole.ADMIN:
            logger.warning("管理者以外による自動ログアウト時間編集アクセス: employee_no=%s", request.user.employee_no)
            raise PermissionDenied("この画面は管理者のみ操作できます。")
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        setting, _ = SystemSetting.objects.get_or_create(pk=1)
        form = LogoutTimeForm(instance=setting)
        return render(request, self.template_name, {"form": form, "token": issue_token(request.session, self.form_id)})

    def post(self, request):
        setting, _ = SystemSetting.objects.get_or_create(pk=1)
        submitted_token = request.POST.get("token", "")
        if not consume_token(request.session, self.form_id, submitted_token):
            messages.error(request, "二重に送信された可能性があるため処理を中断しました。もう一度やり直してください。")
            return redirect("core:other_logout_edit")

        form = LogoutTimeForm(request.POST, instance=setting)
        if not form.is_valid():
            token = issue_token(request.session, self.form_id)
            return render(request, self.template_name, {"form": form, "token": token})

        try:
            form.save()
        except (IntegrityError, DatabaseError):
            # DB書き込み境界。接続断・制約違反等で失敗した場合、握りつぶさず利用者にわかる
            # エラーを返す（この設定は全ユーザーの自動ログアウト挙動に影響するため、
            # 中途半端な状態で「更新しました」と表示させないことが特に重要）。
            logger.exception("自動ログアウト時間の更新に失敗しました")
            messages.error(request, "自動ログアウト時間の更新に失敗しました。時間をおいて再度お試しください。")
            return redirect(f"{reverse('core:other_settings')}?tab=logout")
        logger.info("自動ログアウト時間を更新しました: %s分", setting.session_idle_timeout_minutes)
        audit_services.log(
            employee=request.user,
            action="自動ログアウト時間設定 更新",
            event_message=f"時間(分)：{setting.session_idle_timeout_minutes}",
        )
        messages.success(request, "自動ログアウト時間を更新しました。")
        # 「自動ログアウト時間」タブから遷移してきた編集画面のため、戻り先も同じタブを
        # 選択した状態で一覧を再表示する（core:other_settings側でtabクエリパラメータを解釈）。
        return redirect(f"{reverse('core:other_settings')}?tab=logout")


class HealthCheckView(View):
    """ロードバランサ・監視ツール向けの死活監視エンドポイント（原本HTML/xlsxには存在しない、
    未実装改善候補の棚卸しで発見・2026-08-12追加）。既存の画面・機能とは無関係の運用インフラ
    向けエンドポイントのため、他のcore配下のビューと異なりLoginRequiredMixinを付けない
    （監視ツールは職員番号ログインを行わない）。DB接続確認のみ行い、アップロードファイル実体
    （MEDIA_ROOT）やOCR外部APIの疎通までは見ない（死活監視は「アプリが応答しDBに到達できるか」
    の最小限に留め、重い/遅い依存先まで含めると監視自体がタイムアウトの原因になり得るため）。
    """

    def get(self, request):
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
        except DatabaseError:
            logger.exception("ヘルスチェック: DB接続に失敗しました")
            return JsonResponse({"status": "error", "database": "unreachable"}, status=503)
        return JsonResponse({"status": "ok", "database": "ok"})
