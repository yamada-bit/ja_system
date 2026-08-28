"""アップロードファイルをブラウザへ返す際の共通ハードニング（セキュリティレビュー H-3 対応）。

文書/契約書のファイルにはアップロード時の種別許可リストが無く、`poc.html` / `poc.svg`
（インライン JS 可）等を「文書」として登録できてしまう。DownloadView は `as_attachment=True`
（強制ダウンロード）のため比較的安全だが、PreviewView / PendingPreviewView は同じファイルを
`Content-Disposition: inline` かつアプリと同一オリジンから配信するため、`mimetypes.guess_type`
が返す `text/html` / `image/svg+xml` で開かれた瞬間に任意スクリプトが実行され、セッション
クッキー窃取・CSRF トークン取得・被害者権限での代理操作につながる（格納型 XSS）。

対策は2層:
  1. **インライン配信を PDF ＋ ラスター画像に限定** する。それ以外は `wants_inline` が True でも
     強制的に添付ダウンロード（`Content-Disposition: attachment`）へフォールバックする。
     検索プレビュー機能自体が元々画像/PDF しか対象にしていない
     （`core.file_type_services.get_preview_kind` が None を返す形式は JS 側で iframe に
     読み込ませない）ため、フォールバックによる画面上の機能低下は無い。
  2. **どの形式でも実行系ヘッダーを禁止** する。`X-Content-Type-Options: nosniff` と、
     スクリプト実行・プラグイン読み込みを禁じる最小限の `Content-Security-Policy` を必ず付与し、
     万一 content_type 判定が緩くても被害を出さないようにする。

アプリ全体への CSP 導入（`default-src 'self'` で `script-src` から `'unsafe-inline'` を外す）は
H-1/H-2 の被害低減にも有効だが、本アプリのテンプレートは原本 HTML 由来の `onclick=` 等の
インラインハンドラに全面的に依存しているため段階的な移行が必要で、ここでは扱わない
（review_security.txt H-3 の「推奨対応」参照）。
"""

import os

from core.file_type_services import IMAGE_EXTENSIONS, PDF_EXTENSION

# ブラウザが「非実行で」表示できる形式のみインライン配信を許可する。
SAFE_INLINE_EXTENSIONS = IMAGE_EXTENSIONS | {PDF_EXTENSION}

# 画像（トップレベル表示）・PDF（ブラウザ内蔵ビューア）の描画には影響させず、スクリプト実行と
# <object>/<embed> プラグイン読み込みだけを禁止する最小構成にする（`default-src 'none'` 等の
# 網羅的な制限はブラウザ内蔵 PDF ビューアの表示に影響しうるため、あえて入れない）。
FILE_RESPONSE_CSP = "script-src 'none'; object-src 'none'"


def is_safe_inline_filename(filename: str) -> bool:
    """`filename` の拡張子がインライン配信を許可された安全な形式（PDF・ラスター画像）か。"""
    _, ext = os.path.splitext((filename or "").lower())
    return ext in SAFE_INLINE_EXTENSIONS


def resolve_as_attachment(*, wants_inline: bool, filename: str) -> bool:
    """`FileResponse(as_attachment=...)` に渡す実効値。ビューが inline を望んでいても
    安全な形式でなければ True（添付ダウンロード）へ倒す。"""
    if not wants_inline:
        return True
    return not is_safe_inline_filename(filename)


def apply_file_response_security_headers(response):
    """配信レスポンスに MIME スニッフィング抑止と実行禁止 CSP を付与する。"""
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = FILE_RESPONSE_CSP
    return response
