import csv
import logging

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import render
from django.views import View

from audit import services as audit_services
from audit.forms import AuditLogSearchForm
from permissions.mixins import SettingsMenuAccessMixin

logger = logging.getLogger(__name__)


class AuditLogListView(LoginRequiredMixin, SettingsMenuAccessMixin, View):
    """screen-log-list。1ページ100件目安（Rev1.1で50→100件）。"""

    template_name = "audit/log_list.html"
    PAGE_SIZE = 100
    settings_menu_key = "audit_log"

    def get(self, request):
        # request.GET or Noneにすると、クエリ無しの初回アクセス時にフォームが未バインド扱いになり
        # is_valid()が常にFalseを返すため、下記フィルタが一切効かなくなる
        # （accounts.services.filter_staff_querysetで見つかった実バグと同じパターン）。
        form = AuditLogSearchForm(request.GET)
        qs = audit_services.filter_audit_log_queryset(form)
        paginator = Paginator(qs, self.PAGE_SIZE)
        page_obj = paginator.get_page(request.GET.get("page"))
        return render(request, self.template_name, {"form": form, "page_obj": page_obj})


class AuditLogCsvExportView(LoginRequiredMixin, SettingsMenuAccessMixin, View):
    """screen-log-list「CSV出力」。原本は`alert('CSV出力はデモ機能のため動作しません')`という
    未実装ボタンだが、ユーザーから明示的に実装依頼があったため実装する（CLAUDE.md「原本フィデリティに
    関する運用方針」：ユーザー指示がある場合は原本一致より優先）。accounts.views.StaffCsvExportView
    ・permissions.views.AuthorityCsvExportViewと同様、一覧表示と同じ検索条件（絞込み結果）を
    そのままCSV化する。
    """

    settings_menu_key = "audit_log"

    def get(self, request):
        # request.GET or Noneは避ける（AuditLogListViewと同じ理由）。
        form = AuditLogSearchForm(request.GET)
        qs = audit_services.filter_audit_log_queryset(form)

        response = HttpResponse(content_type="text/csv; charset=utf-8-sig")
        response["Content-Disposition"] = 'attachment; filename="audit_log_list.csv"'
        writer = csv.writer(response)
        writer.writerow(["操作日時", "職員番号", "部署名", "職員名", "操作内容", "イベントメッセージ", "個人情報"])
        for log in qs:
            writer.writerow(
                [
                    log.timestamp.strftime("%Y/%m/%d %H:%M"),
                    log.employee_no,
                    log.department_name,
                    log.employee_name,
                    log.action,
                    log.event_message,
                    "1" if log.personal_info_flag else "",
                ]
            )
        count = qs.count()
        logger.info("操作履歴ログCSV出力を実行しました: employee_no=%s 件数=%s", request.user.employee_no, count)
        # accounts.views.StaffCsvExportView等と同様、職員名等の個人情報を含む一覧をファイルとして
        # 出力するイベントのため、監査ログにも記録する。
        audit_services.log(
            employee=request.user,
            action="操作履歴ログ CSV出力",
            event_message=f"操作履歴ログ一覧CSV出力,件数：{count}件",
            personal_info_flag=True,
        )
        return response
