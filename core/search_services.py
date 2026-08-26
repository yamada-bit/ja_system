import datetime

from django.db.models import F, Q, Window
from django.db.models.functions import RowNumber

from core.text_normalization import normalize_for_search

# 検索フォームの中で、検索条件そのものではなく検索方式の切替に使う補助フィールド
# （AND/OR切替のtitle_match・freeword_match、日付欄の対象切替save_day_kbn）。
# build_search_audit_messageで単独の「項目：値」として列挙すると意味が通らないため除外する。
_SEARCH_AUDIT_EXCLUDED_FIELDS = frozenset({"title_match", "freeword_match", "save_day_kbn"})


def apply_sort(qs, sort_key, direction, sort_fields):
    """screen-searchの検索結果一覧ソート処理。documents.search_services.apply_sort/
    contracts.search_services.apply_sortが`SORT_FIELDS`辞書の中身以外完全に同一実装のまま
    重複していたため集約した（品質レビューで発見、2026-08-25修正）。

    「No.」欄はページ内の表示位置（forloop.counter）ではなく、既定表示順（保存日が新しい順）に
    おける通し番号をウィンドウ関数で付与し、その行に紐付けて表示する（2026-08-17ユーザー報告で
    発覚：ページ位置で毎回振り直すと「No.列をソートしても数字自体は常に1,2,3…のまま変わらない」
    ように見えていた）。「保存情報」「保管・更新者」列は複数フィールドの合成表示のため複合ソート
    として特別扱いする（表示文字列と無関係な単一フィールドで近似すると「ソートがおかしい」不具合に
    なる、2026-08-17修正）。この3列（no/info/uploader）の特殊扱い自体は両アプリ共通のロジック。

    `sort_fields`はソートキー→フィールド名の辞書（documents.search_services.SORT_FIELDS/
    contracts.search_services.SORT_FIELDSを渡す。アプリ固有の列はこちらで吸収する）。
    """
    qs = qs.annotate(display_no=Window(expression=RowNumber(), order_by=F("save_date").desc()))
    field = sort_fields.get(sort_key)
    if not field:
        return qs.order_by("-save_date")
    prefix = "-" if direction == "desc" else ""
    if sort_key == "no":
        # 「No.」列は原本sortTable(1,'num',btn)と同じく、その列に表示されている数値
        # （=display_no）そのものを昇順/降順で数値比較する。
        return qs.order_by(f"{prefix}display_no")
    if sort_key == "info":
        # 表示されている「部署名/年/カテゴリー」の並びと一致させるため3フィールド複合ソート。
        return qs.order_by(
            f"{prefix}department__section_name",
            f"{prefix}year",
            f"{prefix}category__name",
            "-save_date",
        )
    if sort_key == "uploader":
        # 表示されている「保管・更新者の部署名｜氏名」の並びと一致させる。
        return qs.order_by(
            f"{prefix}uploader__department__section_name",
            f"{prefix}uploader__name",
            "-save_date",
        )
    return qs.order_by(f"{prefix}{field}", "-save_date")


def _combine(lookups, match_mode, *, match_and):
    combined = lookups[0]
    for lookup in lookups[1:]:
        combined = (combined & lookup) if match_mode == match_and else (combined | lookup)
    return combined


def apply_word_filter(qs, field, raw_value, match_mode, *, match_and):
    """タイトル等、単一フィールドに対するスペース区切りAND/OR検索。documents.search_services.
    _apply_word_filter/contracts.search_services._apply_word_filterが完全に同一実装のまま
    重複していたため集約した（品質レビューで発見、2026-08-25修正）。

    半角全角を問わず検索できるようにするため、正規化済みシャドウカラム（`{field}_normalized`、
    models.save()参照）に対して、キーワード側も同じ正規化をした上でicontainsする
    （簡易設計指示書の検索要件）。`match_and`は呼び出し側のMATCH_AND定数（documents.forms/
    contracts.forms、値は"and"で共通）を渡す。
    """
    words = raw_value.split()
    if not words:
        return qs
    normalized_field = f"{field}_normalized"
    lookups = [Q(**{f"{normalized_field}__icontains": normalize_for_search(w)}) for w in words]
    return qs.filter(_combine(lookups, match_mode, match_and=match_and))


def apply_freeword_filter(qs, raw_value, match_mode, *, match_and):
    """フリーワード検索（title/memo/抽出本文の3フィールドをORで束ねた上で、複数語をAND/OR）。
    documents.search_services._apply_freeword_filter/contracts.search_services.
    _apply_freeword_filterが完全に同一実装のまま重複していたため集約した
    （品質レビューで発見、2026-08-25修正）。
    """
    words = raw_value.split()
    if not words:
        return qs
    lookups = [
        Q(title_normalized__icontains=normalize_for_search(w))
        | Q(memo_normalized__icontains=normalize_for_search(w))
        | Q(extracted_text_normalized__icontains=normalize_for_search(w))
        for w in words
    ]
    return qs.filter(_combine(lookups, match_mode, match_and=match_and))


def is_search_form_submission(get_params, field_names):
    """screen-search一覧のページャー/ソートクリック（既存の検索条件をそのままURLへ引き継いで
    再アクセスするだけの操作）と、検索フォーム自体の送信（画面下部「検索開始」ボタン）を区別する。

    ページャー/ソートは新たな検索操作ではないため操作履歴ログには残さない（xlsx 操作履歴ログ!
    B72-73＜文書検索　例＞は「検索した項目」を記録する仕様であり、同一条件の使い回しを毎回
    記録すると「画面操作の履歴」という粒度から外れ、ページ送りのたびにログが増殖してしまう。
    core.record_views.BaseBulkDownloadViewが一括ダウンロードを1件のログにまとめている設計判断と
    同じ考え方）。`page`/`sort`パラメータの有無で判定する
    （core.templatetags.search_extras.sort_urlはpageを外しsortを付与、Paginatorのページ送り
    リンクはpageのみ付与、素の初回アクセスや「条件クリア」はどちらも付与しない）。
    """
    if "page" in get_params or "sort" in get_params:
        return False
    return any(name in get_params for name in field_names)


def build_search_audit_message(form):
    """検索フォームの入力内容から操作履歴ログ用のイベントメッセージを組み立てる
    （xlsx 操作履歴ログ!B72-73＜文書検索　例＞「検索した項目：検索入力したデータ,………」、
    原本index.html:3315の契約書検索サンプル「分類：XXX,年：XXX,カテゴリー：XXX,タイトル：XXX,
    フリーワード：XXX」）。実際に値が入力/選択されたフィールドのみを、フォーム定義順で列挙する。
    呼び出し側は`form.is_valid()`が真であることを保証すること（cleaned_dataを使うため）。
    """
    parts = []
    for name, field in form.fields.items():
        if name in _SEARCH_AUDIT_EXCLUDED_FIELDS:
            continue
        value = form.cleaned_data.get(name)
        # 空のQuerySet（ModelMultipleChoiceField、department/group/category等）はDjangoの
        # __eq__未定義により`in (None, "", [], ())`のようなタプル比較では検出できず、
        # 空選択のまま「部署：」のような空ラベルが列挙されてしまう（実装時に発見）。
        # QuerySetはbool()で正しく空判定できるため、素の真偽値判定に統一する。
        if not value:
            continue
        parts.append(f"{field.label}：{_format_search_audit_value(value)}")
    return ",".join(parts) if parts else "(条件指定なし)"


def _format_search_audit_value(value):
    if isinstance(value, (list, tuple)) or hasattr(value, "all"):
        # ModelMultipleChoiceField（QuerySet）・MultipleChoiceField（値のリスト）の両方に対応。
        return "、".join(str(v) for v in value)
    if isinstance(value, datetime.date):
        return value.strftime("%Y/%m/%d")
    return str(value)
