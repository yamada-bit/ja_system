import logging

from django.conf import settings
from django.utils import timezone

from audit.models import AuditLog
from core.text_normalization import filter_by_full_name

logger = logging.getLogger(__name__)


def retention_cutoff_date():
    """操作履歴ログの保持下限日（この日より前のログは一覧・CSV・DB保存の対象外）。

    xlsx 操作履歴ログ!B51-52「操作履歴ログの最大保存件数(=CSV出力最大件数)設定値は、初期値を
    3ヵ月分とし、設定ファイル等で定義し、先方より変更依頼を受けた際に容易に変更できること」。
    「3ヵ月分」を`settings.AUDIT_LOG_RETENTION_MONTHS`（.env経由、既定3）ヵ月で表現する。

    core.management.commands.purge_expired_audit_logs がこの日より古いレコードを物理削除するが、
    バッチ未実行・遅延時でも「最大保存件数＝CSV出力最大件数」を厳密に満たすため、一覧表示・
    CSV出力の絞り込み（filter_audit_log_queryset）でも同じ下限を適用する。

    月加減算は`core.notice_services.add_months`に集約済み（お知らせしきい値・物理削除バッチと
    同じロジック）。auditは下位アプリのため、documents/contractsモデルを巻き込む
    notice_servicesのモジュールロード時結合を避けて関数内importする。
    """
    from core.notice_services import add_months

    return add_months(timezone.localdate(), -settings.AUDIT_LOG_RETENTION_MONTHS)


def filter_audit_log_queryset(form):
    """screen-log-listの検索条件でAuditLogを絞り込む（一覧表示とCSV出力で共有）。

    accounts.services.filter_staff_querysetと同様、呼び出し側は`AuditLogSearchForm(request.GET)`
    のように必ず実際のQueryDictをバインドすること（`request.GET or None`にすると初回アクセス時に
    未バインド扱いとなり`is_valid()`が常にFalseを返し、下記フィルタが一切効かなくなる）。
    """
    # xlsx 操作履歴ログ!B51-52：保持期間を過ぎたログは一覧にもCSVにも出さない（retention_cutoff_date
    # のdocstring参照）。検索フォームの操作日(開始)がこれより前でも、この下限より過去には遡れない。
    qs = AuditLog.objects.filter(timestamp__date__gte=retention_cutoff_date()).order_by("-timestamp")
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


# 操作履歴ログに平文で残してはならない項目ラベルのキーワード（str.lowerして部分一致で判定）。
# xlsx 操作履歴ログ!B69-70 の汎用ルール「更新した項目名：更新前データ -> 更新後データ」を
# パスワードのような機微項目にそのまま適用すると、監査ログテーブル・CSV出力に認証情報が
# 平文で蓄積される（簡易設計指示書レビュー指摘 2-1）。呼び出し側（accounts.services.
# build_staff_edit_diff_message 等）は既に実値を渡さない運用だが、それは各呼び出し箇所が
# 個別に覚えている運用に過ぎず、新しい更新系ビューを追加する開発者が生の差分をそのまま
# 渡すと簡単に破れる。build_diff_message 側でも最終防衛としてマスクする。
SENSITIVE_DIFF_LABEL_KEYWORDS = ("パスワード", "password", "passwd", "pwd")

# マスク時に更新前/更新後の両方へ入れる固定文言。既存の呼び出し
# （build_staff_edit_diff_message が渡している ("パスワード", "(変更あり)", "(変更あり)")）と
# 同じ値にして、正常系のメッセージ文言を変えない。
REDACTED_DIFF_VALUE = "(変更あり)"


def _redact_sensitive_change(label, before, after):
    """機微項目（パスワード等）の変更前後の値をマスクして返す。

    値の内容に関わらず「変更あり」だけを残す。ラベル判定は大文字小文字を無視した部分一致
    （「パスワード」「新パスワード」「Password(確認)」等をまとめて拾う）。
    """
    lowered = str(label).lower()
    if any(keyword in lowered for keyword in SENSITIVE_DIFF_LABEL_KEYWORDS):
        return REDACTED_DIFF_VALUE, REDACTED_DIFF_VALUE
    return before, after


def build_diff_message(subject_label, changes):
    """更新イベントの「更新した項目名：更新前データ -> 更新後データ」形式メッセージを組み立てる
    （xlsx 操作履歴ログ!B69-70＜職員マスタ更新　例＞「職員：職員名(職員番号),更新した項目名：
    更新前データ -> 更新後データ,………」）。

    `changes`は実際に変更されたフィールドのみを`(項目名, 更新前, 更新後)`のタプルで渡すこと
    （変更の無いフィールドを列挙しない判断は呼び出し側の責務）。accounts.services.
    build_staff_edit_diff_message・masters.views.py各Edit系の`audit_event_message()`から使う。

    パスワード等の機微項目（SENSITIVE_DIFF_LABEL_KEYWORDS）は、呼び出し側が誤って実値を
    渡してきても`_redact_sensitive_change`で「(変更あり)」にマスクしてから連結する。
    """
    diff_parts = []
    for label, before, after in changes:
        before, after = _redact_sensitive_change(label, before, after)
        diff_parts.append(f"{label}：{before} -> {after}")
    if not diff_parts:
        return subject_label
    return subject_label + "," + ",".join(diff_parts)


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
