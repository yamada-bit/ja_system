import datetime
import logging
from dataclasses import dataclass

from django.conf import settings
from django.db.models import Count, Q
from django.utils import timezone

from documents.models import Document

logger = logging.getLogger(__name__)


@dataclass
class NoticeCounts:
    expired_documents: int
    expired_contracts: int
    expiring_soon_documents: int
    expiring_soon_contracts: int
    recently_deleted_documents: int
    recently_deleted_contracts: int


def get_notice_counts(employee) -> NoticeCounts:
    """screen-menuの「お知らせ」3件（有効期限切れ／有効期限切れまでXヶ月以内／直近Xヶ月内で削除）を
    集計する（xlsx メイン画面!C42-46）。

    Rev1.2（2026-08-24反映）で3件とも「文書」のみから「文書、契約書」両方が対象になった
    （xlsx C42,C44,C46「・有効期限切れの文書、契約書」等）。DocumentとContractは別モデル・
    別検索画面のため、1行を「文書がX件」「契約書がY件」の2件数・2リンクに分割して表示する
    方針とした（ユーザー判断、2026-08-24。1行に統合しdocuments:searchのみへ遷移させる案も
    検討したが、2026-08-13に一度その構成にしたところ「バッジ件数と遷移先の検索結果件数が
    一致しない」問題が起きた経緯があるため、件数と遷移先が常に1対1対応する2リンク構成を
    選んだ）。

    件数は`employee`が検索・閲覧画面で実際に見られる範囲に合わせて絞り込む（以前からのdocuments
    側の方針を契約書側にも適用。documents側はcan_select_department()で管理者以外を絞り込み対象と
    判定した上でvisible_department_ids()、契約書側はcontract_searchable_department_ids()——
    それぞれ検索画面の部署絞り込みと同じ関数を使う。2026-08-24、documents側がvisible_department_ids()
    を経由せず自部署のみでフィルタしていたため、閲覧部署範囲テーブル〈部署統合・分割〉未反映の
    まま検索画面と件数が食い違うバグを修正した）。
    """
    from contracts.models import Contract
    from organizations.services import visible_department_ids
    from permissions.services import can_select_department, contract_searchable_department_ids

    today = timezone.localdate()
    soon_limit = add_months(today, settings.NOTICE_EXPIRING_THRESHOLD_MONTHS)
    deleted_since = add_months(today, -settings.NOTICE_DELETED_THRESHOLD_MONTHS)

    doc_qs = Document.objects.all()
    if not can_select_department(employee):
        # documents/search_services.pyの非管理者向け部署フィルタと同じvisible_department_ids()を使う
        # （閲覧部署範囲テーブル〈部署統合・分割〉未反映のままだと、文書検索画面と件数が食い違う）。
        doc_qs = doc_qs.filter(department_id__in=visible_department_ids(employee))

    contract_qs = Contract.objects.all()
    contract_dept_ids = contract_searchable_department_ids(employee)
    if contract_dept_ids is not None:
        contract_qs = contract_qs.filter(department_id__in=contract_dept_ids)

    doc_expired, doc_expiring_soon, doc_recently_deleted = _expiry_counts(doc_qs, today, soon_limit, deleted_since)
    contract_expired, contract_expiring_soon, contract_recently_deleted = _expiry_counts(
        contract_qs, today, soon_limit, deleted_since
    )

    return NoticeCounts(
        expired_documents=doc_expired,
        expired_contracts=contract_expired,
        expiring_soon_documents=doc_expiring_soon,
        expiring_soon_contracts=contract_expiring_soon,
        recently_deleted_documents=doc_recently_deleted,
        recently_deleted_contracts=contract_recently_deleted,
    )


def _expiry_counts(qs, today, soon_limit, deleted_since):
    """expired/expiring_soon/recently_deletedの3件数を、qsに対する1回のaggregate()で算出する。
    documents用・contracts用で同じ3条件を繰り返し書く（かつ.count()を計6回発行する）実装だったのを、
    メイン画面という高頻度アクセス画面向けに集約した。
    """
    counts = qs.aggregate(
        expired=Count("pk", filter=Q(is_deleted=False, expiry_date__lt=today)),
        expiring_soon=Count(
            "pk", filter=Q(is_deleted=False, expiry_date__gte=today, expiry_date__lte=soon_limit)
        ),
        recently_deleted=Count("pk", filter=Q(is_deleted=True, deleted_at__date__gte=deleted_since)),
    )
    return counts["expired"], counts["expiring_soon"], counts["recently_deleted"]


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
