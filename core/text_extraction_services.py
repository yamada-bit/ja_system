"""PDFのテキスト層抽出（pdfplumber）の共通処理・スキャン文書判定。

pdfplumberによる抽出はOCR（core.ocr_layout_services、Google Cloud Vision）と異なり外部通信を
伴わずローカルで完結するため、次の2箇所から共通で呼び出す：
- documents/contracts.UploadStep2View.post：アップロード直後の同期抽出（本モジュールの
  try_immediate_text_layer_extraction）。画面応答を大きくブロックしない範囲（外部通信なし）で
  全文検索への反映を即時化する。テキスト層が無い（スキャン文書）と判定した場合や解析に
  失敗した場合は何もせず、後続のバッチに処理を委ねる。
- core.management.commands.extract_pending_pdf_text：定期バッチ（5分間隔想定）。
  アップロード直後の同期抽出に失敗・対象外だったレコード（スキャン文書、アップロード時点で
  何らかの理由で抽出できなかった文書）を拾い、テキスト層再判定とOCR振り分けを行う。

is_scanned()は元々core.ocr_services（OCR呼び出し用モジュール）に置いていたが、2026-08-19の
OCR関数統合（core.ocr_layout_servicesへの一本化）でOCR呼び出し側に残す理由が無くなったため、
判定の主な利用者であるこちらへ移設した（extract_pending_pdf_textコマンドもここから読む）。
"""
import logging

import pdfplumber

logger = logging.getLogger(__name__)

# 抽出済みテキスト層の文字数がこの値未満なら「テキスト層が実質無い＝スキャン文書」と判定し、
# OCR（core.ocr_layout_services）に処理を振り分ける（core.management.commands.
# extract_pending_pdf_text参照）。
SCANNED_TEXT_THRESHOLD_CHARS = 10


def is_scanned(text_layer_content):
    """pdfplumber等で抽出したテキスト層の内容から、スキャン文書（画像PDF）かどうかを判定する。"""
    return len((text_layer_content or "").strip()) < SCANNED_TEXT_THRESHOLD_CHARS


def extract_text_layer(obj):
    """objのfile（PDF）からpdfplumberでテキスト層を抽出する。例外はそのまま呼び出し元に伝播させる
    （ファイルI/O・解析エラーの扱いは呼び出し元の用途によって異なるため、ここでは判断しない）。"""
    with obj.file.open("rb") as f, pdfplumber.open(f) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def try_immediate_text_layer_extraction(obj, *, label):
    """アップロード直後の同期抽出エントリポイント。

    テキスト層のあるPDFはその場でextracted_textを確定させ、登録と同時に全文検索の対象にする
    （従来の「バッチが5分間隔で拾うまで対象外」という待ち時間を無くす）。スキャン文書
    （テキスト層が実質無い）や解析失敗時は何もせずextracted_text=""のまま据え置き、
    Google Cloud VisionによるOCR（外部API・処理時間が読めないため同期実行しない）が必要かの
    判定・実行はcore.management.commands.extract_pending_pdf_text（バッチ）に委ねる。

    アップロード処理自体を失敗させないよう、抽出に伴う例外はここで捕捉してログに残すのみとする
    （1件の本文抽出失敗でアップロード自体を失敗にしない設計判断。呼び出し元はobj.save()が
    既に成功した後にこの関数を呼ぶため、失敗してもレコード自体は正常に登録済み）。
    """
    try:
        text = extract_text_layer(obj)
    except Exception:
        # pdfplumberの解析失敗（破損PDF等）・ファイルI/Oエラー等、例外の型は多岐にわたるが、
        # いずれも「今は抽出できなかった」というだけで、次回のバッチポーリングで再試行される
        # ため広くExceptionを捕捉する（extract_pending_pdf_textと同じ設計判断）。
        logger.exception(
            "アップロード直後の本文抽出に失敗しました（バッチでの再試行に委ねます）: model=%s pk=%s",
            label, obj.pk,
        )
        return
    if is_scanned(text):
        # スキャン文書はここでは処理しない（OCR要否の判定・実行はバッチに委ねる）。
        return
    obj.extracted_text = text
    obj.save(update_fields=["extracted_text"])
