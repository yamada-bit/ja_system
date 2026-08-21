import datetime
import logging
from dataclasses import dataclass

from django.conf import settings
from django.utils import timezone

from documents.models import Document

logger = logging.getLogger(__name__)


@dataclass
class NoticeCounts:
    expired: int
    expiring_soon: int
    recently_deleted: int


def get_notice_counts(employee) -> NoticeCounts:
    """screen-menuの「お知らせ」3件（有効期限切れ／有効期限切れまでXヶ月以内／直近Xヶ月内で削除）を
    集計する（xlsx メイン画面!C42-46）。

    3件とも表示文言は「文書」で、件数はこの関数の通り文書(Document)基準に統一している。原本HTML
    確定版のJS（`clickNoticeLink()`）は2件目（有効期限切れまでXヶ月以内）のリンク押下時のみ
    `transitionToSearch('contract')`（契約書検索へ）を呼んでおり、表示文言・件数集計と遷移先が
    食い違う原本特有の矛盾があった（SCREENS_INVENTORY_WAVE1.md参照）。以前は原本フィデリティ優先で
    その遷移先をそのまま踏襲していたが、実運用で「バッジ件数と遷移先の検索結果件数が一致しない」
    との指摘を受け、`templates/core/menu.html`側で3件とも文書検索（`documents:search`）へ遷移する
    よう統一した（2026-08-13ユーザー判断）。

    件数は`employee`が検索・閲覧画面で実際に見られる範囲（`can_select_department()`が
    Falseの職員は自部署のみ）に合わせて絞り込む。以前は全部署の文書を無条件で集計しており、
    お知らせのバッジ件数とクリック後の検索結果件数が一致しない状態だった（2026-08-13ユーザー
    指摘）。バッジ件数は「クリックした先で実際に見える件数」と一致するのが利用者の基本的な
    期待であるため、検索画面側の絞り込みに合わせる方を採用した。
    """
    from permissions.services import can_select_department

    today = timezone.localdate()
    soon_limit = add_months(today, settings.NOTICE_EXPIRING_THRESHOLD_MONTHS)
    deleted_since = add_months(today, -settings.NOTICE_DELETED_THRESHOLD_MONTHS)

    qs = Document.objects.all()
    if not can_select_department(employee):
        qs = qs.filter(department=employee.department)

    expired = qs.filter(is_deleted=False, expiry_date__lt=today).count()
    expiring_soon = qs.filter(
        is_deleted=False, expiry_date__gte=today, expiry_date__lte=soon_limit
    ).count()
    recently_deleted = qs.filter(is_deleted=True, deleted_at__date__gte=deleted_since).count()

    return NoticeCounts(
        expired=expired, expiring_soon=expiring_soon, recently_deleted=recently_deleted
    )


def is_expiring_soon(expiry_date: datetime.date) -> bool:
    """popup-detail（検索結果詳細ポップアップ）「まもなく有効期限（更新月）」バナー用の判定。

    原本index.html:1146「この契約書はまもなく有効期限（更新月）を迎えます」に対応する状態だが、
    原本のバナーは静的モックで実データ上の判定基準が無かった（原本フィデリティ監査で発見）。
    メイン画面お知らせ「有効期限切れまでXヶ月以内」と同じ`settings.NOTICE_EXPIRING_THRESHOLD_MONTHS`
    閾値を流用し、まだ期限切れではないが閾値以内に迫っている状態として定義する。
    """
    today = timezone.localdate()
    if expiry_date < today:
        return False
    return expiry_date <= add_months(today, settings.NOTICE_EXPIRING_THRESHOLD_MONTHS)


def add_months(base: datetime.date, months: int) -> datetime.date:
    """外部ライブラリ(dateutil)への依存を増やさず月加減算するための小さなヘルパー。
    documents/contracts双方の`search_services._apply_notice_filter()`（お知らせリンクからの
    遷移時の絞り込み）でも同じ月加減算が必要なため、アプリ間で重複させずここに集約している。
    """
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
