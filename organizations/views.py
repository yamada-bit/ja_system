import logging

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from audit import services as audit_services
from core.double_submit import issue_token, reject_if_resubmitted
from core.form_services import save_or_none
from organizations.forms import DeptEditForm, DeptRegistForm, DeptSearchForm
from organizations.models import Department
from organizations.services import apply_dept_action, departments_list
from permissions.mixins import SettingsMenuAccessMixin

logger = logging.getLogger(__name__)

# screen-dept-listのソート対象列（xlsx 部署管理!B53-56）。
SORT_FIELDS = {
    "branch_code": "branch_code",
    "branch_name": "branch_name",
    "section_code": "section_code",
    "section_name": "section_name",
}


class DeptListView(LoginRequiredMixin, SettingsMenuAccessMixin, View):
    """screen-dept-list。xlsx B60「ページャーは不要」と明記されているため、他の一覧画面と異なり
    Paginatorは使わず内部スクロールの全件表示にする（原本HTMLにもpager-bottomが無く整合）。
    """

    template_name = "organizations/dept_list.html"
    settings_menu_key = "dept_management"

    def get(self, request):
        # request.GET or Noneは避ける（accounts.services.filter_staff_querysetのコメント参照）。
        form = DeptSearchForm(request.GET)
        sort_key = request.GET.get("sort")
        sort_dir = request.GET.get("dir", "asc")
        qs = Department.objects.all()
        if form.is_valid():
            if form.cleaned_data.get("branch_code"):
                qs = qs.filter(branch_code=form.cleaned_data["branch_code"])
            if form.cleaned_data.get("section_code"):
                qs = qs.filter(section_code=form.cleaned_data["section_code"])
        field = SORT_FIELDS.get(sort_key, "branch_code")
        prefix = "-" if sort_dir == "desc" else ""
        qs = qs.order_by(f"{prefix}{field}", "branch_code", "section_code")
        return render(
            request,
            self.template_name,
            {
                "form": form, "departments": qs, "sort_key": sort_key, "sort_dir": sort_dir,
                # accounts.views.StaffListViewの検索パネルと同じ連動プルダウン
                # （xlsx 部署管理!B38相当。本支所選択時に部課プルダウン内容を動的に更新する）。
                # 一覧本体の"departments"（Departmentのqueryset）とキーが衝突しないよう別名にする。
                # exclude_retired=True：検索パネルの部課プルダウンから退職(99)を除外する
                # （xlsx 部署管理!B45）。section_choices()による初期表示分だけでなく、本支所選択時の
                # JS再構築分にも適用する必要がある（organizations.services.departments_list参照）。
                "departments_pulldown": departments_list(exclude_retired=True),
            },
        )


class DeptRegistView(LoginRequiredMixin, SettingsMenuAccessMixin, View):
    """screen-dept-regist。"""

    template_name = "organizations/dept_regist.html"
    form_id = "organizations_dept_regist"
    settings_menu_key = "dept_management"

    def get(self, request):
        form = DeptRegistForm()
        token = issue_token(request.session, self.form_id)
        return render(request, self.template_name, {"form": form, "token": token})

    def post(self, request):
        resp = reject_if_resubmitted(request, self.form_id, "organizations:dept_regist")
        if resp is not None:
            return resp

        form = DeptRegistForm(request.POST)
        if not form.is_valid():
            token = issue_token(request.session, self.form_id)
            return render(request, self.template_name, {"form": form, "token": token})

        # DeptRegistForm.clean()でも本支所コード+部課コードの重複を事前チェックしているが、
        # あくまでcheck-then-actであり、異なるセッションからほぼ同時に同じ組み合わせが
        # 登録された場合はUniqueConstraint違反(IntegrityError)に至り得る。save_or_noneが
        # transaction.atomic()+IntegrityError捕捉+ログ記録をまとめて行う（GroupRegistView等
        # masters側と同一パターンのため集約。コード監査で発見、2026-08-25修正）。
        department = save_or_none(
            form,
            log_message="部署登録時にIntegrityErrorが発生しました: branch_code=%s section_code=%s",
            log_args=(form.cleaned_data.get("branch_code"), form.cleaned_data.get("section_code")),
        )
        if department is None:
            # 素の例外をユーザーに見せず、他の失敗経路と同じくmessages.errorで案内してフォームを
            # 再表示する。
            messages.error(
                request, "同じ本支所コード・部課コードの組み合わせが別の操作で登録された可能性があります。内容を確認してもう一度お試しください。"
            )
            token = issue_token(request.session, self.form_id)
            return render(request, self.template_name, {"form": form, "token": token})
        logger.info("部署を新規登録しました: id=%s %s", department.pk, department)
        # xlsx側に部署管理登録の操作履歴ログサンプルは無いが、masters/permissions系の登録・更新
        # ビューと同じく「マスタ登録操作」として一元記録機構(audit)を通す（原本フィデリティ監査で
        # ログイン記録漏れが見つかった際と同種の抜け漏れとして追加）。
        audit_services.log(
            employee=request.user,
            action="部署管理　新規登録",
            event_message=f"本支所コード：{department.branch_code},部課コード：{department.section_code},{department}",
        )
        messages.success(request, f"部署「{department}」を登録しました。")
        return redirect("organizations:dept_list")


class DeptEditView(LoginRequiredMixin, SettingsMenuAccessMixin, View):
    """screen-dept-edit。"""

    template_name = "organizations/dept_edit.html"
    form_id = "organizations_dept_edit"
    settings_menu_key = "dept_management"

    def get(self, request, pk):
        department = get_object_or_404(Department, pk=pk)
        form = DeptEditForm(instance=department)
        token = issue_token(request.session, self.form_id)
        return render(
            request, self.template_name, {"form": form, "department": department, "token": token}
        )

    def post(self, request, pk):
        department = get_object_or_404(Department, pk=pk)
        resp = reject_if_resubmitted(request, self.form_id, "organizations:dept_edit", pk=pk)
        if resp is not None:
            return resp

        form = DeptEditForm(request.POST, instance=department)
        if not form.is_valid():
            token = issue_token(request.session, self.form_id)
            return render(
                request, self.template_name, {"form": form, "department": department, "token": token}
            )

        dept_action = form.cleaned_data.get("dept_action")
        try:
            # form.save()とapply_dept_action()（複数targetへのDepartmentViewScope.
            # update_or_createループ）を単一のtransaction.atomic()にまとめる。以前は
            # apply_dept_action側にトランザクション・IntegrityError捕捉が無く、統合・分割の
            # 途中で例外が発生すると一部targetだけ反映された中途半端な状態になり得た上、
            # 監査ログを先に記録していたため「更新は成功したが統合・分割は未反映」という
            # ログと実態の不整合も生じ得た（コード監査で発見、2026-08-25修正）。
            with transaction.atomic():
                form.save()
                if dept_action in ("merge", "split"):
                    targets = form.cleaned_data["dept_action_target"]
                    apply_dept_action(department, dept_action, targets)
        except IntegrityError:
            # DeptEditFormのbranch_name/section_name編集自体は元々UniqueConstraint対象外だが、
            # apply_dept_actionのDepartmentViewScope.update_or_createもこのtry/exceptで
            # 保護対象になったため、DeptRegistView.postと同じくIntegrityErrorを捕捉する。
            logger.exception("部署更新時にIntegrityErrorが発生しました: id=%s", department.pk)
            messages.error(request, "更新内容が別の操作と競合したため保存できませんでした。もう一度お試しください。")
            token = issue_token(request.session, self.form_id)
            return render(
                request, self.template_name, {"form": form, "department": department, "token": token}
            )
        logger.info("部署を更新しました: id=%s %s", department.pk, department)
        # 部署登録と同様、更新操作も操作履歴ログに記録する（masters系登録・更新ビューと同じ扱い）。
        # トランザクションが成功した後に記録するため、統合・分割が失敗した場合はここに到達せず
        # 「更新 済み・統合/分割 未反映」という監査ログの不整合は起きない。
        audit_services.log(
            employee=request.user,
            action="部署管理　更新",
            event_message=f"本支所コード：{department.branch_code},部課コード：{department.section_code},{department}",
        )

        if dept_action in ("merge", "split"):
            targets = form.cleaned_data["dept_action_target"]
            target_names = "、".join(str(t) for t in targets)
            action_label = "統合" if dept_action == "merge" else "分割"
            logger.info(
                "部署%sを実行しました: department=%s targets=%s", action_label, department, target_names
            )
            audit_services.log(
                employee=request.user,
                action=f"部署管理　{action_label}",
                event_message=f"部署：{department},対象部署：{target_names}",
            )
            messages.success(request, f"部署「{department}」を更新し、「{target_names}」との{action_label}を反映しました。")
        else:
            messages.success(request, f"部署「{department}」を更新しました。")
        return redirect("organizations:dept_list")
