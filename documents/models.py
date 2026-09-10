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
from documents.storage_paths import document_searchable_upload_path, document_upload_path

logger = logging.getLogger(__name__)


class Document(NormalizedTextFieldsMixin, UuidPrefixedFilenameMixin, models.Model):
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
    # CharField(255)で導入していたが、NFKC正規化（normalize_for_search）は文字数を増やし得る
    # （例: 互換文字1字が複数字に展開される）ため、titleが255文字ぎりぎりの場合にDataErrorで
    # 保存が失敗し得た（品質レビューで発見、2026-08-25修正）。他の*_normalized列と同じTextFieldにし、
    # 上限自体を無くして原理的にオーバーフローしないようにする。
    # verbose_name は付けない（editable=False の検索用内部列で UI・admin に出ないため。監査 C-1/Q-3）。
    title_normalized = models.TextField(blank=True, default="", editable=False)
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
            # シャドウ列に対してのみ検索するため、GIN(gin_trgm_ops) も正規化列3本に揃えて張る。
            # 生 title / memo / extracted_text には索引を張らない（生 extracted_text の GIN は
            # filter(extracted_text="") の等値判定にしか使われず無用だったため 2026-09-10 に撤去。
            # 監査 B-IDX-1 / B-IDX-2）。
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

    # save()（*_normalizedシャドウカラムの再計算）とdisplay_nameプロパティの実体は
    # core.models.NormalizedTextFieldsMixin/UuidPrefixedFilenameMixinに集約済み
    # （contracts.Contractとの重複をコード監査で発見、2026-08-25修正）。
