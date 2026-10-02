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
import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import InterfaceError, OperationalError

from contracts.models import Contract
from core import ocr_checkpoint_services, ocr_layout_services
from core.ocr_layout_services import (
    OcrDisabledError, OcrRetryWaitTimeLimitError, OcrTimeLimitError, OcrVisionUnavailableError,
)
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

    def add_arguments(self, parser):
        # 通常（5分間隔）と大容量（夜間）の2本のタスクに、ファイルサイズで担当を分けるための
        # オプション。--max-bytesは「以下」、--larger-than-bytesは「超」なので、同じ値を指定すれば
        # 担当が重複も漏れもなく分かれる（同じ文書を2本が二重にOCRしない）。どちらも未指定なら
        # 全件が対象（従来の動作）。
        parser.add_argument(
            "--max-bytes", type=int, default=None,
            help="このバイト数以下のファイルだけを対象にする（通常タスク用）。",
        )
        parser.add_argument(
            "--larger-than-bytes", type=int, default=None,
            help="このバイト数を超えるファイルだけを対象にする（大容量タスク用）。",
        )
        parser.add_argument(
            "--time-limit", type=int, default=None,
            help="1回の実行に使える秒数。未指定ならsettings.OCR_BATCH_TIME_LIMIT_SECONDS。"
                 "大容量タスクでは、タスクスケジューラの実行時間制限より短い値を指定する。",
        )

    def handle(self, *args, **options):
        total_processed = 0
        total_skipped = 0
        total_failed = 0
        total_deferred = 0
        total_backoff = 0
        # 1回の実行に使える時間の上限（既定はsettings.OCR_BATCH_TIME_LIMIT_SECONDS、--time-limitで
        # 上書き）。タスクスケジューラの実行時間制限（register_scheduled_tasks.ps1の
        # $ExtractTimeLimit、30分）に強制終了される前に、自分で区切って終えるためのもの。
        time_limit = options.get("time_limit") or settings.OCR_BATCH_TIME_LIMIT_SECONDS
        max_bytes = options.get("max_bytes")
        larger_than_bytes = options.get("larger_than_bytes")
        deadline = time.monotonic() + time_limit

        # documents/contractsをまたいで、ファイルサイズの小さい順に処理する。pk順だと、数百ページの
        # 大容量スキャンPDFが先頭に居座った場合、実行時間制限で毎回その1件の途中で打ち切られ、
        # 後ろの小さな文書が永久に処理されない（飢餓状態）ため。大きいものは最後に回り、
        # 他に処理すべきものが無い回に（その回の全時間を使って）処理される。
        targets = []
        for model, label in TARGET_MODELS:
            # 並べ替えに要るのはpkとファイルサイズだけなので、本文（extracted_text_normalized）・
            # 座標データ（ocr_textdata）等の大きい列は読まない。未処理が数千件溜まった状態でも
            # メモリを圧迫しないため。処理する直前に1件ずつ全列を取り直す（下のループ）。
            pending = model.objects.filter(text_extracted=False, is_deleted=False).only("pk", "file")
            for obj in pending.order_by("pk").iterator(chunk_size=500):
                size = self._file_size(obj)
                if max_bytes is not None and size > max_bytes:
                    continue
                if larger_than_bytes is not None and size <= larger_than_bytes:
                    continue
                # 前回OCRに失敗して再試行間隔（バックオフ）の途中の文書は、今回は触らない。Visionの
                # 障害・割当量超過中に同じ文書を5分ごとに叩いて課金・割当量を浪費しないため。
                if ocr_checkpoint_services.is_in_backoff(label, obj.pk):
                    total_backoff += 1
                    continue
                targets.append((size, label, model, obj.pk))
        targets.sort(key=lambda t: t[0])

        for index, (_size, label, model, pk) in enumerate(targets):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                total_deferred = len(targets) - index
                logger.warning(
                    "実行時間の上限（%s秒）に達したため残り%s件の処理を次回に持ち越します",
                    time_limit, total_deferred,
                )
                break
            # 一覧を作ってからここへ来るまでに、削除された・別のプロセスが先に処理を終えた文書は飛ばす
            # （処理済みの文書を二重にOCRして課金・上書きしないための再確認も兼ねる）。
            obj = model.objects.filter(pk=pk, text_extracted=False, is_deleted=False).first()
            if obj is None:
                continue
            # 先頭の1件目（＝この実行で使える時間をまだ全く消費していない）でも制限時間内に
            # 終わらなかった場合は、何度実行しても完了しない大きさの文書。ログで運用者に伝える。
            is_first = index == 0
            outcome = self._process_one(obj, label, remaining, is_first, time_limit)
            if outcome == "processed":
                total_processed += 1
            elif outcome == "skipped":
                total_skipped += 1
            elif outcome == "deferred":
                total_deferred += 1
            elif outcome == "vision_unavailable":
                # Vision側（割当量超過・障害・認証エラー等）の失敗は他の文書でも同じ理由で起こりやすい。
                # 残りへ進むと、失敗する呼び出しを重ねて割当量を食うだけなので、この実行はここで打ち切る
                # （失敗した文書自体は以後バックオフで間隔を空けるため、毎回先頭で止まり続けることは無い）。
                total_failed += 1
                total_deferred += len(targets) - index - 1
                logger.warning(
                    "Vision API側の失敗のため、この実行を打ち切ります（残り%s件は次回に持ち越し）",
                    len(targets) - index - 1,
                )
                break
            else:
                total_failed += 1
        self.stdout.write(
            f"抽出処理完了: 成功{total_processed}件 / OCR未実行のためスキップ{total_skipped}件 / "
            f"失敗{total_failed}件 / 時間切れで持ち越し{total_deferred}件 / "
            f"OCR失敗後の待機中{total_backoff}件"
        )

    @staticmethod
    def _file_size(obj):
        """処理順を決めるためのファイルサイズ。取得できない（実体欠損等）場合は0として先頭に
        回し、失敗を早く確定させて他レコードの時間を食わないようにする（失敗自体は
        _extract_textが改めてログに残す）。"""
        try:
            return obj.file.size
        except OSError:
            return 0

    def _process_one(self, obj, label, remaining_seconds, is_first, time_limit):
        """1件分の抽出と保存。戻り値は "processed" / "skipped" / "deferred" / "failed" /
        "vision_unavailable"（Vision API側の失敗。呼び出し元はこの実行を打ち切る）。"""
        try:
            result = self._extract_text(obj, label, remaining_seconds)
        except OcrRetryWaitTimeLimitError:
            # Vision側の一時的なエラーで、やり直しの待ちが残り時間に収まらなかった場合。文書の大きさ
            # が原因ではないので、「完了しない大きさ」のエラーログ（下）にはしない。
            logger.warning(
                "Vision APIが一時的なエラーを返し、やり直しの待ちが残り時間に収まらないため"
                "次回に持ち越します: model=%s pk=%s", label, obj.pk,
            )
            return "deferred"
        except OcrTimeLimitError:
            if is_first:
                # 済んだページはチェックポイントに残るので、次回以降は続きから進み、何回かの実行で
                # 完了する（従来は毎回1ページ目からやり直すため完了しなかった）。ただし1回の実行で
                # 何ページも進まないほど遅い場合は設定の見直しが要るため、警告で知らせる。
                logger.warning(
                    "OCRが1回の実行時間の上限（%s秒）内に終わらなかったため、済んだページを保存して"
                    "次回以降に続きから処理します（何度も続く場合は--time-limit/"
                    "OCR_BATCH_TIME_LIMIT_SECONDSとタスクの実行時間制限の見直し、またはPDFの分割を"
                    "検討してください）: model=%s pk=%s",
                    time_limit, label, obj.pk,
                )
            else:
                logger.warning(
                    "OCRが残り時間内に終わらなかったため次回に持ち越します: model=%s pk=%s", label, obj.pk
                )
            return "deferred"
        except OcrVisionUnavailableError:
            # 失敗の記録（バックオフ）とログは_extract_text側で済んでいる。
            return "vision_unavailable"
        except Exception:
            # pdfplumberの解析失敗（破損PDF等）・Google Cloud Vision呼び出し失敗
            # （タイムアウト・割当量超過・認証エラー等）は例外の型が多岐にわたり、
            # かつ「1件の失敗でバッチ全体を止めない」ことが本コマンドの存在意義そのもの
            # （5分間隔で自動リトライされる）であるため、意図的に広くExceptionを捕捉する。
            logger.exception("PDF本文抽出に失敗しました: model=%s pk=%s", label, obj.pk)
            return "failed"
        if result is None:
            # スキャン文書と判定したがOCR_ENABLED=Falseのためスキップした場合。
            # text_extracted=False のまま据え置き、次回ポーリングで再判定する。
            return "skipped"
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
            return "failed"
        # DBへの保存まで成功してはじめてOCRの途中経過（チェックポイント）を捨てる。保存前に消すと、
        # 保存に失敗したとき次回また全ページをOCRし直すことになる。
        ocr_checkpoint_services.clear(label, obj.pk)
        return "processed"

    def _extract_text(self, obj, label, remaining_seconds=None):
        """1件分のテキスト抽出。

        戻り値：
        - None … スキャン文書だが OCR 無効のため未処理（次回に持ち越す）
        - (text, None) … テキスト層抽出成功、または OCR 成功だが textdata を保存しない
          （OCR_STORE_TEXTDATA=False / textdata が空。_should_store_textdata参照、
          2026-09-11時点ではprivacy_flagの影響は無い）
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
        checkpoint = None
        try:
            with obj.file.open("rb") as f:
                pdf_bytes = f.read()
            # 前回までに済んだページの結果を読み込み、それらはVisionへ再送しない（課金・割当量の節約）。
            checkpoint = ocr_checkpoint_services.OcrCheckpoint.load(label, obj.pk, pdf_bytes)
            text, textdatas = ocr_layout_services.extract_text_and_layout_via_ocr(
                pdf_bytes, source_name=obj.display_name, max_seconds=remaining_seconds,
                completed_pages=checkpoint.completed_pages, on_page_done=checkpoint.save_page,
            )
        except OcrDisabledError:
            return None
        except OcrTimeLimitError:
            # 時間切れは失敗ではなく「次回に持ち越し」（_process_oneが専用のログを出す）。下の
            # 汎用の失敗ログ（ERROR＋スタックトレース）に流すと、運用者が障害と取り違える。
            # 済んだページはon_page_doneで保存済みで、失敗回数にも数えない（バックオフもしない）。
            raise
        except Exception:
            logger.exception(
                "Google Cloud Vision OCRに失敗しました（タイムアウト・割当量超過・認証エラー等）: model=%s pk=%s",
                label, obj.pk,
            )
            if checkpoint is not None:
                # 次に試してよい時刻を後ろへ延ばす（指数バックオフ）。ファイル読み込み自体の失敗
                # （checkpointが未作成）は文書側の問題で、OCR再試行の間隔制御の対象外。
                attempts, wait = checkpoint.record_failure()
                if attempts >= settings.OCR_FAILURE_ALERT_ATTEMPTS:
                    logger.error(
                        "OCRが%s回続けて失敗しています。運用者の確認が必要です（Vision側の障害・割当量・"
                        "認証、または文書自体の問題）: model=%s pk=%s",
                        attempts, label, obj.pk,
                    )
                logger.warning(
                    "OCR失敗のため、この文書は%s分後まで再試行しません: model=%s pk=%s",
                    wait // 60, label, obj.pk,
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
