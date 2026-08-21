import logging

from django.contrib.postgres.indexes import GinIndex
from django.db import models

from contracts.storage_paths import (
    contract_searchable_upload_path,
    contract_upload_path,
    related_file_upload_path,
)
from core.text_normalization import normalize_for_search

logger = logging.getLogger(__name__)


class Contract(models.Model):
    """契約書（screen-storage2/screen-search「契約書」モード）。documentsと共通するUI/JSを持つが
    フィールド構成は異なる（個人情報フラグが無い、保存期間は選択式ではなく固定年数、契約特有項目
    〈契約日・契約期間・契約更新日・契約金額・契約先名〉を持つ）。保存期間はDocument.retention_period
    のようなFKを持たず、masters.SystemSetting.contract_retention_years（既定10年、
    xlsx メイン画面!B48「契約書の保存期限は固定で10年」）で一律計算する。

    `extracted_text`はdocuments.Documentと同様の理由で追加（screen-search「フリーワード」全文検索、
    2026-08-07ユーザー指示）。抽出処理自体もdocuments.Documentと同じ2段階方式
    （core.text_extraction_services／core.management.commands.extract_pending_pdf_text、
    2026-08-10追加）。関連書類(RelatedFile)は「AI-OCRでの処理は不要」とxlsxに明記されている
    （保管!B480）ため対象外、契約書本体ファイルのみを抽出対象とする。
    """

    title = models.CharField("契約書タイトル", max_length=255)
    department = models.ForeignKey(
        "organizations.Department",
        verbose_name="保管先部署",
        on_delete=models.PROTECT,
        related_name="contracts",
    )
    group = models.ForeignKey(
        "masters.Group", verbose_name="分類", on_delete=models.PROTECT, related_name="contracts"
    )
    category = models.ForeignKey(
        "masters.Category",
        verbose_name="カテゴリー",
        on_delete=models.PROTECT,
        related_name="contracts",
    )
    year = models.PositiveIntegerField("年")

    contract_date = models.DateField("契約日", null=True, blank=True)
    contract_period_start = models.DateField("契約期間(開始)", null=True, blank=True)
    contract_period_end = models.DateField("契約期間(終了)", null=True, blank=True)
    renewal_date = models.DateField("契約更新日", null=True, blank=True)
    contract_amount = models.DecimalField(
        "契約金額", max_digits=12, decimal_places=0, null=True, blank=True
    )
    contract_partner = models.CharField("契約先名", max_length=255, blank=True, default="")

    expiry_date = models.DateField(
        "保存満了日",
        help_text="保存日 + masters.SystemSetting.contract_retention_years から算出して保存する",
    )
    memo = models.TextField("メモ", blank=True, default="")
    file = models.FileField("ファイル", upload_to=contract_upload_path)
    extracted_text = models.TextField(
        "抽出本文",
        blank=True,
        default="",
        help_text="ファイルから抽出した本文テキスト。フリーワード全文検索の対象",
    )
    # documents.Document.title_normalized等と同じ理由で追加（core.text_normalization参照）。
    title_normalized = models.CharField(max_length=255, blank=True, default="", editable=False)
    memo_normalized = models.TextField(blank=True, default="", editable=False)
    extracted_text_normalized = models.TextField(blank=True, default="", editable=False)
    ocr_attempted = models.BooleanField(
        "OCR実行済み",
        default=False,
        help_text=(
            "documents.Document.ocr_attemptedと同じ理由で追加"
            "（core.management.commands.extract_pending_pdf_text参照）。"
        ),
    )
    searchable_file = models.FileField(
        "検索用PDF（OCRテキスト埋め込み版）",
        upload_to=contract_searchable_upload_path,
        null=True,
        blank=True,
        help_text=(
            "documents.Document.searchable_fileと同じ理由で追加（同モデルのhelp_text参照）。"
            "ただしContractにはprivacy_flag（個人情報フラグ）が無いため、documents.Documentと"
            "異なりファイル単位の除外判定は行わず、settings.OCR_EMBED_TEXT_TO_PDFのみに従って"
            "埋め込む（core.management.commands.extract_pending_pdf_text._should_embed参照）。"
        ),
    )

    save_date = models.DateTimeField("保存日", auto_now_add=True)
    uploader = models.ForeignKey(
        "accounts.Employee",
        verbose_name="保管・更新者",
        on_delete=models.PROTECT,
        related_name="uploaded_contracts",
    )
    updated_at = models.DateTimeField("更新日時", auto_now=True)

    is_deleted = models.BooleanField("削除済み", default=False)
    deleted_at = models.DateTimeField("削除日", null=True, blank=True)

    class Meta:
        db_table = "t_contract"
        verbose_name = "契約書"
        verbose_name_plural = "契約書"
        indexes = [
            GinIndex(
                fields=["extracted_text"], name="contract_extracted_text_trgm", opclasses=["gin_trgm_ops"]
            ),
            GinIndex(
                fields=["extracted_text_normalized"],
                name="contract_extr_text_norm_trgm",
                opclasses=["gin_trgm_ops"],
            ),
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        # documents.Document.saveと同じ理由（そちらのコメント参照）。
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
        """編集画面のPDFモックプレビュー等での表示用（storage_paths.contract_upload_pathが
        付与する重複防止UUIDプレフィックスを除いた、元のアップロードファイル名部分のみ返す）。
        """
        basename = self.file.name.rsplit("/", 1)[-1]
        return basename.split("_", 1)[1] if "_" in basename else basename


class RelatedFile(models.Model):
    """契約書の関連書類（screen-storage2契約書モード「関連書類」欄）。文書管理とは別の物理ファイル
    紐付けのみで、AI-OCR等の処理対象ではない（xlsx 保管!B480）。1ファイル選択ごとに次の行が
    自動追加される形でUI上は複数選択されるため、契約書1件に対し複数レコードを持つ。
    """

    contract = models.ForeignKey(
        "contracts.Contract",
        verbose_name="契約書",
        on_delete=models.CASCADE,
        related_name="related_files",
    )
    file = models.FileField("ファイル", upload_to=related_file_upload_path)
    display_order = models.PositiveIntegerField("表示順", default=0)

    class Meta:
        db_table = "t_contract_attachment"
        verbose_name = "関連書類"
        verbose_name_plural = "関連書類"
        ordering = ["display_order", "id"]

    def __str__(self):
        return self.file.name

    @property
    def display_name(self):
        """一覧・編集画面でのファイル名表示用（storage_paths.related_file_upload_pathが
        付与する重複防止UUIDプレフィックスを除いた、元のアップロードファイル名部分のみ返す）。
        """
        basename = self.file.name.rsplit("/", 1)[-1]
        return basename.split("_", 1)[1] if "_" in basename else basename
