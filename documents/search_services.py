import logging

from django.db.models import F, Q, Window
from django.db.models.functions import RowNumber

from core.text_normalization import normalize_for_search
from documents.forms import MATCH_AND
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
    # 「No.」欄はページ内の表示位置（forloop.counter）ではなく、既定表示順（保存日が新しい順）
    # における通し番号をウィンドウ関数で付与し、その行に紐付けて表示する。原本sortTable()は
    # DOM行を並べ替えるだけで各行のNo.セル自体の値は書き換えない（＝番号が行についてくる）ため、
    # ページ位置で毎回振り直すと「No.列をソートしても数字自体は常に1,2,3…のままで変わらない」
    # ように見えてしまう（2026-08-17ユーザー報告で発覚）。qs.annotate()はorder_by()より前でも
    # 後でも最終的なSELECT列に乗るだけなので、ここで付与してから後続のorder_by()で好きな順に
    # 並べ替えても、Window内のorder_by（既定順）に基づく値自体は変わらない。
    qs = qs.annotate(display_no=Window(expression=RowNumber(), order_by=F("save_date").desc()))
    field = SORT_FIELDS.get(sort_key)
    if not field:
        return qs.order_by("-save_date")
    if sort_key == "no":
        # 「No.」列は原本sortTable(1,'num',btn)と同じく、その列に表示されている数値
        # （=display_no）そのものを昇順/降順で数値比較する。display_noは既定表示順（保存日が
        # 新しい順）の通し番号のため、昇順ソートの結果は既定表示順と一致する（＝一見すると
        # 並びが変わらないように見える）が、これは「行番号を行番号で並べ替える」以上、原本でも
        # 起きる自然な結果であり不具合ではない。降順にすればすぐに逆順（並びが反転し、番号も
        # N,N-1,…,1と表示される）になることで、ソート自体は機能していることを確認できる
        # （2026-08-17、原本フィデリティ優先の方針によりsave_dateへの独自の向き付けから変更）。
        prefix = "-" if direction == "desc" else ""
        return qs.order_by(f"{prefix}display_no")
    if sort_key == "info":
        # 表示されている「部署名/年/カテゴリー」の並びと一致させるため3フィールド複合ソート
        # にする（単一フィールドのbranch_codeで近似していた旧実装は表示文字列と無関係な順序に
        # なり「ソートがおかしい」不具合だった）。
        prefix = "-" if direction == "desc" else ""
        return qs.order_by(
            f"{prefix}department__section_name",
            f"{prefix}year",
            f"{prefix}category__name",
            "-save_date",
        )
    if sort_key == "uploader":
        # 表示されている「保管・更新者の部署名｜氏名」の並びと一致させる（氏名のみでは
        # 部署をまたぐと表示と食い違って見えるため、部署名を優先キーにする）。
        prefix = "-" if direction == "desc" else ""
        return qs.order_by(
            f"{prefix}uploader__department__section_name",
            f"{prefix}uploader__name",
            "-save_date",
        )
    prefix = "-" if direction == "desc" else ""
    return qs.order_by(f"{prefix}{field}", "-save_date")


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
    words = raw_value.split()
    if not words:
        return qs
    # 半角全角を問わず検索できるようにするため、正規化済みシャドウカラム
    # （Document.title_normalized等、models.Document.save参照）に対して、キーワード側も
    # 同じ正規化をした上でicontainsする（簡易設計指示書の検索要件）。
    normalized_field = f"{field}_normalized"
    lookups = [Q(**{f"{normalized_field}__icontains": normalize_for_search(w)}) for w in words]
    if match_mode == MATCH_AND:
        combined = lookups[0]
        for lookup in lookups[1:]:
            combined &= lookup
    else:
        combined = lookups[0]
        for lookup in lookups[1:]:
            combined |= lookup
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
    if match_mode == MATCH_AND:
        combined = lookups[0]
        for lookup in lookups[1:]:
            combined &= lookup
    else:
        combined = lookups[0]
        for lookup in lookups[1:]:
            combined |= lookup
    return qs.filter(combined)


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
