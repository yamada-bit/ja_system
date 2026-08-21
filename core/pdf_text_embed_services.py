"""core.ocr_layout_servicesの結果（座標付きOCRテキスト）を透明テキストとしてPDFに埋め込む処理。

settings.OCR_EMBED_TEXT_TO_PDF が True の間のみ、extract_pending_pdf_textコマンドから呼ばれる。
埋め込んでも原本（documents.Document/contracts.Contractのfileフィールド）は変更しない：
戻り値の新しいPDFバイト列は呼び出し元がsearchable_fieldへ別ファイルとして保存する
（監査・原本性の観点。原本を差し替えない設計はユーザー確認済み）。

reportlab/pypdfはローカル完結（外部通信・認証情報チェック不要）のため、
core.ocr_layout_services（google-cloud-vision・pdf2image）と異なり遅延importにしていない。

移植元: C:\\Users\\yamad\\Claude\\Code\\jafyame_pj（分割アップロード＋OCR＋PDF埋め込みに特化した
別プロジェクト）の jafyame_app/pdf_merge_text.py merge_textdatas_pdf。ファイルパス入出力だった
ものをbytes入出力に変更した（Django側でFileField/ContentFileとして扱いやすくするため）。
"""
import io
import logging

from pypdf import PdfReader, PdfWriter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

logger = logging.getLogger(__name__)

# reportlabにデフォルトで組み込まれている日本語CIDフォント（追加のフォントファイル不要）。
FONT_NAME = "HeiseiKakuGo-W5"
if FONT_NAME not in pdfmetrics.getRegisteredFontNames():
    pdfmetrics.registerFont(UnicodeCIDFont(FONT_NAME))


def embed_textdatas_into_pdf(pdf_bytes, textdatas):
    """pdf_bytesの各ページに、textdatas（core.ocr_layout_services.TextDatasのリスト）の
    座標に合わせて透明テキストを重ね書きした新しいPDFのバイト列を返す。

    1ページの埋め込み処理に失敗しても、そのページは透明テキスト無しの原本ページのまま出力し、
    他ページの処理は継続する（1ページの失敗で埋め込み処理全体を失敗させない。
    extract_pending_pdf_textコマンド側でもこの関数自体の失敗は「埋め込みは失敗したが
    テキスト抽出〈extracted_text〉は成功させる」という扱いで、本質的でない処理として
    握りつぶす設計になっている）。
    """
    pdf_reader = PdfReader(io.BytesIO(pdf_bytes))
    pdf_writer = PdfWriter()

    textdatas_by_page = {pagedata.page_no: pagedata for pagedata in textdatas}

    for page_num, page in enumerate(pdf_reader.pages):
        page_no = page_num + 1
        pagedata = textdatas_by_page.get(page_no)
        if pagedata and pagedata.textdata_list:
            try:
                _overlay_transparent_text(page, pagedata)
            except Exception:
                logger.exception(
                    "OCRテキストのPDF埋め込みでページの処理に失敗しました"
                    "（このページは透明テキスト無しで出力します）: page=%s", page_no,
                )
        pdf_writer.add_page(page)

    output = io.BytesIO()
    pdf_writer.write(output)
    pdf_writer.close()
    return output.getvalue()


def _overlay_transparent_text(page, pagedata):
    """1ページ分の透明テキストレイヤーを作成し、page（pypdfのPageObject）にマージする
    （page自体がin-placeで更新される）。"""
    width = round(page.mediabox.width)
    height = round(page.mediabox.height)
    page_width = pagedata.page_width
    page_height = pagedata.page_height
    if not page_width or not page_height:
        return
    # OCR時のページ画像サイズ(page_width/page_height)とPDFページサイズ(width/height)の比率。
    # 座標データはページ画像のピクセル座標系で作られているため、PDF座標系へスケール変換する。
    scale_x = width / page_width
    scale_y = height / page_height

    packet = io.BytesIO()
    pdf_canvas = canvas.Canvas(packet, pagesize=(width, height))
    pdf_canvas.setFillColorRGB(1, 1, 1, alpha=0)  # 透明（コピー・検索は可能、表示はされない）
    for textdata in pagedata.textdata_list:
        x = textdata.x1 * scale_x
        # PDF座標系は左下原点、OCR座標系は左上原点のため上下反転する。
        y = height - textdata.y2 * scale_y
        # バウンディングボックスの高さをフォントサイズとして使う（移植元と同じ簡易的な方式）。
        font_size = max(1, round((textdata.y2 - textdata.y1) * scale_y))
        pdf_canvas.setFont(FONT_NAME, font_size)
        pdf_canvas.drawString(int(x), int(y), textdata.text)
    pdf_canvas.save()

    packet.seek(0)
    overlay_pdf = PdfReader(packet)
    page.merge_page(overlay_pdf.pages[0])
