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
from django.conf import settings

from core.text_normalization import normalize_for_search

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

    テキスト層のあるPDFはその場で NFKC 正規化して extracted_text_normalized を確定させ、
    text_extracted=True にして、登録と同時に全文検索の対象にする（従来の「バッチが5分間隔で
    拾うまで対象外」という待ち時間を無くす）。生の抽出テキストは保存しない（監査 案1：テキスト層
    抽出は決定的・ローカル・無料で、元ファイルからいつでも再実行できるため）。スキャン文書
    （テキスト層が実質無い）や解析失敗時は何もせず text_extracted=False のまま据え置き、
    Google Cloud VisionによるOCR（外部API・処理時間が読めないため同期実行しない）が必要かの
    判定・実行はcore.management.commands.extract_pending_pdf_text（バッチ）に委ねる。

    アップロード処理自体を失敗させないよう、抽出に伴う例外はここで捕捉してログに残すのみとする
    （1件の本文抽出失敗でアップロード自体を失敗にしない設計判断。呼び出し元はobj.save()が
    既に成功した後にこの関数を呼ぶため、失敗してもレコード自体は正常に登録済み）。
    """
    try:
        if obj.file.size > settings.SYNC_TEXT_EXTRACTION_MAX_BYTES:
            # 大容量PDFはpdfplumberの全ページ解析に数十秒〜数分かかり得て、リクエストのタイム
            # アウト（httpPlatformHandlerのrequestTimeout/LB）に達すると、DBコミット済みのまま
            # 応答が切れて保留ファイルが残り、再送で重複登録になる。同期抽出は見送り、
            # 定期バッチ（text_extracted=Falseのまま据え置き）に委ねる。
            logger.info(
                "大容量のため同期の本文抽出を見送りました（バッチに委ねます）: model=%s pk=%s size=%s",
                label, obj.pk, obj.file.size,
            )
            return
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
    obj.extracted_text_normalized = normalize_for_search(text)
    obj.text_extracted = True
    obj.save(update_fields=["extracted_text_normalized", "text_extracted"])


def try_immediate_text_layer_extraction_batch(objs, *, label):
    """複数レコードの同期抽出を、1リクエスト内の累計サイズ上限
    （settings.SYNC_TEXT_EXTRACTION_MAX_TOTAL_BYTES）付きで順に行う。

    1ファイルごとの上限（try_immediate_text_layer_extraction内）だけでは、閾値以下の
    ファイルを多数まとめて登録した場合に所要時間が合算されて同じタイムアウトを招くため、
    累計がこの上限を超えた分は同期抽出を飛ばしてバッチに委ねる。累計には実際に抽出を試みた
    ファイルのサイズだけを加算する（個別上限で見送られたファイルは加算しない）。
    """
    total = 0
    for obj in objs:
        try:
            size = obj.file.size
        except OSError:
            logger.exception("ファイルサイズを取得できず同期抽出を見送りました: model=%s pk=%s", label, obj.pk)
            continue
        if size > settings.SYNC_TEXT_EXTRACTION_MAX_BYTES:
            # 個別上限超過はtry_immediate_text_layer_extraction側でログを残して見送る。
            try_immediate_text_layer_extraction(obj, label=label)
            continue
        if total + size > settings.SYNC_TEXT_EXTRACTION_MAX_TOTAL_BYTES:
            logger.info(
                "1リクエストの累計上限のため同期の本文抽出を見送りました（バッチに委ねます）: "
                "model=%s pk=%s", label, obj.pk,
            )
            continue
        total += size
        try_immediate_text_layer_extraction(obj, label=label)
