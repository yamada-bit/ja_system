"""検索用PDF（OCRテキスト埋め込み版）の遅延生成。

documents.Document / contracts.Contract の `ocr_textdata`（OCR 行レイアウト、
core.ocr_layout_services.textdatas_to_json 形式）が保存されているスキャン文書について、
利用者がダウンロードを要求した時点で、原本PDF＋座標データからその場で透明テキストを
埋め込んだPDFを組み立てて返す（2026-09-11、監査 案3）。

以前は extract_pending_pdf_text バッチが埋め込み済みPDFを事前生成して searchable_file
（FileField）へ恒久保存していたが、スキャン文書1件あたり原本と同等サイズ（数十〜数百MB）の
PDFをもう1本持つことになり容量負荷が大きかった。座標データ（JSON、圧縮後1〜4MB）だけを
保存し、桁違いに軽い埋め込み処理（1000ページで数秒）を都度実行する方式に変えた。
"""
import logging

from core import ocr_layout_services, pdf_text_embed_services

logger = logging.getLogger(__name__)


class SearchablePdfUnavailable(Exception):
    """対象レコードに ocr_textdata が無く、検索用PDFを生成できない。"""


def build_searchable_pdf(obj):
    """obj（Document/Contract）の原本PDFに、保存済み ocr_textdata の透明テキストを重ねた
    新しいPDFのバイト列を返す。

    ocr_textdata が None/空（テキスト層PDF、settings.OCR_STORE_TEXTDATA=False でOCRされた
    スキャン文書、OCR前）の場合は SearchablePdfUnavailable を送出する。
    ファイル実体の取得失敗（OSError）は呼び出し元でハンドリングさせるためそのまま伝播させる。
    """
    if not obj.ocr_textdata:
        raise SearchablePdfUnavailable("この文書には検索用PDFを生成できる座標データがありません。")
    textdatas = ocr_layout_services.textdatas_from_json(obj.ocr_textdata)
    with obj.file.open("rb") as f:
        pdf_bytes = f.read()
    return pdf_text_embed_services.embed_textdatas_into_pdf(pdf_bytes, textdatas)
