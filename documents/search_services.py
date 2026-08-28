import logging

from core import search_services
from core.forms import MATCH_AND
from documents.models import Document
from organizations.services import visible_department_ids
from permissions.services import can_select_department

logger = logging.getLogger(__name__)


# screen-search一覧のソート対象列（原本は列見出しごとに▼/▲のsort-btnを持つ、index.html
# search-table-header参照）。「保存情報」「保管・更新者」列は複数フィールドの合成表示
# （search.html参照）のため、apply_sort側でその複数フィールドの複合ソートとして扱う。
# 「保存期間」列も、__str__の文字列ではなくmasters.RetentionPeriod.display_order（画面上の
# 意図された並び順、例:1年→3年→…→永年）でソートする。いずれも表示と無関係な列
# （department__branch_code／uploader__nameのみ／retention_period_id）で近似していた旧実装は、
# 見た目上「ソートがおかしい」不具合だったため、2026-08-17に表示・意図した順序と一致させる形に
# 修正した。
SORT_FIELDS = {
    "no": "display_no",  # 特殊扱い（下記apply_sort参照）、単体では未使用。
    "title": "title",
    "info": "department__section_name",  # 特殊扱い（下記apply_sort参照）、単体では未使用。
    "uploader": "uploader__name",  # 特殊扱い（下記apply_sort参照）、単体では未使用。
    "save_date": "save_date",
    "retention_period": "retention_period__display_order",
    "expiry_date": "expiry_date",
    "updated_at": "updated_at",
}


def apply_sort(qs, sort_key, direction):
    """実体はcore.search_services.apply_sortに集約済み（contracts.search_services.apply_sortとの
    重複をコード監査で発見、2026-08-25修正。can_delete等と同じ経緯）。"""
    return search_services.apply_sort(qs, sort_key, direction, SORT_FIELDS)


def build_queryset(form, *, employee, notice=None, pks=None, sort_key=None, sort_dir="asc"):
    """screen-search（文書）の検索条件からQuerySetを組み立てる。

    タイトル／フリーワードはスペース区切りでAND/OR切替可能（xlsx 検索・閲覧・変更シート）。
    フリーワードは`extracted_text`（本文抽出テキスト）も対象にする
    （2026-08-07ユーザー指示、documents.Document.extracted_text参照）。
    """
    if notice == "recently_deleted":
        # xlsx メイン画面!C46「直近Xヶ月内で削除された文書」通知からの遷移。
        # 削除済み文書はダウンロード等は不可だが閲覧のみ可能（SCREENS_INVENTORY_WAVE1.md参照）。
        qs = Document.objects.filter(is_deleted=True)
    else:
        qs = Document.objects.filter(is_deleted=False)
    qs = qs.select_related("department", "group", "category", "retention_period", "uploader")

    if not can_select_department(employee):
        # xlsx 検索・閲覧・変更!B48(Rev1.1)「閲覧部署範囲テーブルを参照し、部署の統合/分割時の
        # 旧部署情報があればその部署をカンマ区切りで自動セットする」。自部署のみに絞る旧仕様から、
        # 閲覧部署範囲テーブル（organizations.DepartmentViewScope）で追加された部署分も含める形に
        # 拡張した（organizations.services.visible_department_ids）。
        qs = qs.filter(department_id__in=visible_department_ids(employee))

    if pks:
        # 保管完了ポップアップ「登録した文書を確認する」からの遷移（原本index.html:1665-1677
        # renderSearchResultTableForAllUploadedFiles()相当）。直前に登録した文書だけを、
        # 検索フォームの残留状態に関係なく表示する（原本フィデリティ監査で発見：以前は
        # 素の検索画面を開くだけでボタン文言が示す「絞り込み表示」が実質未実装だった）。
        #
        # pksはURLパスコンバータ（<int:pk>等）を経由しないGETクエリの生文字列のため、
        # 改ざんや不正なリンクで数値以外が混入するとpk__inのSQL評価時に未捕捉のValueErrorに
        # なり画面がクラッシュしていた（監査で発見）。無効な値は除外し、不正アクセス試行の
        # 兆候として警告ログに残す。
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

    # 部署/分類/年/カテゴリーは原本通り複数選択（チェックボックス）ポップアップのため、
    # QuerySet/リストで受け取り__inで絞り込む。
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
    # 「期間」欄はラジオ(save_day_kbn)で保存日／保存満了日どちらに適用するか切り替える
    # （screen-search!name="save-day-kbn"）。
    date_field = "expiry_date" if data.get("save_day_kbn") == "expiry" else "save_date__date"
    if data.get("save_date_start"):
        qs = qs.filter(**{f"{date_field}__gte": data["save_date_start"]})
    if data.get("save_date_end"):
        qs = qs.filter(**{f"{date_field}__lte": data["save_date_end"]})
    if data.get("retention_period"):
        qs = qs.filter(retention_period=data["retention_period"])

    qs = _apply_notice_filter(qs, notice)

    return apply_sort(qs, sort_key, sort_dir)


def _apply_word_filter(qs, field, raw_value, match_mode):
    """実体はcore.search_services.apply_word_filterに集約済み（contracts.search_services.
    _apply_word_filterとの重複をコード監査で発見、2026-08-25修正。apply_sort等と同じ経緯）。"""
    return search_services.apply_word_filter(qs, field, raw_value, match_mode, match_and=MATCH_AND)


def _apply_freeword_filter(qs, raw_value, match_mode):
    """実体はcore.search_services.apply_freeword_filterに集約済み（contracts.search_services.
    _apply_freeword_filterとの重複をコード監査で発見、2026-08-25修正）。"""
    return search_services.apply_freeword_filter(qs, raw_value, match_mode, match_and=MATCH_AND)


def _apply_notice_filter(qs, notice):
    """screen-menuのお知らせリンクからの遷移（core.notice_services参照）。is_deletedの絞り込み自体は
    build_queryset側で既に行っているため、ここでは日付範囲のみ絞り込む。
    """
    from django.conf import settings
    from django.utils import timezone

    from core.notice_services import add_months

    if not notice:
        return qs
    today = timezone.localdate()
    if notice == "expired":
        return qs.filter(expiry_date__lt=today)
    if notice == "expiring_soon":
        # 「有効期限切れまでXヵ月以内」は本日以降・Xヵ月以内の上限も必要（xlsx メイン画面!B44
        # 「本日日付よりXヵ月以内に保存期間を過ぎる予定の文書のみ」）。以前は上限が無く、
        # 未来の全ての文書がヒットしていた（2026-08-13監査で発見・修正）。
        soon_limit = add_months(today, settings.NOTICE_EXPIRING_THRESHOLD_MONTHS)
        return qs.filter(expiry_date__gte=today, expiry_date__lte=soon_limit)
    if notice == "recently_deleted":
        since = add_months(today, -settings.NOTICE_DELETED_THRESHOLD_MONTHS)
        return qs.filter(deleted_at__date__gte=since)
    return qs
