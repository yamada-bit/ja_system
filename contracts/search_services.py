import logging

from django.db.models import F, Q, Window
from django.db.models.functions import RowNumber
from django.utils import timezone

from contracts.forms import MATCH_AND
from contracts.models import Contract
from core.text_normalization import normalize_for_search
from permissions.services import contract_searchable_department_ids

logger = logging.getLogger(__name__)


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
    # 「No.」欄はページ内の表示位置ではなく、既定表示順（保存日が新しい順）の通し番号を
    # ウィンドウ関数で行に紐付けて表示する（documents.search_services.apply_sortと同じ理由、
    # 2026-08-17ユーザー報告で発覚）。
    qs = qs.annotate(display_no=Window(expression=RowNumber(), order_by=F("save_date").desc()))
    field = SORT_FIELDS.get(sort_key)
    if not field:
        return qs.order_by("-save_date")
    if sort_key == "no":
        # 「No.」列は原本sortTable(1,'num',btn)と同じく、その列に表示されている数値
        # （=display_no、既定表示順の通し番号）そのものを昇順/降順で数値比較する
        # （documents.search_services.apply_sortと同じ理由、2026-08-17原本フィデリティ優先の
        # 方針によりsave_dateへの独自の向き付けから変更）。
        prefix = "-" if direction == "desc" else ""
        return qs.order_by(f"{prefix}display_no")
    if sort_key == "info":
        # 表示されている「部署名/年/カテゴリー」の並びと一致させるため3フィールド複合ソート
        # にする（documents.search_services.apply_sortと同じ理由で単一フィールドのbranch_code
        # 近似をやめた、2026-08-17修正）。
        prefix = "-" if direction == "desc" else ""
        return qs.order_by(
            f"{prefix}department__section_name",
            f"{prefix}year",
            f"{prefix}category__name",
            "-save_date",
        )
    if sort_key == "uploader":
        # 表示されている「保管・更新者の部署名｜氏名」の並びと一致させる
        # （documents.search_services.apply_sortと同じ理由、2026-08-17修正）。
        prefix = "-" if direction == "desc" else ""
        return qs.order_by(
            f"{prefix}uploader__department__section_name",
            f"{prefix}uploader__name",
            "-save_date",
        )
    prefix = "-" if direction == "desc" else ""
    return qs.order_by(f"{prefix}{field}", "-save_date")


def build_queryset(form, *, employee, notice=None, pks=None, sort_key=None, sort_dir="asc"):
    if notice == "recently_deleted":
        qs = Contract.objects.filter(is_deleted=True)
    else:
        qs = Contract.objects.filter(is_deleted=False)
    qs = qs.select_related("department", "group", "category", "uploader")

    # 管理者は無制限（None）。非管理者は自部署＋閲覧部署範囲テーブル（部署統合・分割）＋
    # 権限管理「契約書-部門間閲覧設定」で追加された部署に絞る
    # （xlsx 検索・閲覧・変更!B417-423(Rev1.1)、permissions.services.contract_searchable_department_ids）。
    allowed_department_ids = contract_searchable_department_ids(employee)
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
    words = raw_value.split()
    if not words:
        return qs
    # documents.search_services._apply_word_filterと同じ理由（そちらのコメント参照）。
    normalized_field = f"{field}_normalized"
    lookups = [Q(**{f"{normalized_field}__icontains": normalize_for_search(w)}) for w in words]
    combined = lookups[0]
    for lookup in lookups[1:]:
        combined = (combined & lookup) if match_mode == MATCH_AND else (combined | lookup)
    return qs.filter(combined)


def _apply_freeword_filter(qs, raw_value, match_mode):
    words = raw_value.split()
    if not words:
        return qs
    lookups = [
        Q(title_normalized__icontains=normalize_for_search(w))
        | Q(memo_normalized__icontains=normalize_for_search(w))
        | Q(extracted_text_normalized__icontains=normalize_for_search(w))
        for w in words
    ]
    combined = lookups[0]
    for lookup in lookups[1:]:
        combined = (combined & lookup) if match_mode == MATCH_AND else (combined | lookup)
    return qs.filter(combined)


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
