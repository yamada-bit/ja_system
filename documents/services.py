import datetime
import logging

from django.db.models import Case, F, IntegerField, Value, When
from django.utils import timezone

from masters.models import RetentionPeriod, RetentionPeriodUnit, SystemSetting
from permissions.services import can_select_department

logger = logging.getLogger(__name__)

# xlsx 保管!B300,B581・検索・閲覧・変更!B339-340「初回登録から1週間以上経過しているものは
# 削除不可。ボタンを非表示にする」（Rev1.1で押下不可(disabled)表示から非表示に変更）。
DELETE_WINDOW_DAYS = 7


def can_delete(document) -> bool:
    """検索・閲覧画面の削除ボタン表示可否（xlsx 検索・閲覧・変更!B331,B337(Rev1.2)「削除されている
    (削除フラグがTrue)文書は、ボタンを非表示とする」）。

    2026-08-12にユーザー依頼で「ゴミ箱保管中（is_deleted=True）の文書は削除ボタンで完全削除できる」
    機能を追加していたが、Rev1.2改訂でxlsxが明示的に「削除済みなら削除ボタン自体を非表示」と
    指定したため、2026-08-24のRev1.2反映時にユーザー判断でxlsx優先とし、この完全削除機能は廃止した
    （documents.views.DeleteView docstring参照。完全削除自体はcore.management.commands.
    purge_expired_deleted_records〈自動物理削除バッチ、xlsx メイン画面!B51〉に一本化）。
    """
    if document.is_deleted:
        return False
    return timezone.now() - document.save_date < datetime.timedelta(days=DELETE_WINDOW_DAYS)


def used_retention_periods():
    """検索画面「保存期間」プルダウンの選択肢（xlsx 検索・閲覧・変更!B182-184）。
    「保存期間設定」マスタの全件ではなく、保存済み（ゴミ箱を除く）文書に実際に紐付いている
    保存期間のみを重複なしで抽出し、日数の短い順（昇順）に並べる。永年は月・年より必ず長い
    ものとして扱えばよいため、厳密な暦日数ではなく単純な近似値（月=30日、年=365日、
    永年=最大値扱い）で十分（相対順序さえ合っていればよく、この並び順自体は表示上の
    ソート専用でcalculate_expiry_date()の実際の満了日計算には使わない）。
    """
    from documents.models import Document

    used_ids = Document.objects.filter(is_deleted=False).values_list("retention_period_id", flat=True).distinct()
    return RetentionPeriod.objects.filter(pk__in=used_ids).annotate(
        _sort_days=Case(
            When(period_unit=RetentionPeriodUnit.PERMANENT, then=Value(10**9)),
            When(period_unit=RetentionPeriodUnit.YEAR, then=F("period_value") * 365),
            default=F("period_value") * 30,
            output_field=IntegerField(),
        )
    ).order_by("_sort_days")


def apply_document_edit(doc, cleaned_data, employee):
    """編集フォーム（`UploadStep2Form`, edit_mode=True）のcleaned_dataをdocに反映して保存する。
    `documents.views.DocumentEditView.post`と一括編集`BulkEditView.post`の両方から呼ばれる
    共通処理（部署解決・各フィールドコピー・expiry_date再計算・save）。監査ログの記録は
    呼び出し側の責務として残す（既存の各ビューの慣習に合わせ、audit_services.logの呼び出しは
    ここでは行わない）。
    """
    department = cleaned_data["department"]
    if not can_select_department(employee):
        department = employee.department

    doc.title = cleaned_data["title_0"]
    doc.department = department
    doc.group = cleaned_data["group"]
    doc.category = cleaned_data["category"]
    doc.year = cleaned_data["year"]
    doc.retention_period = cleaned_data["retention_period"]
    doc.privacy_flag = cleaned_data["privacy_flag"]
    doc.memo = cleaned_data["memo"]
    doc.expiry_date = calculate_expiry_date(timezone.localdate(), cleaned_data["retention_period"])
    doc.save()
    return doc


def expiry_date_previews(retention_periods) -> dict[str, str]:
    """保管画面２・編集画面の保存満了日プレビュー（JS `calculateExpiryDate()`）用。
    基準日は「保存した日」で、実際の登録/更新時に使う`save_date`/`timezone.localdate()`と
    同じく常に今日の日付（2026-08-20ユーザー確認：保存満了日＝保存した日+保存期間。
    保管画面２の「年」欄は文書の業務上の年を表すだけで、保存満了日の計算には使わない）。
    calculate_expiry_date()をそのまま再利用することで、JS側に同じ日付計算ロジックを
    二重実装せずに済ませる。
    """
    today = timezone.localdate()
    return {str(rp.pk): calculate_expiry_date(today, rp).isoformat() for rp in retention_periods}


def calculate_expiry_date(save_date: datetime.date, retention_period) -> datetime.date:
    """保存日+保存期間から保存満了日を計算する（HTML確定版の`calculateExpiryDate()`に相当）。
    「永年」は`masters.SystemSetting.retention_permanent_years`（既定50年、xlsx 保存期間設定!B74）
    を実年数として使う。
    """
    if retention_period.period_unit == RetentionPeriodUnit.PERMANENT:
        setting = SystemSetting.objects.first()
        years = setting.retention_permanent_years if setting else 50
        return _add_years(save_date, years)
    if retention_period.period_unit == RetentionPeriodUnit.YEAR:
        return _add_years(save_date, retention_period.period_value)
    # MONTH
    return _add_months(save_date, retention_period.period_value)


def _add_years(base: datetime.date, years: int) -> datetime.date:
    try:
        return base.replace(year=base.year + years)
    except ValueError:
        # 2/29起点の場合の閏年ずれ対策
        return base.replace(month=2, day=28, year=base.year + years)


def _add_months(base: datetime.date, months: int) -> datetime.date:
    month_index = base.month - 1 + months
    year = base.year + month_index // 12
    month = month_index % 12 + 1
    day = min(base.day, _days_in_month(year, month))
    return datetime.date(year, month, day)


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        next_month = datetime.date(year + 1, 1, 1)
    else:
        next_month = datetime.date(year, month + 1, 1)
    return (next_month - datetime.date(year, month, 1)).days
