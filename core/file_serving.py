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
import re

from django.conf import settings
from django.http import FileResponse, HttpResponse

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


# ---- Range（部分取得）対応 --------------------------------------------------------
# DjangoのFileResponseはRangeリクエストに対応せず、常にファイル全体を返す。PDF.js
# （static/js/pdf-preview.js）はサーバーがRange対応のときだけ必要なページ分のバイトを取得し、
# 非対応だとファイル全体をダウンロードしてから描画するため、500MBのPDFのプレビューを開くたびに
# 全体転送になっていた。ここでRange（単一範囲）に対応して206を返す。

# 単一範囲（"bytes=0-99" / "bytes=100-" / "bytes=-500"）のみ解釈する。複数範囲（カンマ区切り）や
# 不正な書式は、RFC 9110に従い「Rangeヘッダーを無視して全体を200で返す」。
_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")


# 配信時に1回で読み込むバイト数。DjangoのFileResponseの既定は4KBで、1MBの配信に約250回の
# read()と書き込みを繰り返す。特に部分取得（206）は下の_LimitedReaderを経由して1回あたりの
# Python側の呼び出しが増えるため、waitress上で5MBの取得が約77ms→115msとサイズに比例して
# 遅くなった（実測）。256KBにすると従来と同等（約79ms）に戻る。
FILE_RESPONSE_BLOCK_SIZE = 256 * 1024


class _LimitedReader:
    """ファイルの現在位置から remaining バイトまでだけを返すファイルライクオブジェクト
    （FileResponseにそのまま渡して206の本文を作るため）。close()で元のファイルも閉じる。"""

    def __init__(self, file_obj, remaining):
        self._file = file_obj
        self._remaining = remaining

    def read(self, size=-1):
        if self._remaining <= 0:
            return b""
        if size is None or size < 0 or size > self._remaining:
            size = self._remaining
        data = self._file.read(size)
        self._remaining -= len(data)
        return data

    def close(self):
        self._file.close()


def parse_byte_range(header, size):
    """Rangeヘッダー値を(開始, 終了)（両端を含む）に変換する。

    戻り値: None＝ヘッダー無し・解釈不能・複数範囲（全体を200で返す）。
    範囲が満たせない（開始がファイルサイズ以上、サフィックス長0）場合は ValueError を送出する
    （呼び出し側が416にする）。
    """
    if not header:
        return None
    m = _RANGE_RE.match(header.strip())
    if not m:
        return None
    first, last = m.groups()
    if first == "" and last == "":
        return None
    if first == "":  # サフィックス範囲: 末尾 last バイト
        length = int(last)
        if length == 0 or size == 0:
            raise ValueError("unsatisfiable")
        return max(size - length, 0), size - 1
    start = int(first)
    if start >= size:
        raise ValueError("unsatisfiable")
    end = size - 1 if last == "" else min(int(last), size - 1)
    if end < start:
        return None  # 逆転した範囲は不正な書式として無視する
    return start, end


def ranged_file_response(request, file_obj, *, as_attachment, filename):
    """file_obj（seek可能な開いたファイル）を、Range対応のFileResponseで返す。

    戻り値は (response, is_continuation)。is_continuation は「先頭以外の部分取得」を表し、
    PDF.jsのようにRangeで何度も取得するクライアントでは、監査ログをファイルごとに1回に
    保つため、呼び出し側は is_continuation の応答では監査ログを残さない。
    """
    size = file_obj.size
    try:
        byte_range = parse_byte_range(request.META.get("HTTP_RANGE", ""), size)
    except ValueError:
        file_obj.close()
        response = HttpResponse(status=416)
        response["Content-Range"] = f"bytes */{size}"
        return apply_file_response_security_headers(response), False

    if byte_range is None:
        response = FileResponse(file_obj, as_attachment=as_attachment, filename=filename)
        response.block_size = FILE_RESPONSE_BLOCK_SIZE
        response["Content-Length"] = str(size)
        # Range対応を「宣言」するのは大きいファイルだけにする。PDF.jsはAccept-Rangesを見て部分取得に
        # 切り替えるが、往復1回あたりの遅延が大きい環境（IIS/LB経由のテストサーバーで約0.4秒/回、
        # 1.3MBのPDFで実測）では、直列の部分取得が2〜3回増えるぶん、全体を1回で取るより遅くなる
        # （しかもPDF.jsは全体取得も止めないため転送量も増える）。小さいファイルは従来どおり全体を
        # 1回で返し、部分取得が有利になる大容量だけRangeを宣言する。Rangeヘッダー付きの要求自体は
        # 大きさによらず処理する（上の206の分岐）。
        if size >= settings.FILE_RANGE_MIN_BYTES:
            response["Accept-Ranges"] = "bytes"
        return apply_file_response_security_headers(response), False

    start, end = byte_range
    file_obj.seek(start)
    response = FileResponse(
        _LimitedReader(file_obj, end - start + 1), as_attachment=as_attachment, filename=filename
    )
    response.block_size = FILE_RESPONSE_BLOCK_SIZE
    response.status_code = 206
    response["Content-Length"] = str(end - start + 1)
    response["Content-Range"] = f"bytes {start}-{end}/{size}"
    response["Accept-Ranges"] = "bytes"
    return apply_file_response_security_headers(response), start > 0
