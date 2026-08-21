import logging

from django.contrib.postgres.indexes import GinIndex
from django.db import models

from core.text_normalization import normalize_for_search
from documents.storage_paths import document_searchable_upload_path, document_upload_path

logger = logging.getLogger(__name__)


class Document(models.Model):
    """文書（screen-storage2/screen-search「文書」モード、screen-storage1経由でアップロード）。

    保管画面のフォーム項目にそのまま対応する。`extracted_text`は screen-search の「フリーワード」欄が
    ファイル本文に対する全文検索も行う前提（2026-08-07ユーザー指示）で追加した。旧ja_pj_oldでは
    本番DBのLC_CTYPE=Cが原因でpg_trgmが日本語トライグラムを生成できず、全文検索が実質
    `icontains`単純部分一致にフォールバックしていたが、新ja_db（`Japanese_Japan.utf8`ロケールで
    作成）ではpg_trgmが日本語で正しく機能することを確認済みのため、GinIndex(gin_trgm_ops)による
    類似検索を前提にできる。実際のPDF本文抽出処理は登録直後の同期抽出
    （core.text_extraction_services.try_immediate_text_layer_extraction、テキスト層のある
    PDFのみ対象）と、定期バッチ（core.management.commands.extract_pending_pdf_text、
    テキスト層の無いスキャン文書はGoogle Cloud VisionでOCR）の2段階で行う（2026-08-10追加）。
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
    year = models.PositiveIntegerField("年")
    retention_period = models.ForeignKey(
        "masters.RetentionPeriod",
        verbose_name="保存期間",
        on_delete=models.PROTECT,
        related_name="documents",
    )
    expiry_date = models.DateField(
        "保存満了日",
        help_text=(
            "保存日+保存期間から算出して保存する（メイン画面お知らせの「有効期限切れ」"
            "「有効期限切れまでXヶ月以内」抽出で検索条件として使うため、都度計算せず保持する）"
        ),
    )
    privacy_flag = models.BooleanField("個人情報が含まれる", default=True)
    memo = models.TextField("メモ", blank=True, default="")
    file = models.FileField("ファイル", upload_to=document_upload_path)
    extracted_text = models.TextField(
        "抽出本文",
        blank=True,
        default="",
        help_text="ファイルから抽出した本文テキスト。フリーワード全文検索の対象",
    )
    # title/memo/extracted_textそれぞれの検索用シャドウカラム（save()で自動生成、editable=False）。
    # 半角全角を問わず検索できるようにするため（簡易設計指示書の検索要件、
    # core.text_normalization.normalize_for_search参照）、NFKC正規化した値を保存しておき、
    # 検索時はキーワード側も同じ正規化をした上でこちらのカラムに対してicontainsする
    # （元のtitle/memo/extracted_text自体はユーザー入力・抽出結果をそのまま保持する）。
    title_normalized = models.CharField(max_length=255, blank=True, default="", editable=False)
    memo_normalized = models.TextField(blank=True, default="", editable=False)
    extracted_text_normalized = models.TextField(blank=True, default="", editable=False)
    ocr_attempted = models.BooleanField(
        "OCR実行済み",
        default=False,
        help_text=(
            "core.management.commands.extract_pending_pdf_textがOCR（Google Cloud Vision）を"
            "実行完了した場合にTrueにする。OCR結果が空文字列（画像に文字が無い等）の場合でも"
            "extracted_text=\"\"のままだと毎回スキャン文書と判定され無限にOCRが再実行されて"
            "しまうため、このフラグで一度実行済みのレコードをバッチの対象から除外する"
            "（一時的なAPIエラーで例外が起きた場合はセットしないため次回リトライされる）。"
        ),
    )
    searchable_file = models.FileField(
        "検索用PDF（OCRテキスト埋め込み版）",
        upload_to=document_searchable_upload_path,
        null=True,
        blank=True,
        help_text=(
            "settings.OCR_EMBED_TEXT_TO_PDF=Trueかつprivacy_flag=False（個人情報を含まない）の"
            "場合のみ、スキャン文書のOCR結果を透明テキストとして埋め込んだPDFを"
            "core.management.commands.extract_pending_pdf_textが生成する（既定はnull＝未生成）。"
            "個人情報を含む文書（privacy_flag=True）は検索用PDFへの複製を避けるため対象外とする"
            "（2026-08-19追加）。原本（fileフィールド）は変更せず別ファイルとして保持する"
            "（監査・原本性の観点）。"
        ),
    )

    save_date = models.DateTimeField("保存日", auto_now_add=True)
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
            GinIndex(fields=["extracted_text"], name="doc_extracted_text_trgm", opclasses=["gin_trgm_ops"]),
            GinIndex(
                fields=["extracted_text_normalized"],
                name="doc_extracted_text_norm_trgm",
                opclasses=["gin_trgm_ops"],
            ),
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        # title/memo/extracted_textのいずれかを更新するsave()では、対応する
        # *_normalizedシャドウカラムも必ず同時に再計算・永続化する。update_fieldsが
        # 指定されたsave()（core.text_extraction_services / extract_pending_pdf_text
        # バッチのsave(update_fields=["extracted_text"])等）ではDjangoがそこに列挙された
        # カラムしかUPDATE文に含めないため、ここで対応する正規化カラムを追加しないと
        # 値をセットしたつもりでもDBに反映されない。
        self.title_normalized = normalize_for_search(self.title)
        self.memo_normalized = normalize_for_search(self.memo)
        self.extracted_text_normalized = normalize_for_search(self.extracted_text)
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            update_fields = set(update_fields)
            if "title" in update_fields:
                update_fields.add("title_normalized")
            if "memo" in update_fields:
                update_fields.add("memo_normalized")
            if "extracted_text" in update_fields:
                update_fields.add("extracted_text_normalized")
            kwargs["update_fields"] = update_fields
        super().save(*args, **kwargs)

    @property
    def display_name(self):
        """編集画面のPDFモックプレビュー等での表示用（storage_paths.document_upload_pathが
        付与する重複防止UUIDプレフィックスを除いた、元のアップロードファイル名部分のみ返す）。
        """
        basename = self.file.name.rsplit("/", 1)[-1]
        return basename.split("_", 1)[1] if "_" in basename else basename
