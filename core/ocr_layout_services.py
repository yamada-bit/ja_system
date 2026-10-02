"""スキャンPDF（画像PDF）のOCR処理（Google Cloud Vision連携）。座標付きで抽出し、
全文テキスト（→検索用の extracted_text_normalized）と行レイアウト（→ ocr_textdata、
検索用PDFの遅延生成 core.searchable_pdf_services で使う）の両方を返す。

PDFをpdf2imageでページごとに画像化し、各ページ画像をVisionのdocument_text_detectionへ
1ページずつ個別に投入する方式で固定する。Visionの同期API batch_annotate_files にPDFバイト列を
直接渡す方式（1リクエスト最大5ページの制約がある）は採用しない——全ページ確実にOCR対象にする
ため、方式の切替は行わずページ画像分割方式のみを使う（2026-08-10ユーザー指示）。

Visionレスポンスのbounding_box（単語・記号ごとの座標）も保持し、行単位に再構成した
TextData/TextDatasとして全文テキストと合わせて返す。以前はVision標準のfull_text_annotation.text
をそのまま使う座標無しの単純版（core.ocr_services.extract_text_via_ocr）を別モジュールとして
持っていたが、pdf2image変換・Visionクライアント生成・ページ単位ループの大部分が重複していたため
2026-08-19に本モジュールへ統合・削除した（OCR座標データを保存しない設定でも常にこちらを
使い、戻り値のテキスト部分だけを使う。Vision標準の再構成ではなく座標からの独自再構成になるため、
統合前後で本文テキストの中身〈行順等〉が変わりうる点はユーザー承認済み）。

settings.OCR_ENABLED が False の間はGoogle Cloud Vision API・pdf2imageを一切呼び出さない
（機微情報を含む文書の画像データを外部クラウドAPIへ送信する経路を、設定で完全に遮断できるように
するため。extract_pending_pdf_textコマンドはOcrDisabledErrorを捕捉してスキップ扱いにする）。

移植元: C:\\Users\\yamad\\Claude\\Code\\jafyame_pj（分割アップロード＋OCR＋PDF埋め込みに特化した
別プロジェクト）の jafyame_app/process_async.py・jafyame_file.py にある行の再構成ロジック
（座標の傾き補正・行連結）。同プロジェクト固有のフォーム項目抽出（定型フォームとのテンプレート
マッチング、cv2/SIFT依存）はja_pjに不要のため移植していない。
"""
import dataclasses
import io
import logging
import math
import os
import tempfile
import time
from typing import List

from django.conf import settings

logger = logging.getLogger(__name__)

# 解像度でGoogle Cloud Vision APIのblockの区切りが変わるため、実績のある値を使う
# （元は C:\Users\yamad\Claude\Code\jafyame_pj の同種OCR実装から踏襲した値）。
OCR_PAGE_IMAGE_DPI = 200


class OcrDisabledError(Exception):
    """settings.OCR_ENABLED=False の状態でOCR実行が要求された場合に送出する。"""


class OcrTimeLimitError(Exception):
    """OCRが呼び出し元の指定した制限時間（max_seconds）を超えたため中断したことを表す。"""


class OcrRetryWaitTimeLimitError(OcrTimeLimitError):
    """Visionがエラーを返し、やり直しの待ちで制限時間を超えるため中断したことを表す。

    原因は「文書が大きくて終わらない」ではなく「Vision側の一時的な混雑」なので、バッチが
    先頭1件目の時間切れとして出す「何度実行しても完了しない大きさ」のエラーログとは区別する。
    """


# Visionが応答のerror.code（google.rpc.Code）で返す、Vision側の事情による失敗：
# DEADLINE_EXCEEDED=4／PERMISSION_DENIED=7／RESOURCE_EXHAUSTED=8／INTERNAL=13／UNAVAILABLE=14／UNAUTHENTICATED=16。
# これ以外（INVALID_ARGUMENT=3等）は、その文書（ページ画像）固有の失敗として扱う。
_SYSTEMIC_VISION_ERROR_CODES = frozenset({4, 7, 8, 13, 14, 16})


class OcrFailedError(Exception):
    """OCRが本文を得られないまま終わったことを表す（呼び出し元は「完了」にせず再試行に回す）。

    Vision APIは割当量超過（RESOURCE_EXHAUSTED、code=8）等を例外ではなく応答の `error` に
    入れて返す。これを無視すると本文が空のまま「OCR成功」として確定し、text_extracted=True に
    なって二度と再処理されない（全文検索から黙って漏れる）ため、この例外で必ず失敗扱いにする。
    """


class OcrVisionUnavailableError(OcrFailedError):
    """Vision API側の失敗（応答`error`・呼び出しの例外）がやり直しを使い切っても続いたことを表す。

    文書固有の失敗（全ページの画像化失敗等）と区別するための型。割当量超過・障害・認証エラーなど
    Vision側が原因の場合、他の文書も同じ理由で失敗するので、バッチはこの例外を受けたら
    その実行を打ち切り、無駄な呼び出しを重ねない（extract_pending_pdf_text参照）。
    """


# 同じ行とみなすy座標の許容差（200DPIで約1mm相当）。移植元のYTHRESHOLDと同じ値。
_LINE_Y_THRESHOLD = 8


@dataclasses.dataclass
class TextData:
    """OCRで検出したテキスト1行分の座標（ページ画像のピクセル座標系）とテキスト。"""

    x1: int
    y1: int
    x2: int
    y2: int
    text: str


@dataclasses.dataclass
class TextDatas:
    """1ページ分のTextDataのまとまり。page_width/page_heightはOCR時のページ画像サイズ
    （core.pdf_text_embed_services側でPDFページサイズへスケール変換する際の基準値として使う）。"""

    page_no: int
    page_width: int
    page_height: int
    textdata_list: List[TextData]


def textdatas_to_json(textdatas):
    """TextDatas のリストを DB(JSONField)・再構成に耐える素の list へ変換する（監査 案3）。
    1行 = [x1, y1, x2, y2, text] の配列形式にして、キー重複ぶんの容量を抑える
    （dict キーを毎行持つと 1000 ページ規模で無視できないため）。"""
    return [
        {
            "page": td.page_no,
            "w": td.page_width,
            "h": td.page_height,
            "lines": [[ln.x1, ln.y1, ln.x2, ln.y2, ln.text] for ln in td.textdata_list],
        }
        for td in textdatas
    ]


def textdatas_from_json(data):
    """textdatas_to_json の逆変換。検索用PDFの遅延生成（core.searchable_pdf_services）で使う。"""
    return [
        TextDatas(
            page_no=d["page"],
            page_width=d["w"],
            page_height=d["h"],
            textdata_list=[TextData(x1, y1, x2, y2, text) for x1, y1, x2, y2, text in d["lines"]],
        )
        for d in data
    ]


def extract_text_and_layout_via_ocr(
    pdf_bytes, *, source_name="", max_seconds=None, completed_pages=None, on_page_done=None,
):
    """PDFバイト列からテキストと座標データを抽出する。

    戻り値は (全文テキスト, 全ページ分のTextDatasのリスト) のタプル。後者は
    core.pdf_text_embed_services.embed_textdatas_into_pdf にそのまま渡せる形式。

    settings.OCR_ENABLED=False の場合は OcrDisabledError を送出する（呼び出し元の
    extract_pending_pdf_text コマンドが捕捉してスキップ扱いにする）。
    google-cloud-vision・pdf2imageはいずれも遅延importする：OCR_ENABLED=Falseの環境
    （未導入・poppler未導入の環境を含む）では、この関数が呼ばれない限りSDKの読み込み・
    認証情報チェック・poppler実行が一切走らないようにするため。

    ページ画像は1ページずつ変換して処理し、処理後に破棄する（従来は全ページを一度に
    メモリへ展開しており、数百ページのPDFでメモリ不足になり得たため）。1ページごとに
    pdf2image.convert_from_bytesへバイト列を渡すと毎回一時ファイルへ全体を書き出すため、
    先にPDFを一時ディレクトリへ1回だけ書き出し、パス指定（convert_from_path）で変換する。

    max_seconds を指定すると、その秒数を超えた時点で OcrTimeLimitError を送出して打ち切る
    （呼び出し元のバッチがタスクスケジューラの実行時間制限で強制終了される前に、自分で
    安全に諦められるようにするため。ページ単位でしか判定しないので、1ページの処理中は
    超過し得る）。

    completed_pages（{ページ番号: (本文, [TextDatas])}）に含まれるページはVisionへ送らずその結果を
    使い、on_page_done(ページ番号, 本文, [TextDatas])は1ページ完了するたびに呼ぶ。途中で失敗しても
    次回は済んだページを再送せず続きから再開できるようにするためのフック
    （core.ocr_checkpoint_services）。どちらも省略すれば従来どおり全ページを処理する。
    """
    if not settings.OCR_ENABLED:
        raise OcrDisabledError("OCR_ENABLED=False のためGoogle Cloud Vision連携は無効化されています。")

    from google.api_core import exceptions as api_exceptions
    from google.api_core.exceptions import GoogleAPIError

    # この文書（ページ画像）固有の失敗。Vision側の事情ではないので、バッチの打ち切り対象にしない。
    document_specific_errors = (
        api_exceptions.InvalidArgument, api_exceptions.NotFound,
        api_exceptions.FailedPrecondition, api_exceptions.OutOfRange,
    )
    from google.cloud import vision
    from pdf2image import convert_from_path, pdfinfo_from_path

    client = vision.ImageAnnotatorClient()
    poppler_path = settings.POPPLER_PATH or None
    deadline = time.monotonic() + max_seconds if max_seconds else None

    page_texts = []
    all_textdatas = []
    failed_pages = 0
    with tempfile.TemporaryDirectory(prefix="ocr_") as tmp_dir:
        pdf_path = os.path.join(tmp_dir, "source.pdf")
        with open(pdf_path, "wb") as f:
            f.write(pdf_bytes)
        # ここ（ページ数取得）はpopplerの未導入・PDF破損を例外として呼び出し元へ伝播させるため、
        # ページ単位のtry/exceptの外に置く（全ページ失敗が「本文が空のOCR完了」に化けないように）。
        page_count = int(pdfinfo_from_path(pdf_path, poppler_path=poppler_path)["Pages"])

        completed_pages = completed_pages or {}
        for page_no in range(1, page_count + 1):
            if page_no in completed_pages:
                # 前回までに済んだページ。Vision（課金・割当量）にも画像化にも触れずに結果を再利用する。
                saved_text, saved_textdatas = completed_pages[page_no]
                all_textdatas.extend(saved_textdatas)
                page_texts.append(saved_text)
                continue
            if deadline is not None and time.monotonic() > deadline:
                raise OcrTimeLimitError(
                    f"OCRが制限時間（{max_seconds}秒）を超えたため中断しました: "
                    f"{page_no - 1}/{page_count}ページ処理済み"
                )
            try:
                image = convert_from_path(
                    pdf_path, dpi=OCR_PAGE_IMAGE_DPI, fmt="jpeg",
                    first_page=page_no, last_page=page_no, poppler_path=poppler_path,
                )[0]
                buf = io.BytesIO()
                image.save(buf, format="JPEG")
                image_obj = vision.Image(content=buf.getvalue())
                # 応答レベルのエラー（割当量超過等）は例外にならないので明示的に検査する。
                # 一時的な混雑制限であることが多いため、そのページだけ待ってやり直す。やり直しを
                # 使い切ってもエラーなら、ページ単位のスキップ（下のexcept）にはせず文書ごと中断する
                # （続行しても後続ページが同じ理由で失敗しやすく、本文が欠けたまま「完了」になるため）。
                retries = max(settings.OCR_VISION_RETRY_COUNT, 0)
                systemic = True  # 直近の失敗が、他の文書でも起こりうる（Vision側の）失敗か
                for attempt in range(retries + 1):
                    try:
                        response = client.document_text_detection(
                            image=image_obj, image_context={"language_hints": ["ja"]},
                            timeout=settings.OCR_VISION_TIMEOUT_SECONDS,
                        )
                    except GoogleAPIError as exc:
                        # タイムアウト（DeadlineExceeded）・接続断・一時的なサーバーエラー等、呼び出し
                        # 自体の失敗も、応答`error`と同じくそのページだけやり直す。使い切っても失敗なら
                        # 文書ごと失敗（下のOcrFailedError）。ページを飛ばして完了にすると本文が欠けたまま
                        # text_extracted=Trueで確定し、全文検索から永久に漏れるため。
                        systemic = not isinstance(exc, document_specific_errors)
                        message = (
                            f"Vision API呼び出しに失敗しました: {type(exc).__name__}: {exc} "
                            f"source={source_name} page={page_no}"
                        )
                    else:
                        if response.error.code == 0:
                            break
                        systemic = response.error.code in _SYSTEMIC_VISION_ERROR_CODES
                        message = (
                            f"Vision APIがエラーを返しました: code={response.error.code} "
                            f"message={response.error.message} source={source_name} page={page_no}"
                        )
                    if attempt >= retries:
                        # 割当量超過・障害・認証エラー等は他の文書でも同じ理由で失敗するので、バッチが
                        # 実行ごと打ち切れるよう専用の型で送出する。画像が大きすぎる等、この文書だけの
                        # 失敗（INVALID_ARGUMENT等）は、文書ごと失敗にするだけで他の文書は続ける。
                        raise (OcrVisionUnavailableError if systemic else OcrFailedError)(message)
                    wait = settings.OCR_VISION_RETRY_WAIT_SECONDS * (2 ** attempt)
                    if deadline is not None and time.monotonic() + wait > deadline:
                        # 待つと制限時間を超える。待たずに諦め、次回バッチに持ち越す。
                        raise OcrRetryWaitTimeLimitError(
                            f"OCRのやり直し待ちで制限時間（{max_seconds}秒）を超えるため中断しました: "
                            f"{page_no}/{page_count}ページ目"
                        )
                    logger.warning(
                        "%s。%s秒待って再試行します（%s/%s回目）", message, wait, attempt + 1, retries,
                    )
                    time.sleep(wait)
                page_textdatas = _get_lines(page_no, response)
                page_text = "\n".join(_get_textlines(page_textdatas, page_no))
                all_textdatas.extend(page_textdatas)
                page_texts.append(page_text)
                if on_page_done is not None:
                    on_page_done(page_no, page_text, page_textdatas)
            except (OcrFailedError, OcrTimeLimitError):
                raise
            except Exception:
                # 1ページの画像化など文書側の原因による失敗で文書全体の処理を止めない。このページの
                # 本文・座標データは欠落するが、他ページは継続する（移植元process_pdf_asyncの
                # ページ単位try/exceptと同じ設計判断）。Vision API側の失敗（GoogleAPIError）は
                # 上でやり直し、使い切れば文書ごと失敗にするので、ここには来ない。
                logger.exception(
                    "座標付きOCR処理でページの処理に失敗しました（このページはスキップ）: source=%s page=%s",
                    source_name, page_no,
                )
                failed_pages += 1

    if page_count > 0 and failed_pages == page_count:
        # 全ページ失敗が「本文が空のOCR完了」に化けないように（一部ページだけの失敗は従来どおり
        # スキップして他ページの本文を採用する）。
        raise OcrFailedError(f"全{page_count}ページのOCRに失敗しました: source={source_name}")

    if source_name:
        logger.info(
            "Google Cloud Vision OCR（座標付き）を実行しました: source=%s pages=%s", source_name, page_count,
        )

    return "\n".join(page_texts), all_textdatas


def _get_lines(page_no, response):
    """block内のsymbolデータをy座標でソートして行ごとにx座標でソートし、TextDatasを作る。

    移植元: jafyame_pj/jafyame_app/process_async.py get_lines（フォーム領域絞り込み用の
    areas引数を持つ版が別途sv_extract_text.pyにあるが、本モジュールでは常にページ全体を
    1領域として扱うため、areas引数を持たないprocess_async.py版をベースにした）。
    """
    from google.cloud import vision

    textdatas = []
    sp = " "
    sure_sp = " "
    unk = ""

    for page in response.full_text_annotation.pages:
        page_width = page.width
        page_height = page.height
        rotate_angle = _get_rotate_angle(page)
        start_x, start_y, end_x, end_y = 0, 0, page_width, page_height
        center_x = (start_x + end_x) / 2
        center_y = (start_y + end_y) / 2

        lines = []
        degrees = []
        for block in page.blocks:
            x11 = block.bounding_box.vertices[0].x
            y11 = block.bounding_box.vertices[0].y
            x22 = block.bounding_box.vertices[2].x
            y22 = block.bounding_box.vertices[2].y
            x1 = min(x11, x22)
            y1 = min(y11, y22)
            x2 = max(x11, x22)
            y2 = max(y11, y22)
            if end_x < x1 or x2 < start_x or end_y < y1 or y2 < start_y:
                continue
            for paragraph in block.paragraphs:
                pre_wx1 = pre_wx2 = pre_wy1 = pre_wy2 = -1
                symbols = []
                for word in paragraph.words:
                    degree = _get_bounding_degree(word)
                    degrees.append(degree)
                    wx11 = word.bounding_box.vertices[0].x
                    wy11 = word.bounding_box.vertices[0].y
                    wx22 = word.bounding_box.vertices[2].x
                    wy22 = word.bounding_box.vertices[2].y
                    wx1 = min(wx11, wx22)
                    wy1 = min(wy11, wy22)
                    wx2 = max(wx11, wx22)
                    wy2 = max(wy11, wy22)
                    if end_x < wx1 or wx2 < start_x or end_y < wy1 or wy2 < start_y:
                        continue
                    pos = _get_pos(word, page_width, page_height, rotate_angle)
                    wx1 = min(pos[0], pos[2])
                    wy1 = min(pos[1], pos[3])
                    wx2 = max(pos[0], pos[2])
                    wy2 = max(pos[1], pos[3])
                    # paragraph内でy座標が連続するwordは同じ行として連結する
                    if pre_wy1 == -1:
                        pre_wx1, pre_wx2, pre_wy1, pre_wy2 = wx1, wx2, wy1, wy2
                    elif pre_wx2 < wx2 and pre_wy1 <= wy1 <= pre_wy2:
                        pre_wx1, pre_wx2, pre_wy1, pre_wy2 = wx1, wx2, wy1, wy2
                    elif pre_wx2 < wx2 and pre_wy1 <= wy2 <= pre_wy2:
                        pre_wx1, pre_wx2, pre_wy1, pre_wy2 = wx1, wx2, wy1, wy2
                    elif pre_wx2 < wx2 and wy1 <= pre_wy1 and pre_wy2 <= wy2:
                        pre_wx1, pre_wx2, pre_wy1, pre_wy2 = wx1, wx2, wy1, wy2
                    else:
                        lines.append(symbols)
                        symbols = []
                        pre_wx1, pre_wx2, pre_wy1, pre_wy2 = wx1, wx2, wy1, wy2
                    for symbol in word.symbols:
                        pos = _get_pos(symbol, page_width, page_height, rotate_angle)
                        pre = post = ""
                        if symbol.property.detected_break:
                            break_str = unk
                            typ = symbol.property.detected_break.type_
                            if typ == vision.TextAnnotation.DetectedBreak.BreakType.SPACE:
                                break_str = sp
                            elif typ == vision.TextAnnotation.DetectedBreak.BreakType.SURE_SPACE:
                                break_str = sure_sp
                            if symbol.property.detected_break.is_prefix:
                                pre = break_str
                            else:
                                post = break_str
                        sx1 = min(pos[0], pos[2])
                        sy1 = min(pos[1], pos[3])
                        sx2 = max(pos[0], pos[2])
                        sy2 = max(pos[1], pos[3])
                        symbols.append(TextData(sx1, sy1, sx2, sy2, pre + symbol.text + post))
                lines.append(symbols)
        if degrees:
            adjust_angle = int(sum(degrees) / len(degrees))
            if 0 < abs(adjust_angle):
                lines = _rotate_bounds(lines, adjust_angle, center_x, center_y)

        block_lines = _join_bounds(lines)
        page_lines = _sort_bounds(block_lines)
        page_textdatas = _bounds_to_textdata(page_lines)
        textdatas.append(TextDatas(page_no, page_width, page_height, page_textdatas))

    return textdatas


def _get_bounding_degree(word):
    """wordの傾き角度を取得（30度未満のみ有効とする）。"""
    degree = 0
    try:
        x = [v.x for v in word.bounding_box.vertices]
        y = [v.y for v in word.bounding_box.vertices]
        if len(x) == 4 and len(y) == 4:
            tan = 0 if (x[1] - x[0]) == 0 else (y[0] - y[1]) / (x[1] - x[0])
            deg = math.atan(tan) * 180 / math.pi
            if deg and abs(deg) < 30:
                degree = int(deg)
    except Exception:
        logger.exception("OCR結果の傾き角度計算に失敗しました")
    return degree


def _get_rotate_angle(page):
    """ページ全体の回転角度（0/±90/180度のいずれか）を、word内symbolの並び方向の多数決で判定する。"""
    rotate_flgs = [0, 0, 0, 0]
    rotate_angles = [0, -90, 90, 180]
    for block in page.blocks:
        for paragraph in block.paragraphs:
            for word in paragraph.words:
                if word.symbols and 1 < len(word.symbols):
                    s1 = word.symbols[0]
                    x1, y1 = s1.bounding_box.vertices[0].x, s1.bounding_box.vertices[0].y
                    s2 = word.symbols[-1]
                    x2, y2 = s2.bounding_box.vertices[0].x, s2.bounding_box.vertices[0].y
                    if abs(x1 - x2) > abs(y1 - y2):
                        if 0 < x2 - x1:
                            rotate_flgs[0] += 1
                        elif x2 - x1 < 0:
                            rotate_flgs[3] += 1
                    elif abs(x1 - x2) < abs(y1 - y2):
                        if 0 < y2 - y1:
                            rotate_flgs[2] += 1
                        elif y2 - y1 < 0:
                            rotate_flgs[1] += 1
    return rotate_angles[rotate_flgs.index(max(rotate_flgs))]


def _get_pos(symbol, w, h, a):
    """回転角度aに応じて座標データを正立方向に補正する。"""
    v0 = symbol.bounding_box.vertices[0]
    v2 = symbol.bounding_box.vertices[2]
    if a == -90:
        return [h - v0.y, v0.x, h - v2.y, v2.x]
    if a == 90:
        return [v0.y, w - v0.x, v2.y, w - v2.x]
    if a == 180:
        return [w - v0.x, h - v0.y, w - v2.x, h - v2.y]
    return [v0.x, v0.y, v2.x, v2.y]


def _rotate_bounds(lines, angle, cx, cy):
    """微小な傾き（30度未満）を中心点(cx, cy)周りで補正する。"""
    d_rad = math.radians(angle)
    for symbols in lines:
        for symbol in symbols:
            x1, y1 = symbol.x1 - cx, symbol.y1 - cy
            x2, y2 = symbol.x2 - cx, symbol.y2 - cy
            x1r = x1 * math.cos(d_rad) - y1 * math.sin(d_rad)
            y1r = x1 * math.sin(d_rad) + y1 * math.cos(d_rad)
            x2r = x2 * math.cos(d_rad) - y2 * math.sin(d_rad)
            y2r = x2 * math.sin(d_rad) + y2 * math.cos(d_rad)
            symbol.x1, symbol.x2 = int(x1r + cx), int(x2r + cx)
            symbol.y1, symbol.y2 = int(y1r + cy), int(y2r + cy)
    return lines


def _join_bounds(lines):
    """symbolデータをparagraph内で行ごとに連結し、行単位のTextDataにする。"""
    bounds = []
    for symbols in lines:
        strline = ""
        x1 = -1
        x2 = y1 = y2 = 0
        for symbol in symbols:
            if x1 == -1:
                x1, x2, y1, y2 = symbol.x1, symbol.x2, symbol.y1, symbol.y2
            else:
                if symbol.y1 < y1:
                    y1 = symbol.y1
                x2 = symbol.x2
                if y2 < symbol.y2:
                    y2 = symbol.y2
            strline += symbol.text
        if x1 != -1:
            bounds.append(TextData(x1, y1, x2, y2, strline))
    return bounds


def _sort_bounds(bounds):
    """paragraphが異なる行データを、y座標が近いもの同士でまとめてから行内でx座標順に並べる。"""
    lines = []
    bounds = sorted(bounds, key=lambda b: b.y1)
    others = bounds
    while others:
        linebounds, others = _sort_bounds_y(others)
        if linebounds:
            linebounds.sort(key=lambda b: b.x1)
            lines.append(linebounds)
    return lines


def _sort_bounds_y(bounds):
    """y座標が近い（同じ行とみなせる）データを1つの行としてまとめ、残りを返す。"""
    pre_x1 = pre_x2 = pre_y1 = pre_y2 = -1
    first_loop = True
    linebounds = []
    others = []
    for bound in bounds:
        x1, x2, y1, y2 = bound.x1, bound.x2, bound.y1, bound.y2
        if first_loop:
            first_loop = False
            pre_x1, pre_x2, pre_y1, pre_y2 = x1, x2, y1, y2
            linebounds.append(bound)
            continue
        if (pre_y1 < y1 and pre_y2 < y2 and y1 < pre_y2
                and (y1 - pre_y1) * 1.5 < pre_y2 - y1 and (y2 - pre_y2) * 1.5 < pre_y2 - y1):
            linebounds.append(bound)
        elif (y1 < pre_y1 and y2 < pre_y2 and pre_y1 < y2
                and (pre_y1 - y1) * 1.5 < y2 - pre_y1 and (pre_y2 - y2) * 1.5 < y2 - pre_y1):
            linebounds.append(bound)
        elif pre_y1 - _LINE_Y_THRESHOLD <= y1 <= pre_y1 + _LINE_Y_THRESHOLD:
            linebounds.append(bound)
        elif pre_y2 - _LINE_Y_THRESHOLD <= y2 <= pre_y2 + _LINE_Y_THRESHOLD:
            linebounds.append(bound)
        elif pre_y1 <= y1 and y2 <= pre_y2:
            linebounds.append(bound)
        elif y1 <= pre_y1 and pre_y2 <= y2:
            linebounds.append(bound)
        else:
            others.append(bound)
    return linebounds, others


def _bounds_to_textdata(lines):
    """行ごとにまとめたTextDataを1次元のリストに展開する。"""
    return [bound for line in lines for bound in line]


def _get_textlines(textdatas, page_no):
    """TextDatasのリストから、指定ページの行ごとのテキスト文字列リストを組み立てる。

    移植元: jafyame_pj/jafyame_app/jafyame_file.py jf_get_textlines。
    """
    if not textdatas:
        return []
    textlines = []
    for pagedata in textdatas:
        if pagedata.page_no != page_no:
            continue
        pre_y1 = -1
        pre_y2 = -1
        text = ""
        for textdata in pagedata.textdata_list:
            y1, y2 = textdata.y1, textdata.y2
            if pre_y1 == -1:
                pre_y1, pre_y2 = y1, y2
            elif pre_y1 - _LINE_Y_THRESHOLD <= y1 <= pre_y1 + _LINE_Y_THRESHOLD:
                pre_y1, pre_y2 = y1, y2
            else:
                pre_y1, pre_y2 = y1, y2
                textlines.append(text)
                text = ""
            text += textdata.text
        textlines.append(text)
    return textlines
