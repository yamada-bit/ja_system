import csv
import logging

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView as BaseLoginView
from django.contrib.auth.views import LogoutView as BaseLogoutView
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from audit import services as audit_services
from accounts.csv_import_services import CsvImportError, import_staff_csv
from accounts.forms import LoginForm, StaffCsvImportForm, StaffEditForm, StaffRegistForm, StaffSearchForm
from accounts.models import Employee
from accounts.services import filter_staff_queryset, reset_permission_profile_if_needed
from core.csv_services import sanitize_csv_row
from core.double_submit import consume_token, issue_token
from organizations.services import departments_json
from permissions.mixins import SettingsMenuAccessMixin

logger = logging.getLogger(__name__)


class LoginView(BaseLoginView):
    """screen-login。"""

    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        # 原本index.html:3223,3230等の操作履歴ログサンプルに「ログイン」行が多数あるが、
        # 実装は元々documents/contracts系ビューでしかaudit_services.log()を呼んでおらず
        # ログイン自体が一切記録されていなかった（原本フィデリティ監査で発見）。
        response = super().form_valid(form)
        audit_services.log(employee=self.request.user, action="ログイン", event_message="ログイン")
        return response

    def form_invalid(self, form):
        # 原本にはない追加対応（2026-08-12）。ログイン失敗はブルートフォース調査・不正アクセス
        # 検知の一次情報になるが、成功時のみ記録する上のform_valid()だと失敗が一切残らず、
        # 何回誤ったパスワードが試されても気付けない状態だった。ロックアウト機能（レート制限）は
        # 失敗時の画面表示文言が原本に無い新規UI要素になってしまうため今回は対象外とし、
        # 記録のみ追加する。
        #
        # 職員番号（USERNAME_FIELD）自体が存在しない場合はEmployeeが引けないため、氏名・部署は
        # 「不明」のまま職員番号だけ記録する。パスワード自体はログに一切含めない。
        username = form.data.get("username", "")
        employee = Employee.objects.filter(employee_no=username).first() if username else None
        audit_services.log_raw(
            employee_no=username or "(未入力)",
            employee_name=employee.name if employee else "(不明)",
            department_name=str(employee.department) if employee else "(不明)",
            action="ログイン失敗",
            event_message="ログインに失敗しました（職員番号またはパスワードが誤っています）",
        )
        return super().form_invalid(form)


class LogoutView(BaseLogoutView):
    """ヘッダーの「ログアウト」ボタン（各画面共通）。"""

    def dispatch(self, request, *args, **kwargs):
        # BaseLogoutView.dispatch()の中でrequest.userがAnonymousUserに置き換わるため、
        # 記録対象のEmployeeを先に退避してからsuper()を呼ぶ。
        employee = request.user if request.user.is_authenticated else None
        response = super().dispatch(request, *args, **kwargs)
        if employee is not None:
            audit_services.log(employee=employee, action="ログアウト", event_message="ログアウト")
        return response


class StaffListView(LoginRequiredMixin, SettingsMenuAccessMixin, View):
    """screen-staff-list。1ページ100件（xlsx B64,66,68「1ページ100件程度のページャー」、Rev1.1で50→100件）。"""

    template_name = "accounts/staff_list.html"
    PAGE_SIZE = 100
    settings_menu_key = "staff_master"

    def get(self, request):
        form = StaffSearchForm(request.GET)
        sort_key = request.GET.get("sort")
        sort_dir = request.GET.get("dir", "asc")
        qs = filter_staff_queryset(form, sort_key=sort_key, sort_dir=sort_dir)
        paginator = Paginator(qs, self.PAGE_SIZE)
        page_obj = paginator.get_page(request.GET.get("page"))
        return render(
            request,
            self.template_name,
            {
                "form": form, "page_obj": page_obj, "sort_key": sort_key, "sort_dir": sort_dir,
                # xlsx 職員マスタ!B38(検索パネル)「本支所を選択時に、部課プルダウン内容を
                # 動的に更新する」。登録/編集画面（staff_regist.html/staff_edit.html）で
                # 既に使っているdepartments_json＋クライアント側フィルタの仕組みを検索パネルにも
                # 適用する（原本HTML自体はこの画面のみ静的な選択肢のままで連動JSを持たないが、
                # 同じ挙動が登録/編集では実際に動作しており、検索パネルへの適用漏れと判断）。
                "departments_json": departments_json(),
                "csv_import_form": StaffCsvImportForm(),
                "csv_import_token": issue_token(request.session, StaffCsvImportView.form_id),
            },
        )


class StaffCsvExportView(LoginRequiredMixin, SettingsMenuAccessMixin, View):
    """screen-staff-list「CSV出力」（xlsx 職員マスタ!B88-91）。
    「一覧表に表示されている内容(絞込み結果)をCSV形式で出力する」ため、一覧画面と同じ検索条件・
    ソート順（filter_staff_queryset）をcrossクエリパラメータで再現する。パスワードは
    「セキュリティ上、空欄で出力すること」（B91）の指定通り、そもそも列自体を空文字で出力する
    （実データはハッシュ化されており復元不可能なため、原本通り空欄以外の選択肢もない）。
    """

    settings_menu_key = "staff_master"

    def get(self, request):
        form = StaffSearchForm(request.GET)
        sort_key = request.GET.get("sort")
        sort_dir = request.GET.get("dir", "asc")
        qs = filter_staff_queryset(form, sort_key=sort_key, sort_dir=sort_dir)

        response = HttpResponse(content_type="text/csv; charset=utf-8-sig")
        response["Content-Disposition"] = 'attachment; filename="staff_list.csv"'
        writer = csv.writer(response)
        writer.writerow(
            ["職員番号", "氏名", "パスワード", "本支所コード", "本支所名", "部課コード", "部課名",
             "職階コード", "職階名", "役職コード", "役職名", "退職"]
        )
        for employee in qs:
            # employee.name等は登録時の自由入力のため、Excel等で開いた際の数式インジェクション対策
            # としてsanitize_csv_rowを通す（audit.views.AuditLogCsvExportViewと同じ理由）。
            writer.writerow(
                sanitize_csv_row(
                    [
                        employee.employee_no,
                        employee.name,
                        "",
                        employee.department.branch_code,
                        employee.department.branch_name,
                        employee.department.section_code,
                        employee.department.section_name,
                        employee.rank,
                        employee.get_rank_display(),
                        employee.position,
                        employee.get_position_display(),
                        "1" if employee.is_retired else "",
                    ]
                )
            )
        count = qs.count()
        logger.info("職員マスタCSV出力を実行しました: employee_no=%s 件数=%s", request.user.employee_no, count)
        # documents/views.py等のダウンロード操作（personal_info_flag=True）と同様、氏名等の個人情報を
        # 含む一覧をファイルとして出力するイベントのため、監査ログにも記録する。
        audit_services.log(
            employee=request.user,
            action="職員マスタ CSV出力",
            event_message=f"職員マスタ一覧CSV出力,件数：{count}件",
            personal_info_flag=True,
        )
        return response


class StaffCsvImportView(LoginRequiredMixin, SettingsMenuAccessMixin, View):
    """screen-staff-list「CSV取込」（xlsx 職員マスタ!B93-142）。取込結果はmessagesで一覧画面に
    要約表示する（accounts.csv_import_services.import_staff_csv参照）。
    """

    form_id = "accounts_staff_csv_import"
    settings_menu_key = "staff_master"

    def post(self, request):
        submitted_token = request.POST.get("token", "")
        if not consume_token(request.session, self.form_id, submitted_token):
            messages.error(request, "二重に送信された可能性があるため処理を中断しました。もう一度やり直してください。")
            return redirect("accounts:staff_list")

        form = StaffCsvImportForm(request.POST, request.FILES)
        if not form.is_valid():
            for error in form.errors.get("csv_file", []):
                messages.error(request, error)
            return redirect("accounts:staff_list")

        try:
            summary = import_staff_csv(form.cleaned_data["csv_file"], actor=request.user)
        except CsvImportError as exc:
            messages.error(request, str(exc))
            return redirect("accounts:staff_list")

        if summary.errors:
            messages.warning(request, f"CSV取込が完了しましたが一部エラーがありました。{summary}")
            for error in summary.errors[:20]:
                messages.error(request, error)
        else:
            messages.success(request, f"CSV取込が完了しました。{summary}")
        return redirect("accounts:staff_list")


class StaffDetailView(LoginRequiredMixin, SettingsMenuAccessMixin, View):
    """screen-staff-detail。原本はパスワードを平文表示するが、ハッシュ化必須という規約上
    実際の値は表示不可能なため一覧と同じマスク表示にする（ログイン画面のダミー値と同種の
    必然的な逸脱）。
    """

    template_name = "accounts/staff_detail.html"
    settings_menu_key = "staff_master"

    def get(self, request, pk):
        employee = get_object_or_404(Employee.objects.select_related("department"), pk=pk)
        return render(request, self.template_name, {"employee": employee})


class StaffRegistView(LoginRequiredMixin, SettingsMenuAccessMixin, View):
    """screen-staff-regist。"""

    template_name = "accounts/staff_regist.html"
    form_id = "accounts_staff_regist"
    settings_menu_key = "staff_master"

    def get(self, request):
        form = StaffRegistForm()
        token = issue_token(request.session, self.form_id)
        return render(
            request,
            self.template_name,
            {"form": form, "token": token, "departments_json": departments_json()},
        )

    def post(self, request):
        submitted_token = request.POST.get("token", "")
        if not consume_token(request.session, self.form_id, submitted_token):
            messages.error(request, "二重に送信された可能性があるため処理を中断しました。もう一度やり直してください。")
            return redirect("accounts:staff_regist")

        form = StaffRegistForm(request.POST)
        if not form.is_valid():
            token = issue_token(request.session, self.form_id)
            return render(
                request,
                self.template_name,
                {"form": form, "token": token, "departments_json": departments_json()},
            )

        try:
            employee = form.save()
        except IntegrityError:
            # clean_employee_no()でも事前チェックしているが、あくまでcheck-then-actであり、
            # 異なるセッション（＝別々の二重送信トークン）から同じ職員番号がほぼ同時に登録された
            # 場合はこのDB制約違反(IntegrityError)に至り得る。素の例外をユーザーに見せず、
            # 他の失敗経路と同じくmessages.errorで案内した上でフォームを再表示する。
            logger.exception(
                "職員登録時にIntegrityErrorが発生しました: employee_no=%s",
                form.cleaned_data.get("employee_no"),
            )
            messages.error(
                request, "同じ職員番号が別の操作で登録された可能性があります。内容を確認してもう一度お試しください。"
            )
            token = issue_token(request.session, self.form_id)
            return render(
                request,
                self.template_name,
                {"form": form, "token": token, "departments_json": departments_json()},
            )
        logger.info("職員を新規登録しました: employee_no=%s", employee.employee_no)
        # xlsx側に職員マスタ登録の操作履歴ログサンプルは無いが、masters/permissions系の登録・更新
        # ビューと同じく「マスタ登録操作」として一元記録機構(audit)を通す（原本フィデリティ監査で
        # ログイン記録漏れが見つかった際と同種の抜け漏れとして追加）。
        audit_services.log(
            employee=request.user,
            action="職員マスタ 新規登録",
            event_message=f"職員番号：{employee.employee_no},氏名：{employee.name}",
        )
        messages.success(request, f"職員「{employee.name}」を登録しました。")
        return redirect("accounts:staff_list")


class StaffEditView(LoginRequiredMixin, SettingsMenuAccessMixin, View):
    """screen-staff-edit。"""

    template_name = "accounts/staff_edit.html"
    form_id = "accounts_staff_edit"
    settings_menu_key = "staff_master"

    def get(self, request, pk):
        employee = get_object_or_404(Employee.objects.select_related("department"), pk=pk)
        form = StaffEditForm(instance=employee)
        return render(
            request,
            self.template_name,
            {
                "form": form,
                "employee": employee,
                "token": issue_token(request.session, self.form_id),
                "departments_json": departments_json(),
            },
        )

    def post(self, request, pk):
        employee = get_object_or_404(Employee.objects.select_related("department"), pk=pk)
        submitted_token = request.POST.get("token", "")
        if not consume_token(request.session, self.form_id, submitted_token):
            messages.error(request, "二重に送信された可能性があるため処理を中断しました。もう一度やり直してください。")
            return redirect("accounts:staff_edit", pk=pk)

        before_department_id = employee.department_id
        before_rank = employee.rank
        before_position = employee.position
        before_is_retired = employee.is_retired

        form = StaffEditForm(request.POST, instance=employee)
        if not form.is_valid():
            token = issue_token(request.session, self.form_id)
            return render(
                request,
                self.template_name,
                {"form": form, "employee": employee, "token": token, "departments_json": departments_json()},
            )

        try:
            employee = form.save()
        except IntegrityError:
            # StaffEditFormはemployee_no（unique制約を持つ唯一のフィールド）を編集不可にしているため
            # 現状この分岐に到達する実際の経路は無いが、StaffRegistView.postとの一貫性を保ち、
            # 将来editable項目にunique制約付きフィールドが増えた場合の保険として捕捉しておく。
            logger.exception("職員更新時にIntegrityErrorが発生しました: employee_no=%s", employee.employee_no)
            messages.error(request, "更新内容が別の操作と競合したため保存できませんでした。もう一度お試しください。")
            token = issue_token(request.session, self.form_id)
            return render(
                request,
                self.template_name,
                {"form": form, "employee": employee, "token": token, "departments_json": departments_json()},
            )
        reset_permission_profile_if_needed(
            employee,
            department_changed=employee.department_id != before_department_id,
            rank_changed=employee.rank != before_rank,
            position_changed=employee.position != before_position,
            # 「退職に設定した場合」なので未退職→退職の遷移のみを対象にする（xlsx B228）。
            # 既に退職済みの職員を退職以外の理由で編集しても毎回リセットされないようにするため、
            # employee.is_retired（現在値）ではなく遷移を渡す（accounts.services参照）。
            retired_changed=employee.is_retired and not before_is_retired,
            actor=request.user,
        )
        logger.info("職員情報を更新しました: employee_no=%s", employee.employee_no)
        # 職員マスタ登録と同様、更新操作も操作履歴ログに記録する（masters系登録・更新ビューと
        # 同じ扱い。権限プロファイルの自動リセット自体は別イベントとしてservices.py側で記録する）。
        audit_services.log(
            employee=request.user,
            action="職員マスタ 更新",
            event_message=f"職員番号：{employee.employee_no},氏名：{employee.name}",
        )
        messages.success(request, f"職員「{employee.name}」を更新しました。")
        return redirect("accounts:staff_list")
