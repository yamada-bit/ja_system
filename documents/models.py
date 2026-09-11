import logging

from django.contrib.postgres.indexes import GinIndex
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

# 西暦年の健全性チェック（監査 B-VAL-3）。フォームは choices（直近年±数年）で絞るが、admin・
# 一括編集・将来コードの直接 save が 0 や5桁の異常値を通さないための多層防御。2200 は最長の
# 保存期間でも十分な上限。
_YEAR_VALIDATORS = [MinValueValidator(1900), MaxValueValidator(2200)]

from core.models import NormalizedTextFieldsMixin, UuidPrefixedFilenameMixin
from core.upload_validation import validate_no_active_content
from documents.storage_paths import document_upload_path

logger = logging.getLogger(__name__)


class Document(NormalizedTextFieldsMixin, UuidPrefixedFilenameMixin, models.Model):
    """文書（screen-storage2/screen-search「文書」モード、screen-storage1経由でアップロード）。

    保管画面のフォーム項目にそのまま対応する。`extracted_text_normalized` は screen-search の
    「フリーワード」欄がファイル本文に対する全文検索も行う前提（2026-08-07ユーザー指示）で追加した。
    旧ja_pj_oldでは本番DBのLC_CTYPE=Cが原因でpg_trgmが日本語トライグラムを生成できず、全文検索が
    実質`icontains`単純部分一致にフォールバックしていたが、新ja_db（`Japanese_Japan.utf8`ロケールで
    作成）ではpg_trgmが日本語で正しく機能することを確認済みのため、GinIndex(gin_trgm_ops)による
    類似検索を前提にできる。実際のPDF本文抽出処理は登録直後の同期抽出
    （core.text_extraction_services.try_immediate_text_layer_extraction、テキスト層のある
    PDFのみ対象）と、定期バッチ（core.management.commands.extract_pending_pdf_text、
    テキスト層の無いスキャン文書はGoogle Cloud VisionでOCR）の2段階で行う（2026-08-10追加）。
    生の抽出テキストは保存せず、NFKC 正規化した `extracted_text_normalized` のみ持つ
    （監査 案1、2026-09-11。テキスト層抽出は元ファイルから決定的に再実行でき、OCR 結果は
    `ocr_textdata` から再導出できるため）。
    """

    title = models.CharField("文書タイトル", max_length=255)
    department = models.ForeignKey(
        "organizations.Department",
        verbose_name="保管先部署",
        on_delete=models.PROTECT,
        related_name="documents",
    )
    group = models.ForeignKey(
        "masters.Group", verbose_name="分類", on_delete=models.PROTECT, related_name="documents"
    )
    category = models.ForeignKey(
        "masters.Category",
        verbose_name="カテゴリー",
        on_delete=models.PROTECT,
        related_name="documents",
    )
    year = models.PositiveIntegerField("年", validators=_YEAR_VALIDATORS)
    retention_period = models.ForeignKey(
        "masters.RetentionPeriod",
        verbose_name="保存期間",
        on_delete=models.PROTECT,
        related_name="documents",
    )
    expiry_date = models.DateField(
        "保存満了日",
        db_index=True,  # メイン画面お知らせ集計・検索「保存満了日」範囲/ソートで常用（監査 B-IDX-3）
        help_text=(
            "保存日+保存期間から算出して保存する（メイン画面お知らせの「有効期限切れ」"
            "「有効期限切れまでXヶ月以内」抽出で検索条件として使うため、都度計算せず保持する）"
        ),
    )
    privacy_flag = models.BooleanField("個人情報が含まれる", default=True)
    memo = models.TextField("メモ", blank=True, default="")
    file = models.FileField(
        "ファイル", upload_to=document_upload_path, validators=[validate_no_active_content]
    )
    # title/memo の検索用シャドウカラム（save()で自動生成、editable=False）。半角全角を問わず
    # 検索できるようにするため（簡易設計指示書の検索要件、core.text_normalization.
    # normalize_for_search参照）、NFKC正規化した値を保存し、検索時はキーワード側も同じ正規化を
    # した上でこのカラムに icontains する。CharField(255)で導入していたが、NFKC正規化は文字数を
    # 増やし得る（互換文字1字が複数字に展開される）ため TextField にして上限を撤廃済み
    # （品質レビューで発見、2026-08-25修正）。verbose_name は付けない（editable=False の検索用
    # 内部列で UI・admin に出ないため。監査 C-1/Q-3）。
    title_normalized = models.TextField(blank=True, default="", editable=False)
    memo_normalized = models.TextField(blank=True, default="", editable=False)
    # ファイル本文の全文検索用シャドウカラム（フリーワード検索の対象、2026-08-07ユーザー指示）。
    # 生の抽出テキストは保存しない（監査 案1、2026-09-11）。テキスト層PDFは pdfplumber 抽出結果を、
    # スキャン文書は OCR 結果を NFKC 正規化してこの列だけに保存する。populate は
    # NormalizedTextFieldsMixin ではなく抽出サービス（core.text_extraction_services /
    # core.management.commands.extract_pending_pdf_text）が直接行う。
    extracted_text_normalized = models.TextField(blank=True, default="", editable=False)
    text_extracted = models.BooleanField(
        "本文抽出済み",
        default=False,
        db_index=True,
        help_text=(
            "テキスト層抽出または OCR による本文抽出が完了したら True（結果が空文字列でも完了は完了）。"
            "core.management.commands.extract_pending_pdf_text は False のレコードだけを対象にする。"
            "誤OCR等で再抽出させたい場合は運用手順で False に戻す（監査 案2、2026-09-11。旧 ocr_attempted"
            "＋extracted_text=\"\" 判定を1フラグに統合）。"
        ),
    )
    ocr_textdata = models.JSONField(
        "OCR座標データ",
        null=True,
        blank=True,
        editable=False,
        help_text=(
            "スキャン文書の OCR 行レイアウト（core.ocr_layout_services.textdatas_to_json 形式）。"
            "検索用PDF（OCRテキスト埋め込み版）を core.searchable_pdf_services が必要時に生成するための"
            "元データ。settings.OCR_STORE_TEXTDATA=True のスキャン文書で保存する（当初実装は "
            "privacy_flag の影響なし。将来 privacy_flag=True を除外したくなった場合の切替点は "
            "core.management.commands.extract_pending_pdf_text.Command._should_store_textdata）。"
            "テキスト層PDF・OCR前・OCR_STORE_TEXTDATA=False の文書は null（監査 案3、2026-09-11。"
            "旧 searchable_file〈埋め込み済みPDFの恒久保存〉を、桁違いに小さい座標データの保存＋"
            "遅延生成に置き換えた）。"
        ),
    )

    # 一覧の初期ソート（保存日 降順）＋期間検索（save_date__date 範囲）で常用（監査 B-IDX-4）。
    save_date = models.DateTimeField("保存日", auto_now_add=True, db_index=True)
    uploader = models.ForeignKey(
        "accounts.Employee",
        verbose_name="保管・更新者",
        on_delete=models.PROTECT,
        related_name="uploaded_documents",
    )
    updated_at = models.DateTimeField("更新日時", auto_now=True)

    is_deleted = models.BooleanField("削除済み", default=False)
    deleted_at = models.DateTimeField("削除日", null=True, blank=True)

    class Meta:
        db_table = "t_document"
        verbose_name = "文書"
        verbose_name_plural = "文書"
        indexes = [
            # フリーワード全文検索（core.search_services.apply_freeword_filter）は
            # title_normalized / memo_normalized / extracted_text_normalized の3列を OR で icontains、
            # タイトル検索（apply_word_filter）は title_normalized を icontains する。いずれも正規化
            # シャドウ列に対してのみ検索するため、GIN(gin_trgm_ops) も正規化列3本に揃えて張る
            # （監査 B-IDX-1 / B-IDX-2。生 extracted_text カラム自体は 2026-09-11 に廃止、案1）。
            GinIndex(fields=["title_normalized"], name="doc_title_norm_trgm", opclasses=["gin_trgm_ops"]),
            GinIndex(fields=["memo_normalized"], name="doc_memo_norm_trgm", opclasses=["gin_trgm_ops"]),
            GinIndex(
                fields=["extracted_text_normalized"],
                name="doc_extracted_text_norm_trgm",
                opclasses=["gin_trgm_ops"],
            ),
            # 削除済み行だけの部分索引（監査 B-IDX-5）。ゴミ箱一覧（filter(is_deleted=True)）と
            # 日次バッチ purge_expired_deleted_records（is_deleted=True かつ deleted_at 範囲）で使う。
            # メイン画面お知らせの recently_deleted は条件付き集約（1スキャン3件数）で索引を使わないため
            # 対象外。生 is_deleted 単独 btree は低選択性で使われないので張らない。
            models.Index(
                fields=["deleted_at"], condition=models.Q(is_deleted=True), name="doc_deleted_at_partial"
            ),
        ]

    def __str__(self):
        return self.title

    # save()（title/memo の *_normalized 再計算）とdisplay_nameプロパティの実体は
    # core.models.NormalizedTextFieldsMixin/UuidPrefixedFilenameMixinに集約済み
    # （contracts.Contractとの重複をコード監査で発見、2026-08-25修正）。
    # extracted_text_normalized は抽出サービスが直接セットする（Mixin対象外、案1）。
