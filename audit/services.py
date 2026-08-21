import logging

from audit.models import AuditLog
from core.text_normalization import filter_by_full_name

logger = logging.getLogger(__name__)


def filter_audit_log_queryset(form):
    """screen-log-listの検索条件でAuditLogを絞り込む（一覧表示とCSV出力で共有）。

    accounts.services.filter_staff_querysetと同様、呼び出し側は`AuditLogSearchForm(request.GET)`
    のように必ず実際のQueryDictをバインドすること（`request.GET or None`にすると初回アクセス時に
    未バインド扱いとなり`is_valid()`が常にFalseを返し、下記フィルタが一切効かなくなる）。
    """
    qs = AuditLog.objects.order_by("-timestamp")
    if form.is_valid():
        if form.cleaned_data.get("date_start"):
            qs = qs.filter(timestamp__date__gte=form.cleaned_data["date_start"])
        if form.cleaned_data.get("date_end"):
            qs = qs.filter(timestamp__date__lte=form.cleaned_data["date_end"])
        if form.cleaned_data.get("employee_no"):
            # xlsx 操作履歴ログ!B36-37(Rev1.1)「職員番号の完全一致検索とする」。
            qs = qs.filter(employee_no=form.cleaned_data["employee_no"])
        if form.cleaned_data.get("employee_name"):
            qs = filter_by_full_name(qs, form.cleaned_data["employee_name"], field_name="employee_name")
        if form.cleaned_data.get("event_message"):
            # xlsx 操作履歴ログ!B42-43(Rev1.1)「イベントメッセージの文字列 部分一致検索とする。
            # (スペース区切りのAND検索が可能)」。
            for term in form.cleaned_data["event_message"].split():
                qs = qs.filter(event_message__icontains=term)
        if form.cleaned_data.get("personal_info_flag"):
            qs = qs.filter(personal_info_flag=True)
    return qs


def log(*, employee, action, event_message, personal_info_flag=False):
    """操作履歴ログを1件記録する（xlsx 操作履歴ログ!B63「画面名 ＋ 全角スペース ＋ ボタン名」）。

    監査ログの記録失敗で本処理（アップロード・検索等）まで失敗させたくないため、例外は握りつぶし
    ログにのみ残す（「本質的でない処理の失敗で本処理を巻き込まない」という設計判断。ただし完全な
    無音失敗は障害調査を妨げるため、logger.exceptionで必ず記録する）。
    """
    log_raw(
        employee_no=employee.employee_no,
        employee_name=employee.name,
        department_name=str(employee.department),
        action=action,
        event_message=event_message,
        personal_info_flag=personal_info_flag,
    )


def log_raw(*, employee_no, employee_name, department_name, action, event_message, personal_info_flag=False):
    """`log()`のうち、認証済みEmployeeインスタンスを経由できない場面向けの下位関数。

    ログイン失敗時（職員番号が未登録・パスワード誤りのいずれも認証済みEmployeeが手元に無い）の
    記録に使う。それ以外の用途では`log()`を使うこと（Employeeインスタンスからのスナップショット
    取得漏れ・表記ゆれを防ぐため）。
    """
    try:
        AuditLog.objects.create(
            employee_no=employee_no,
            employee_name=employee_name,
            department_name=department_name,
            action=action,
            event_message=event_message,
            personal_info_flag=personal_info_flag,
        )
    except Exception:
        logger.exception("操作履歴ログの記録に失敗しました: action=%s", action)
