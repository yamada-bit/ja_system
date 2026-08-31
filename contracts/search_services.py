import logging

from django.utils import timezone

from contracts.models import Contract
from core import search_services
from core.forms import MATCH_AND
from permissions.services import contract_searchable_department_ids

logger = logging.getLogger(__name__)

# build_queryset()のdept_ids引数の「未指定」を表すセンチネル（呼び出し側が計算済みのNone＝
# 管理者/無制限をそのまま渡した場合と区別するため。core.forms._DEPT_IDS_UNSETと同じ設計）。
_DEPT_IDS_UNSET = object()


SORT_FIELDS = {
    "no": "display_no",  # 特殊扱い（下記apply_sort参照）、単体では未使用。
    "title": "title",
    "info": "department__section_name",  # 特殊扱い（下記apply_sort参照）、単体では未使用。
    "contract_date": "contract_date",
    "renewal_date": "renewal_date",
    "contract_period_end": "contract_period_end",
    "contract_partner": "contract_partner",
    "uploader": "uploader__name",  # 特殊扱い(下記apply_sort参照)、単体では未使用。
    "save_date": "save_date",
    "expiry_date": "expiry_date",
    "updated_at": "updated_at",
}


def apply_sort(qs, sort_key, direction):
    """実体はcore.search_services.apply_sortに集約済み（documents.search_services.apply_sortとの
    重複をコード監査で発見、2026-08-25修正。can_delete等と同じ経緯）。"""
    return search_services.apply_sort(qs, sort_key, direction, SORT_FIELDS)


def build_queryset(form, *, employee, notice=None, pks=None, sort_key=None, sort_dir="asc", dept_ids=_DEPT_IDS_UNSET):
    if notice == "recently_deleted":
        qs = Contract.objects.filter(is_deleted=True)
    else:
        qs = Contract.objects.filter(is_deleted=False)
    qs = qs.select_related("department", "group", "category", "uploader")
    # 一覧に表示しない重いTextFieldカラムは取得しない（core.search_services.
    # LIST_DEFERRED_TEXT_FIELDS docstring参照）。
    qs = qs.defer(*search_services.LIST_DEFERRED_TEXT_FIELDS)

    # 管理者は無制限（None）。非管理者は自部署＋閲覧部署範囲テーブル（部署統合・分割）＋
    # 権限管理「契約書-部門間閲覧設定」で追加された部署に絞る
    # （xlsx 検索・閲覧・変更!B417-423(Rev1.1)、permissions.services.contract_searchable_department_ids）。
    # `dept_ids`未指定時のみここで計算する。views.SearchView.getはcontracts.forms.SearchFormが
    # 既に計算済みの値（`form.contract_dept_ids`）を渡すことで、検索画面表示のたびに
    # contract_searchable_department_ids()を2回発行していた無駄を避ける
    # （効率性レビューで発見、2026-08-25修正。documents側にはこの重複が無いため対応不要）。
    allowed_department_ids = (
        contract_searchable_department_ids(employee) if dept_ids is _DEPT_IDS_UNSET else dept_ids
    )
    if allowed_department_ids is not None:
        qs = qs.filter(department_id__in=allowed_department_ids)

    if pks:
        # 保管完了ポップアップ「登録した契約書を確認する」からの遷移。documents側と同じ理由
        # （documents.search_services.build_queryset参照）。
        #
        # pksはURLパスコンバータを経由しない生文字列のため数値以外が混入し得る。無効な値は
        # 除外し、不正アクセス試行の兆候として警告ログに残す（documents側と同じ理由）。
        valid_pks = []
        for p in pks:
            try:
                valid_pks.append(int(p))
            except (TypeError, ValueError):
                logger.warning(
                    "検索結果の絞り込み(pks)に不正な値が含まれていたため除外しました: "
                    "employee_no=%s value=%r",
                    employee.employee_no,
                    p,
                )
        return apply_sort(qs.filter(pk__in=valid_pks), sort_key, sort_dir)

    data = form.cleaned_data if form.is_valid() else {}

    if data.get("department"):
        qs = qs.filter(department__in=data["department"])
    if data.get("group"):
        qs = qs.filter(group__in=data["group"])
    if data.get("year"):
        qs = qs.filter(year__in=[int(y) for y in data["year"]])
    if data.get("category"):
        qs = qs.filter(category__in=data["category"])
    if data.get("title"):
        qs = _apply_word_filter(qs, "title", data["title"], data.get("title_match"))
    if data.get("freeword"):
        qs = _apply_freeword_filter(qs, data["freeword"], data.get("freeword_match"))
    date_field = "expiry_date" if data.get("save_day_kbn") == "expiry" else "save_date__date"
    if data.get("save_date_start"):
        qs = qs.filter(**{f"{date_field}__gte": data["save_date_start"]})
    if data.get("save_date_end"):
        qs = qs.filter(**{f"{date_field}__lte": data["save_date_end"]})

    qs = _apply_notice_filter(qs, notice)

    return apply_sort(qs, sort_key, sort_dir)


def _apply_word_filter(qs, field, raw_value, match_mode):
    """実体はcore.search_services.apply_word_filterに集約済み（documents.search_services.
    _apply_word_filterとの重複をコード監査で発見、2026-08-25修正）。"""
    return search_services.apply_word_filter(qs, field, raw_value, match_mode, match_and=MATCH_AND)


def _apply_freeword_filter(qs, raw_value, match_mode):
    """実体はcore.search_services.apply_freeword_filterに集約済み（documents.search_services.
    _apply_freeword_filterとの重複をコード監査で発見、2026-08-25修正）。"""
    return search_services.apply_freeword_filter(qs, raw_value, match_mode, match_and=MATCH_AND)


def _apply_notice_filter(qs, notice):
    """screen-menuのお知らせリンクからの遷移（core.notice_services参照）。メイン画面お知らせ
    「有効期限切れまでXヶ月以内」（表示文言は「文書」だが原本HTML実JS通り契約書検索へ遷移する。
    documents.search_services._apply_notice_filter参照）はこちらの`expiring_soon`分岐で処理する。
    """
    from django.conf import settings

    from core.notice_services import add_months

    if not notice:
        return qs
    today = timezone.localdate()
    if notice == "expired":
        return qs.filter(expiry_date__lt=today)
    if notice == "expiring_soon":
        soon_limit = add_months(today, settings.NOTICE_EXPIRING_THRESHOLD_MONTHS)
        return qs.filter(expiry_date__gte=today, expiry_date__lte=soon_limit)
    if notice == "recently_deleted":
        since = add_months(today, -settings.NOTICE_DELETED_THRESHOLD_MONTHS)
        return qs.filter(deleted_at__date__gte=since)
    return qs
