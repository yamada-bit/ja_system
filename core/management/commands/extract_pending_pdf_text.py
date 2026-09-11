"""全文検索基盤：未処理PDFから本文テキストを抽出するバッチコマンド。

Windowsタスクスケジューラから5分間隔で実行する想定。documents/contracts.UploadStep2View.post
がアップロード直後に同期で試みる抽出（core.text_extraction_services.
try_immediate_text_layer_extraction、テキスト層のあるPDFのみ対象）で拾いきれなかったレコード
（text_extracted=False）を、ここで改めてテキスト層抽出→スキャン文書と判定した場合は
Google Cloud VisionによるOCR（core.ocr_layout_services、座標付き抽出、ページ画像分割方式、
ページ数制限なし）へ振り分ける。settings.OCR_ENABLED=Falseの間はOCR自体をスキップし、
text_extracted=False のまま次回以降のポーリングに持ち越す（＝スキャン文書は全文検索対象外）。

抽出結果は NFKC 正規化して extracted_text_normalized にだけ保存し（生テキストは保存しない、
監査 案1）、text_extracted=True にする（結果が空文字列でも「抽出は完了」＝True。旧 ocr_attempted
＋extracted_text=""判定を1フラグに統合、監査 案2）。

OCR時、settings.OCR_STORE_TEXTDATA=True の場合に、Vision から取得した行レイアウト（textdatas）を
ocr_textdata（JSONField）へ保存する。これは検索用PDF（OCRテキスト埋め込み版）を
core.searchable_pdf_services が必要時に生成するための元データ（監査 案3：以前は埋め込み済みPDFを
searchable_file へ恒久保存していたが、桁違いに小さい座標データの保存＋遅延生成に置き換えた）。
当初実装は privacy_flag の影響なし（_should_store_textdata() は常に True）。将来
documents.Document.privacy_flag=True を除外したくなった場合の切替点は _should_store_textdata()
（同メソッドの docstring 参照）。

1件の抽出失敗（破損ファイル・OCR呼び出し失敗等）でバッチ全体を止めない設計とする
（本コマンドは5分間隔で自動的に再実行されるため、失敗したレコードだけ text_extracted=False の
まま次回に持ち越せばよく、他レコードの処理まで巻き込んで止める必要がないため）。
"""
import logging

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import InterfaceError, OperationalError

from contracts.models import Contract
from core import ocr_layout_services
from core.ocr_layout_services import OcrDisabledError
from core.text_extraction_services import extract_text_layer, is_scanned
from core.text_normalization import normalize_for_search
from documents.models import Document

logger = logging.getLogger(__name__)

# (モデル, ログ表示用ラベル) の組。documents/contracts は同じ text_extracted/extracted_text_normalized/
# ocr_textdata の構成のため、抽出ロジック自体は共通化しモデルだけ切り替える。
TARGET_MODELS = [
    (Document, "document"),
    (Contract, "contract"),
]


class Command(BaseCommand):
    help = "未処理PDF（text_extracted=False）から本文テキストを抽出する（全文検索基盤）。"

    def handle(self, *args, **options):
        total_processed = 0
        total_skipped = 0
        total_failed = 0
        for model, label in TARGET_MODELS:
            processed, skipped, failed = self._process_model(model, label)
            total_processed += processed
            total_skipped += skipped
            total_failed += failed
        self.stdout.write(
            f"抽出処理完了: 成功{total_processed}件 / OCR未実行のためスキップ{total_skipped}件 / 失敗{total_failed}件"
        )

    def _process_model(self, model, label):
        # text_extracted=False のレコードだけを対象にする（抽出完了＝空結果でも True になるため、
        # 5分間隔で繰り返し実行しても同じレコードを再処理しない。誤抽出時は運用手順で
        # text_extracted を False に戻す想定）。order_by("pk")で処理順を確定させる（明示的な
        # ordering が無いモデルへの依存を避け、「1件の失敗が他レコードの処理を止めない」ことを
        # テストで再現しやすくするため）。
        queryset = model.objects.filter(text_extracted=False, is_deleted=False).order_by("pk")
        processed = 0
        skipped = 0
        failed = 0
        for obj in queryset:
            try:
                result = self._extract_text(obj, label)
            except Exception:
                # pdfplumberの解析失敗（破損PDF等）・Google Cloud Vision呼び出し失敗
                # （タイムアウト・割当量超過・認証エラー等）は例外の型が多岐にわたり、
                # かつ「1件の失敗でバッチ全体を止めない」ことが本コマンドの存在意義そのもの
                # （5分間隔で自動リトライされる）であるため、意図的に広くExceptionを捕捉する。
                logger.exception("PDF本文抽出に失敗しました: model=%s pk=%s", label, obj.pk)
                failed += 1
                continue
            if result is None:
                # スキャン文書と判定したがOCR_ENABLED=Falseのためスキップした場合。
                # text_extracted=False のまま据え置き、次回ポーリングで再判定する。
                skipped += 1
                continue
            text, textdatas = result
            obj.extracted_text_normalized = normalize_for_search(text)
            obj.text_extracted = True
            update_fields = ["extracted_text_normalized", "text_extracted"]
            if textdatas is not None:
                # OCR経路で、settings.OCR_STORE_TEXTDATA=True かつ _should_store_textdata()=True の
                # ときだけ非None（textdatasのリスト）。検索用PDFの遅延生成用に保存する。
                obj.ocr_textdata = ocr_layout_services.textdatas_to_json(textdatas)
                update_fields.append("ocr_textdata")
            try:
                obj.save(update_fields=update_fields)
            except (OperationalError, InterfaceError):
                # DB接続断・タイムアウト等。「1件の失敗でバッチ全体を止めない」という本コマンドの
                # 設計方針（モジュールdocstring参照）を貫くため、他の失敗系と同様にここも捕捉して
                # ログに残し、後続レコードの処理を継続する。保存が失敗すると text_extracted=False の
                # まま残り、次回バッチで再試行され最終的には整合する（ファイル実体を持たなくなった
                # ため孤立ファイル問題も無い）。
                logger.exception(
                    "PDF本文抽出結果のDB保存に失敗しました: model=%s pk=%s", label, obj.pk,
                )
                failed += 1
                continue
            processed += 1
        return processed, skipped, failed

    def _extract_text(self, obj, label):
        """1件分のテキスト抽出。

        戻り値：
        - None … スキャン文書だが OCR 無効のため未処理（次回に持ち越す）
        - (text, None) … テキスト層抽出成功、または OCR 成功だが textdata を保存しない
          （privacy_flag=True / OCR_STORE_TEXTDATA=False / textdata が空）
        - (text, textdatas) … OCR 成功で textdata も保存する
        """
        try:
            text_layer = extract_text_layer(obj)
        except (FileNotFoundError, OSError):
            logger.exception(
                "本文抽出対象のファイル実体が見つかりません（実行中に削除された可能性）: model=%s pk=%s",
                label, obj.pk,
            )
            raise

        if not is_scanned(text_layer):
            return text_layer, None

        # スキャン文書（テキスト層が実質無い）と判定。
        if not settings.OCR_ENABLED:
            logger.info(
                "スキャン文書と判定しましたがOCR_ENABLED=Falseのため処理をスキップします: model=%s pk=%s",
                label, obj.pk,
            )
            return None
        try:
            with obj.file.open("rb") as f:
                pdf_bytes = f.read()
            text, textdatas = ocr_layout_services.extract_text_and_layout_via_ocr(
                pdf_bytes, source_name=obj.display_name,
            )
        except OcrDisabledError:
            return None
        except Exception:
            logger.exception(
                "Google Cloud Vision OCRに失敗しました（タイムアウト・割当量超過・認証エラー等）: model=%s pk=%s",
                label, obj.pk,
            )
            raise

        store = None
        if settings.OCR_STORE_TEXTDATA and textdatas and self._should_store_textdata(obj):
            store = textdatas
        return text, store

    @staticmethod
    def _should_store_textdata(obj):
        """このレコードの OCR 座標データ（ocr_textdata）を DB へ保存してよいかを判定する。

        **当初実装は privacy_flag の影響なし**（settings.OCR_STORE_TEXTDATA のみに従い、Document /
        Contract を問わず常に保存する。2026-09-11ユーザー方針）。

        将来「個人情報を含む文書（documents.Document.privacy_flag=True）は本文由来の座標データを
        DB へ複製しない」に切り替えたくなったら、下記コメントアウトした1行を有効化するだけでよい
        （contracts.Contract は privacy_flag を持たないため getattr のデフォルト False で常に保存対象）。
        """
        # return not getattr(obj, "privacy_flag", False)
        return True
