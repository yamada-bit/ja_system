"""全テンプレート共通で必要な設定値をコンテキストへ注入するコンテキストプロセッサ。

現状は PDF プレビューの描画方式フラグ（`settings.PDF_JS_PREVIEW_ENABLED`）のみ。
base.html の検索結果詳細ポップアップ（`#popup-detail`）は全画面共通の DOM で、その
プレビュー描画は `static/js/common.js` の `renderDetailPopup()` が担う。各ビューの
`get_context_data` では網羅できないため、ここで一括して渡す。
"""

from django.conf import settings


def preview_settings(request):
    """PDF プレビュー関連の設定値。`config/settings/base.py` の PDF_JS_PREVIEW_ENABLED 参照。"""
    return {"pdf_js_preview_enabled": settings.PDF_JS_PREVIEW_ENABLED}
