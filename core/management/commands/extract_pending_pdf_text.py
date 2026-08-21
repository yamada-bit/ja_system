"""全文検索基盤：未処理PDFから本文テキストを抽出するバッチコマンド。

Windowsタスクスケジューラから5分間隔で実行する想定。documents/contracts.UploadStep2View.post
がアップロード直後に同期で試みる抽出（core.text_extraction_services.
try_immediate_text_layer_extraction、テキスト層のあるPDFのみ対象）で拾いきれなかったレコードを、
ここで改めてテキスト層抽出→スキャン文書と判定した場合はGoogle Cloud VisionによるOCR
（core.ocr_layout_services、座標付き抽出、ページ画像分割方式、ページ数制限なし）へ振り分ける。
settings.OCR_ENABLED=Falseの間はOCR自体をスキップし、extracted_textを空のまま次回以降の
ポーリングに持ち越す（＝スキャン文書は全文検索対象に含まれない）。

OCR自体は常に座標付き抽出（core.ocr_layout_services.extract_text_and_layout_via_ocr）を使う
（2026-08-19、座標を使わない単純版core.ocr_services.extract_text_via_ocrは大部分がこちらと
重複していたため統合・削除した）。settings.OCR_EMBED_TEXT_TO_PDF=Trueかつ_should_embed()が
Trueを返す場合のみ、取得した座標データを使ってOCR結果を透明テキストとして埋め込んだ検索用PDF
（documents.Document/contracts.Contractのsearchable_file）を追加生成する
（core.pdf_text_embed_services、原本のfileフィールドは変更しない）。_should_embed()は
documents.Document.privacy_flag（個人情報が含まれる）がTrueのレコードを埋め込み対象から除外する
（個人情報を検索用PDFに透明テキストとして複製しないための判断、2026-08-19ユーザー指示）。
privacy_flag自体を持たないcontracts.Contractはこの個別判定を行わず、settings.
OCR_EMBED_TEXT_TO_PDFのみに従う（Contractには個人情報フラグの概念が無い設計のため、
CLAUDE.md／contracts/models.py参照）。

1件の抽出失敗（破損ファイル・OCR呼び出し失敗等）でバッチ全体を止めない設計とする
（本コマンドは5分間隔で自動的に再実行されるため、失敗したレコードだけextracted_textを
空のまま次回に持ち越せばよく、他レコードの処理まで巻き込んで止める必要がないため）。
"""
import logging

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import InterfaceError, OperationalError

from contracts.models import Contract
from core import ocr_layout_services, pdf_text_embed_services
from core.ocr_layout_services import OcrDisabledError
from core.text_extraction_services import extract_text_layer, is_scanned
from documents.models import Document

logger = logging.getLogger(__name__)

# (モデル, ログ表示用ラベル) の組。documents/contracts は同じextracted_text/ocr_attemptedの
# 構成のため、抽出ロジック自体は共通化しモデルだけ切り替える。
TARGET_MODELS = [
    (Document, "document"),
    (Contract, "contract"),
]


class Command(BaseCommand):
    help = "未処理PDF（extracted_textが空）から本文テキストを抽出する（全文検索基盤）。"

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
        # 一度抽出済み（extracted_text != ""）のレコードは対象外にすることで、5分間隔で
        # 繰り返し実行しても同じレコードを再処理しない。誤抽出・OCR誤認識時の再実行が必要な場合は
        # 運用手順でextracted_textを空に戻してから行う想定。
        # ocr_attempted=Falseも条件に加えるのは、OCRを実行した結果が本当に空文字列だった場合
        # （画像に文字が全く無い等）に、extracted_text=""のままでは毎回スキャン文書と判定され
        # 無限にOCRが再実行されてしまうのを防ぐため（Document.ocr_attemptedのフィールド
        # コメント参照）。
        # order_by("pk")で処理順を確定させる（明示的なorderingが無いモデルへの依存を避け、
        # 「1件の失敗が他レコードの処理を止めない」ことをテストで再現しやすくするため）。
        queryset = model.objects.filter(
            extracted_text="", ocr_attempted=False, is_deleted=False
        ).order_by("pk")
        processed = 0
        skipped = 0
        failed = 0
        for obj in queryset:
            try:
                text = self._extract_text(obj, label)
            except Exception:
                # pdfplumberの解析失敗（破損PDF等）・Google Cloud Vision呼び出し失敗
                # （タイムアウト・割当量超過・認証エラー等）は例外の型が多岐にわたり、
                # かつ「1件の失敗でバッチ全体を止めない」ことが本コマンドの存在意義そのもの
                # （5分間隔で自動リトライされる）であるため、意図的に広くExceptionを捕捉する。
                logger.exception("PDF本文抽出に失敗しました: model=%s pk=%s", label, obj.pk)
                failed += 1
                continue
            if text is None:
                # スキャン文書と判定したがOCR_ENABLED=Falseのためスキップした場合。
                # extracted_text=""のまま据え置き、次回ポーリングで再判定する。
                skipped += 1
                continue
            update_fields = ["extracted_text"]
            obj.extracted_text = text
            if obj.searchable_file:
                # settings.OCR_EMBED_TEXT_TO_PDF=Trueかつ_should_embed(obj)がTrueで
                # _extract_text_via_ocrがsearchable_file.save(..., save=False)によりステージ済み
                # （DB未反映）の場合のみupdate_fieldsに加える。他レコードでは常にnull（既定）のため
                # falsy。
                update_fields.append("searchable_file")
            if obj.ocr_attempted:
                # _extract_textがOCRを実行完了した場合のみTrueにセット済み（テキスト層抽出だけで
                # 済んだ場合やOCR自体をスキップした場合はFalseのまま）。
                update_fields.append("ocr_attempted")
            try:
                obj.save(update_fields=update_fields)
            except (OperationalError, InterfaceError):
                # DB接続断・タイムアウト等。「1件の失敗でバッチ全体を止めない」という本コマンドの
                # 設計方針（モジュールdocstring参照）を貫くため、他の失敗系と同様にここも捕捉して
                # ログに残し、後続レコードの処理を継続する。settings.OCR_EMBED_TEXT_TO_PDF=True
                # 使用時、searchable_fileは_extract_text_via_ocr内のsearchable_file.save
                # (..., save=False)で既にストレージへ書き込み済み（save=FalseはDB反映のみ
                # スキップする設計）のため、ここで保存が失敗するとDBには反映されずファイルだけが
                # 孤立する。次回バッチではocr_attempted=Falseのまま再試行され最終的には整合するが、
                # 孤立した旧ファイル自体の掃除は別問題として残る（cleanup対象外）。
                logger.exception(
                    "PDF本文抽出結果のDB保存に失敗しました: model=%s pk=%s", label, obj.pk,
                )
                failed += 1
                continue
            processed += 1
        return processed, skipped, failed

    def _extract_text(self, obj, label):
        """1件分のテキスト抽出。戻り値がNoneなら「スキャン文書だがOCR無効のため未処理」を表す。

        OCRを実行完了した場合、obj.ocr_attempted をTrueにセットする（DBへの反映は呼び出し元
        _process_modelがまとめて行う）。OCR結果が空文字列でもocr_attemptedがTrueになっていれば
        次回バッチの対象から外れ、無限リトライを防げる。例外発生時（一時的なAPIエラー等、
        再試行させたいケース）やOCR自体をスキップした場合はセットしない。
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
            return text_layer

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
            text = self._extract_text_via_ocr(obj, label, pdf_bytes)
            obj.ocr_attempted = True
            return text
        except OcrDisabledError:
            return None
        except Exception:
            logger.exception(
                "Google Cloud Vision OCRに失敗しました（タイムアウト・割当量超過・認証エラー等）: model=%s pk=%s",
                label, obj.pk,
            )
            raise

    def _extract_text_via_ocr(self, obj, label, pdf_bytes):
        """座標付き抽出（core.ocr_layout_services）でOCR本文を取得する。座標データは
        settings.OCR_EMBED_TEXT_TO_PDF=Trueかつ_should_embed(obj)がTrueの場合のみ、続けて
        PDFへの透明テキスト埋め込み（core.pdf_text_embed_services）に使う。埋め込みは全文検索の
        本体（extracted_textの保存）に対する付加機能という位置付けのため、失敗してもテキスト抽出
        自体は成功させる（ログのみ残し、searchable_fileは未設定＝nullのまま次回以降のバッチでも
        再試行されない。全文検索自体はextracted_textが埋まっていれば機能するため実害は無い）。"""
        text, textdatas = ocr_layout_services.extract_text_and_layout_via_ocr(
            pdf_bytes, source_name=obj.display_name,
        )
        if settings.OCR_EMBED_TEXT_TO_PDF and textdatas and self._should_embed(obj):
            try:
                embedded_bytes = pdf_text_embed_services.embed_textdatas_into_pdf(pdf_bytes, textdatas)
                obj.searchable_file.save(obj.display_name, ContentFile(embedded_bytes), save=False)
            except Exception:
                logger.exception(
                    "OCRテキストのPDF埋め込みに失敗しました（テキスト抽出自体は継続します）: model=%s pk=%s",
                    label, obj.pk,
                )
        return text

    @staticmethod
    def _should_embed(obj):
        """このレコードにPDF埋め込み（透明テキスト貼り付け）を行ってよいかを判定する。

        documents.Document.privacy_flag（個人情報が含まれる）がTrueのレコードは、検索用PDFへ
        個人情報を複製することになるため埋め込み対象から除外する。privacy_flag自体を持たない
        モデル（contracts.Contractには個人情報フラグの概念が無い、CLAUDE.md参照）は、この
        個別判定を行わずsettings.OCR_EMBED_TEXT_TO_PDFのみに従って埋め込む（2026-08-19追加）。
        """
        return not getattr(obj, "privacy_flag", False)
