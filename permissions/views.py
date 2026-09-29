import csv
import logging

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from accounts.models import Employee
from audit import services as audit_services
from core.csv_services import sanitize_csv_row
from core.double_submit import consume_token, issue_token
from permissions.forms import AuthorityEditForm, AuthoritySearchForm
from permissions.mixins import SettingsMenuAccessMixin
from permissions.models import CSV_EXPORT_FIELDS, MULTI_FIELDS, PermissionProfile, PermissionRole
from permissions.services import (
    can_manage_target,
    filter_authority_queryset,
    get_profile,
    get_role,
    is_admin,
    lock_active_admin_profiles,
)

logger = logging.getLogger(__name__)


class AuthorityListView(LoginRequiredMixin, SettingsMenuAccessMixin, View):
    """screen-authority-list。1ページ100件（xlsx B61,63,65「1ページ100件程度のページャー」、Rev1.1で50→100件）。"""

    template_name = "permissions/authority_list.html"
    PAGE_SIZE = 100
    settings_menu_key = "authority_management"

    def get(self, request):
        # request.GET or Noneは避ける（accounts.services.filter_staff_querysetのコメント参照）。
        form = AuthoritySearchForm(request.GET)
        sort_key = request.GET.get("sort")
        sort_dir = request.GET.get("dir", "asc")
        qs = filter_authority_queryset(request.user, form, sort_key=sort_key, sort_dir=sort_dir)
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
                # xlsx 権限管理!B35「「部署」プルダウン ※権限：管理者のみ表示」（Rev1.2で追加）。
                "is_admin_viewer": is_admin(request.user),
            },
        )


class AuthorityCsvExportView(LoginRequiredMixin, SettingsMenuAccessMixin, View):
    """screen-authority-list「CSV出力」。原本は`onclick`未設定のモックでxlsxにも列レイアウトの
    記載は無いが、一覧画面自体の列構成（原本HTML表示列）は確定しているため、他画面のCSV出力
    （xlsx 職員マスタ!B88-91「一覧表に表示されている内容をCSV出力」）と同じ考え方で、
    一覧に表示されている列をそのままCSV化する（新しい列を勝手に増やさない）。
    """

    settings_menu_key = "authority_management"

    def get(self, request):
        # request.GET or Noneは避ける（accounts.services.filter_staff_querysetのコメント参照）。
        form = AuthoritySearchForm(request.GET)
        sort_key = request.GET.get("sort")
        sort_dir = request.GET.get("dir", "asc")
        qs = filter_authority_queryset(request.user, form, sort_key=sort_key, sort_dir=sort_dir)

        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="authority_list.csv"'
        # accounts.views.StaffCsvExportViewと同じ理由でBOMを明示的に1回だけ書く
        # （charset=utf-8-sigのままだとwriterow()の都度BOMが混入する不具合があった）。
        response.write("\ufeff")
        writer = csv.writer(response)
        writer.writerow(
            ["職員番号", "部署", "氏名", "役職", "権限"]
            + [str(PermissionProfile._meta.get_field(name).verbose_name) for name in CSV_EXPORT_FIELDS]
        )
        for employee in qs:
            # 未設定判定はpermissions.services.get_profileに一元化する
            # （AuthorityDetailViewと同じ判定ロジックを重複実装しない）。
            profile = get_profile(employee)
            # employee.name・部署名・分類名等は自由入力に由来しうるため、Excel等で開いた際の
            # 数式インジェクション対策としてsanitize_csv_rowを通す
            # （audit.views.AuditLogCsvExportViewと同じ理由）。
            writer.writerow(
                sanitize_csv_row(
                    [
                        employee.employee_no,
                        str(employee.department),
                        employee.name,
                        employee.get_position_display(),
                        profile.get_role_display() if profile else "未設定",
                        *_flags_row(profile),
                    ]
                )
            )
        count = qs.count()
        logger.info(
            "権限管理一覧CSV出力を実行しました: employee_no=%s 件数=%s", request.user.employee_no, count
        )
        # accounts/views.py StaffCsvExportViewと同様、氏名・部署に加え権限フラグという機微な情報を
        # 含む一覧をファイルとして出力するイベントのため、監査ログにも記録する
        # （原本フィデリティ再監査で発見：記録漏れ）。
        audit_services.log(
            employee=request.user,
            action="権限管理　CSV出力",
            event_message=f"権限管理一覧CSV出力,件数：{count}件",
            personal_info_flag=True,
        )
        return response


def _flags_row(profile):
    """AuthorityCsvExportViewのCSVヘッダーと同じ順序（CSV_EXPORT_FIELDS）でPermissionProfileの
    フラグを文字列化する。permissions.models.FLAG_FIELDS/MULTI_FIELDSを単一情報源として
    列を自動生成するため、新しいフラグ追加時にヘッダーとこの関数がずれる心配が無い
    （コード監査で発見：以前はCSVヘッダーと本関数の両方に個別ハードコードされており、
    FLAG_FIELDS/MULTI_FIELDSとは別に手動同期が必要な3箇所目になっていた、2026-08-25修正）。
    profileがNone（PermissionProfile未設定の職員）の場合は全列を空文字にする。
    """
    if profile is None:
        return [""] * len(CSV_EXPORT_FIELDS)
    row = []
    for name in CSV_EXPORT_FIELDS:
        if name in MULTI_FIELDS:
            row.append(",".join(str(obj) for obj in getattr(profile, name).all()))
        else:
            row.append("〇" if getattr(profile, name) else "")
    return row


class AuthorityEditView(LoginRequiredMixin, View):
    """screen-authority-edit。対象職員にまだPermissionProfileが無い場合は編集画面表示時に
    既定値（全フラグFalse・一般）で新規作成する（原本は必ず権限行がある前提の静的モックのため、
    「未設定」という状態自体が実システム特有の状態であり、編集画面に入った時点で確定させる）。

    xlsx 権限管理!B156「所属長は自分の権限の変更が不可」（要再確認No.2）、B113「所属長は自分の
    部署の"一般"職員のみ権限変更可」、B153/155「所属長はロールを"職員(一般)"のみ選択可」に対応。
    以前は自分自身の権限編集のみdispatch()でブロックしており、他部署の職員や所属長・管理者
    ロールへの昇格はpkの直接指定で素通りできてしまっていた。can_manage_target()で対象職員
    ごとアクセス制御し、所属長が編集する場合はロール選択肢自体を「一般」のみに絞り込む。
    """

    template_name = "permissions/authority_edit.html"
    form_id = "permissions_authority_edit"

    def dispatch(self, request, *args, **kwargs):
        # LoginRequiredMixin.dispatch より前に request.user を権限判定・logger へ渡すと、未認証
        # （AnonymousUser）アクセス時に permission_profile / employee_no 属性が無く 500 になる
        # （permissions/mixins.py SettingsMenuAccessMixin docstring が警告する順序問題。この
        # ビューだけ自前 dispatch でその前提を崩していた。review_code_permissions_accounts No.1）。
        # 未認証はまず親へ委譲し、LoginRequiredMixin にログイン画面へリダイレクトさせる。
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)
        self.employee = get_object_or_404(Employee.objects.select_related("department"), pk=kwargs.get("pk"))
        if not can_manage_target(request.user, self.employee):
            logger.warning(
                "権限管理編集の対象外アクセスを試行: employee_no=%s target_employee_no=%s",
                request.user.employee_no, self.employee.employee_no,
            )
            # 権限管理は「権限に関わる操作」の中核画面で、所属長が pk を直指定して他部署の職員
            # （または同部署でも所属長・管理者ロールの職員）の権限編集を試みる経路は
            # 「他部署リソースへの URL 直打ちアクセス試行」に該当する。documents/contracts の
            # 部署スコープ外直打ちと同様、エンドユーザー向けの操作履歴ログにも残す
            # （CLAUDE.md「監査が必要なイベント」節、review_rule_permissions_accounts No.4、
            # 2026-09-10 ユーザー確定。管理者用画面のため logger.warning 止まりとする masters
            # とは異なり、権限管理画面は所属長にも開かれており IDOR 的試行の監査価値が高い）。
            audit_services.log_denied_cross_department_access(
                employee=request.user, entity_name="職員の権限設定", pk=self.employee.pk
            )
            raise PermissionDenied("この職員の権限は編集できません。")
        return super().dispatch(request, *args, **kwargs)

    def _editable_roles(self, request):
        """所属長がロールを昇格できないよう、対象ロールの選択肢自体を絞る（管理者は制限なし）。"""
        if get_role(request.user) == PermissionRole.MANAGER:
            return {PermissionRole.STAFF}
        return None

    def _is_admin_editor(self, request):
        """xlsx 権限管理!H182「契約書-部門間閲覧設定　※権限：管理者のみ表示」（Rev1.2で追加）。
        編集者（ログイン者）が管理者かどうかで、この項目の表示・編集可否を分ける。
        """
        return is_admin(request.user)

    def get(self, request, pk):
        profile, _ = PermissionProfile.objects.get_or_create(
            employee=self.employee, defaults={"role": PermissionRole.STAFF}
        )
        is_admin_editor = self._is_admin_editor(request)
        form = AuthorityEditForm(
            instance=profile,
            editable_roles=self._editable_roles(request),
            show_contract_visible_departments=is_admin_editor,
        )
        return render(
            request,
            self.template_name,
            {
                "form": form,
                "employee": self.employee,
                "token": issue_token(request.session, self.form_id),
                "is_admin_editor": is_admin_editor,
            },
        )

    def post(self, request, pk):
        employee = self.employee
        profile, _ = PermissionProfile.objects.get_or_create(
            employee=employee, defaults={"role": PermissionRole.STAFF}
        )
        is_admin_editor = self._is_admin_editor(request)
        submitted_token = request.POST.get("token", "")
        if not consume_token(request.session, self.form_id, submitted_token):
            messages.error(request, "二重に送信された可能性があるため処理を中断しました。もう一度やり直してください。")
            return redirect("permissions:authority_edit", pk=pk)

        form = AuthorityEditForm(
            request.POST,
            instance=profile,
            editable_roles=self._editable_roles(request),
            show_contract_visible_departments=is_admin_editor,
        )
        # フォーム検証（clean_role の would_orphan_admins による0人ガード）と保存を1トランザクション
        # にまとめ、先頭で在職管理者行をロックする（review_code_permissions_accounts No.2）。
        # admin_count は素の集計で行ロックを持たないため、別セッションの権限管理編集や CSV 取込が
        # 同時にもう1人の管理者を降格すると双方がガードを通過して管理者0人になりうる。ロック取得
        # により2つ目以降は commit まで待たされ、待機解除後の検証で減った人数を見て弾ける。
        with transaction.atomic():
            lock_active_admin_profiles()
            form_valid = form.is_valid()
            if form_valid:
                form.save()
        if not form_valid:
            token = issue_token(request.session, self.form_id)
            return render(
                request,
                self.template_name,
                {"form": form, "employee": employee, "token": token, "is_admin_editor": is_admin_editor},
            )

        logger.info("権限設定を更新しました: employee_no=%s", employee.employee_no)
        # 原本index.html:3221,3231の操作履歴ログサンプル「権限管理　更新」に対応。
        # 個々のフラグの変更差分（before→after）までは記録せず対象職員のみ記録する
        # （フラグ数が多く全項目の差分表示は本監査の範囲を超えるため、対象の追跡可能性を優先）。
        audit_services.log(
            employee=request.user,
            action="権限管理　更新",
            event_message=f"職員：{employee.name}({employee.employee_no})",
        )
        messages.success(request, f"「{employee.name}」の権限設定を更新しました。")
        return redirect("permissions:authority_list")
