import logging

from django import template

from core.file_type_services import get_preview_kind

logger = logging.getLogger(__name__)
register = template.Library()


@register.filter
def preview_kind(filename):
    """検索・閲覧画面の行クリックプレビュー欄(showSearchPreview)用。画像/PDF以外の
    拡張子をiframeにそのまま読み込むと、ブラウザがinline表示できずダウンロードを
    開始してしまう（2026-08-17ユーザー報告：Excelファイルを詳細ポップアップで開いた
    瞬間にダウンロードが実行される。原因は行クリックがダブルクリックの前段としても
    発火し、この欄が拡張子判定無しでcan_downloadのみでiframe.srcを設定していたこと）。
    documents/contracts.api.DetailAPIViewと同じcore.file_type_services.get_preview_kind
    を使い、テンプレート側にも同じ判定を渡してJS側でimage/pdf以外はiframeへ読み込ませない。
    """
    return get_preview_kind(filename) or ""


@register.simple_tag
def sort_url(get_params, sort_key, current_sort, current_dir):
    """検索結果一覧のソートリンク用URLクエリ文字列を組み立てる（screen-searchの列見出し
    ▼/▲ソート、index.html`sortTable()`のサーバーサイド版）。同じ列を再クリックしたら
    昇順/降順をトグルし、別の列なら昇順から開始する。`page`パラメータは除去する
    （並び替えたら1ページ目に戻すため）。
    """
    params = get_params.copy()
    next_dir = "desc" if (sort_key == current_sort and current_dir == "asc") else "asc"
    params["sort"] = sort_key
    params["dir"] = next_dir
    params.pop("page", None)
    return "?" + params.urlencode()


@register.simple_tag
def sort_arrow(sort_key, current_sort, current_dir):
    if sort_key != current_sort:
        return "▼"
    return "▲" if current_dir == "asc" else "▼"


@register.simple_tag
def can_manage(viewer, target):
    """screen-authority-listの「編集」ボタン表示可否（xlsx 権限管理!B71-73(Rev1.1)
    「ログイン者が所属長の場合、ログイン者自身の編集は不可とし、編集ボタン非表示とする」）。
    permissions.services.can_manage_targetをテンプレートから呼べるようにするラッパー。
    """
    from permissions.services import can_manage_target

    return can_manage_target(viewer, target)
