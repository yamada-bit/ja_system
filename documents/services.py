import datetime

from django.conf import settings
from django.db.models import Case, F, IntegerField, Value, When
from django.utils import timezone

from core import deletion_services, scoping_services, zip_services
from masters.models import RetentionPeriod, RetentionPeriodUnit
from organizations.services import visible_department_ids
from permissions.services import can_select_department


def can_delete(document) -> bool:
    """検索・閲覧画面の削除ボタン表示可否（xlsx 検索・閲覧・変更!B331,B337(Rev1.2)「削除されている
    (削除フラグがTrue)文書は、ボタンを非表示とする」。保存から1週間〈xlsx 保管!B300,B581・
    検索・閲覧・変更!B339-340〉以上経過したものも削除不可、ボタンを非表示にする）。

    2026-08-12にユーザー依頼で「ゴミ箱保管中（is_deleted=True）の文書は削除ボタンで完全削除できる」
    機能を追加していたが、Rev1.2改訂でxlsxが明示的に「削除済みなら削除ボタン自体を非表示」と
    指定したため、2026-08-24のRev1.2反映時にユーザー判断でxlsx優先とし、この完全削除機能は廃止した
    （documents.views.DeleteView docstring参照。完全削除自体はcore.management.commands.
    purge_expired_deleted_records〈自動物理削除バッチ、xlsx メイン画面!B51〉に一本化）。

    実体はcore.deletion_services.can_deleteに集約済み（contracts.services.can_deleteとの重複を
    コード監査で発見、2026-08-25修正。deletion_denial_message/build_zip_archiveと同じ経緯）。
    """
    return deletion_services.can_delete(document)


def deletion_denial_message(document) -> str:
    """`can_delete(document)`がFalseの場合に利用者へ提示する拒否理由メッセージ。
    documents.views.DeleteView.post（AJAX/非AJAX両方）で共用する（品質レビューで発見：
    以前はビュー側でis_deletedを再判定してメッセージを組み立てており、can_delete自体が
    判定した理由とビュー側の理由文言が別々に保守される状態だった。2026-08-25修正）。
    実体はcore.deletion_services.deletion_denial_messageに集約済み（contracts.services.
    deletion_denial_messageとの重複をコード監査で発見、2026-08-25修正）。
    """
    return deletion_services.deletion_denial_message(document, entity_name="文書")


def document_searchable_department_ids(employee):
    """文書の一括ダウンロード・一括編集開始で、検索一覧（search_services.build_queryset）と
    同じ部署スコープでpkの存在確認を行うための部署ID一覧を返す。`can_select_department`が
    真（管理者）の場合はNone（無制限）、それ以外は`organizations.services.
    visible_department_ids`（自部署＋閲覧部署範囲）に限定する
    （permissions.services.contract_searchable_department_idsと同じ位置付け）。

    配置場所の非対称について（規約準拠監査で指摘）：対になるcontract_searchable_department_ids
    はpermissions.services側にあるが、こちらはdocuments.services側に置いている。理由は
    依存するデータの違いで、文書側はorganizations.services.visible_department_ids（部署の
    閲覧範囲テーブル）のみに依存し権限管理アプリのデータを参照しないのに対し、契約書側は
    それに加えてPermissionProfile.contract_visible_departments（権限管理「契約書-部門間閲覧
    設定」）というpermissionsアプリ固有のデータに依存するため、循環import回避も兼ねて
    permissions.services側に置いている。文書側に同種の権限管理データへの依存が将来追加
    されない限り、この非対称は意図的なものとして維持する。
    """
    if can_select_department(employee):
        return None
    return set(visible_department_ids(employee))


def scoped_get_object_or_404(base_qs, employee, pk):
    """文書の詳細操作（ダウンロード・プレビュー・編集・削除・一括編集）で、部署スコープ
    （`document_searchable_department_ids`）外のpkへのURL直打ちを404にしつつ、セキュリティ上
    意味のある事象としてlogger.warningに残す共通ヘルパー。

    セキュリティレビューで発見：`documents.search_services.build_queryset`は部署スコープを
    適用済みだったが、`DownloadView`/`PreviewView`/`DocumentEditView`/`DeleteView`/一括編集の
    各ビューには適用されておらず、`doc_download`/`doc_edit`権限さえあれば部署をまたいだ
    直接pkアクセスで他部署の文書を閲覧・編集・削除できてしまっていた（2026-08-25修正）。

    実体はcore.scoping_services.scoped_get_object_or_404に集約済み（contracts.services.
    scoped_get_object_or_404との重複をコード監査で発見、2026-08-25修正）。
    """
    return scoping_services.scoped_get_object_or_404(
        base_qs, employee, pk, dept_ids_resolver=document_searchable_department_ids, entity_name="文書"
    )


def build_zip_archive(documents) -> tuple[bytes, int]:
    """views.BulkDownloadView.post用のZIPアーカイブ構築（規約準拠監査で発見：ZIP圧縮という
    ビジネスロジックがビューに直書きされており、ファイル役割分担の慣習
    〈ビューから分離したロジックはservices.pyに置く〉から外れていたため分離。2026-08-25修正）。
    実体はcore.zip_services.build_zip_archiveに集約済み（contracts.services.build_zip_archiveとの
    重複をコード監査で発見、2026-08-25修正）。
    """
    return zip_services.build_zip_archive(documents, entity_label="document")


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
    「永年」は`settings.RETENTION_PERMANENT_YEARS`（既定50年、xlsx 保存期間設定!B74）を実年数として
    使う（config/settings/base.py参照。CONTRACT_RETENTION_YEARSと同じ理由で.env経由に統一）。
    """
    if retention_period.period_unit == RetentionPeriodUnit.PERMANENT:
        return _add_years(save_date, settings.RETENTION_PERMANENT_YEARS)
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
