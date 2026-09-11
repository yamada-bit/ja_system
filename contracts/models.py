import logging

from django.contrib.postgres.indexes import GinIndex
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

# documents.models._YEAR_VALIDATORS と同じ（西暦年の健全性チェック、監査 B-VAL-3）。
# 2行の定数のためクロスアプリ import を避けて併記する。
_YEAR_VALIDATORS = [MinValueValidator(1900), MaxValueValidator(2200)]

from contracts.storage_paths import contract_upload_path
from core.models import NormalizedTextFieldsMixin, UuidPrefixedFilenameMixin
from core.upload_validation import validate_no_active_content

logger = logging.getLogger(__name__)


class Contract(NormalizedTextFieldsMixin, UuidPrefixedFilenameMixin, models.Model):
    """契約書（screen-storage2/screen-search「契約書」モード）。documentsと共通するUI/JSを持つが
    フィールド構成は異なる（個人情報フラグが無い、保存期間は選択式ではなく固定年数、契約特有項目
    〈契約日・契約期間・契約更新日・契約金額・契約先名〉を持つ）。保存期間はDocument.retention_period
    のようなFKを持たず、`settings.CONTRACT_RETENTION_YEARS`（既定10年、xlsx メイン画面!B48
    「契約書の保存期限は固定で10年」）で一律計算する（品質レビューで発見：以前はDB設定値
    `masters.SystemSetting.contract_retention_years`を参照していたが2026-08-13に.env経由の
    設定値へ移行済み〈config/settings/base.py参照〉で、このdocstringが追従していなかった。
    2026-08-25修正）。

    `extracted_text_normalized`はdocuments.Documentと同様の理由で追加（screen-search「フリーワード」
    全文検索、2026-08-07ユーザー指示）。抽出処理自体もdocuments.Documentと同じ2段階方式
    （core.text_extraction_services／core.management.commands.extract_pending_pdf_text、
    2026-08-10追加）。生の抽出テキストは保存せず NFKC 正規化した列のみ持つ（監査 案1、2026-09-11。
    Contract には privacy_flag が無いため、OCR 文書の `ocr_textdata` は
    settings.OCR_STORE_TEXTDATA のみに従って保存する）。関連書類(ContractRelation)はRev1.6で
    「既に保管済みの契約書を検索して紐付ける」方式に変わったため物理ファイル自体を持たず、
    全文抽出は契約書本体ファイルのみを対象とする。
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
    year = models.PositiveIntegerField("年", validators=_YEAR_VALIDATORS)

    contract_date = models.DateField("契約日", null=True, blank=True)
    contract_period_start = models.DateField("契約期間(開始)", null=True, blank=True)
    contract_period_end = models.DateField("契約期間(終了)", null=True, blank=True)
    renewal_date = models.DateField("契約更新日", null=True, blank=True)
    # 原本HTML（<input type="text">）・xlsx とも桁/型の指定なし。max_digits=12（≒9,999億円上限）・
    # decimal_places=0（整数円格納）で確定（2026-09-10 ユーザー承認、モデル定義妥当性監査 A-1/B-6）。
    # DecimalField のままにしているのは CommaNumberInput（3桁区切り入力ウィジェット）が Decimal 往復を
    # 前提に実装されているため。整数専用型（PositiveBigIntegerField）への変更は影響が広く見送り。
    contract_amount = models.DecimalField(
        "契約金額", max_digits=12, decimal_places=0, null=True, blank=True
    )
    # 一覧のソート対象列（契約先名）だが、フリーワード検索・NFKC正規化シャドウ（*_normalized）の
    # 対象外。xlsx に契約先名を検索対象とする記載がないため現状維持で確定（2026-09-10、監査 A-4）。
    contract_partner = models.CharField("契約先名", max_length=255, blank=True, default="")

    expiry_date = models.DateField(
        "保存満了日",
        db_index=True,  # documents.Document.expiry_date と同じ（監査 B-IDX-3）
        help_text="保存日 + settings.CONTRACT_RETENTION_YEARS から算出して保存する",
    )
    memo = models.TextField("メモ", blank=True, default="")
    file = models.FileField(
        "ファイル", upload_to=contract_upload_path, validators=[validate_no_active_content]
    )
    # documents.Document.title_normalized等と同じ理由（core.text_normalization参照）。
    # CharField(255)→TextFieldの経緯もdocuments側と同じ（NFKC正規化による文字数増加で DataError が
    # 起き得たため。品質レビューで発見、2026-08-25修正）。verbose_name は付けない（editable=False の
    # 検索用内部列。監査 C-1/Q-3）。
    title_normalized = models.TextField(blank=True, default="", editable=False)
    memo_normalized = models.TextField(blank=True, default="", editable=False)
    # documents.Document.extracted_text_normalized と同じ（生カラム廃止＝監査 案1、2026-09-11。
    # populate は NormalizedTextFieldsMixin ではなく抽出サービスが直接行う）。
    extracted_text_normalized = models.TextField(blank=True, default="", editable=False)
    # documents.Document.text_extracted と同じ（監査 案2、2026-09-11。旧 ocr_attempted を統合）。
    text_extracted = models.BooleanField(
        "本文抽出済み",
        default=False,
        db_index=True,
        help_text=(
            "テキスト層抽出または OCR による本文抽出が完了したら True（空結果でも完了は完了）。"
            "core.management.commands.extract_pending_pdf_text は False のレコードだけを対象にする。"
            "再抽出させたい場合は運用手順で False に戻す。"
        ),
    )
    # documents.Document.ocr_textdata と同じ（監査 案3、2026-09-11）。当初実装は privacy_flag の
    # 影響なしで、Document/Contract とも settings.OCR_STORE_TEXTDATA のみに従って保存する。
    ocr_textdata = models.JSONField(
        "OCR座標データ",
        null=True,
        blank=True,
        editable=False,
        help_text=(
            "スキャン文書の OCR 行レイアウト（core.ocr_layout_services.textdatas_to_json 形式）。"
            "検索用PDFを core.searchable_pdf_services が必要時に生成するための元データ。"
            "settings.OCR_STORE_TEXTDATA=True のスキャン文書でのみ保存する。"
        ),
    )

    # documents.Document.save_date と同じ（監査 B-IDX-4）。
    save_date = models.DateTimeField("保存日", auto_now_add=True, db_index=True)
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
        constraints = [
            # 契約期間の前後関係を DB でも担保（フォームの validate_date_range に加えた多層防御。
            # 監査 B-VAL-5。ContractRelation が自己参照禁止を CheckConstraint 化しているのに合わせて
            # rigor を揃える）。両端 null 可（契約日のみ・期間未入力もあり得るため）。
            models.CheckConstraint(
                condition=(
                    models.Q(contract_period_start__lte=models.F("contract_period_end"))
                    | models.Q(contract_period_start__isnull=True)
                    | models.Q(contract_period_end__isnull=True)
                ),
                name="contract_period_start_before_end",
            ),
        ]
        indexes = [
            # documents.Document.Meta.indexes と同じ方針（監査 B-IDX-1 / B-IDX-2）。生 extracted_text
            # カラム自体は 2026-09-11 に廃止（案1）。
            # フリーワード検索・タイトル検索は正規化シャドウ列にのみ icontains するため、GIN は
            # title_normalized / memo_normalized / extracted_text_normalized の3本に揃える。
            # 生カラムには索引を張らない。
            GinIndex(fields=["title_normalized"], name="contract_title_norm_trgm", opclasses=["gin_trgm_ops"]),
            GinIndex(fields=["memo_normalized"], name="contract_memo_norm_trgm", opclasses=["gin_trgm_ops"]),
            GinIndex(
                fields=["extracted_text_normalized"],
                name="contract_extr_text_norm_trgm",
                opclasses=["gin_trgm_ops"],
            ),
            # documents.Document と同じ部分索引（監査 B-IDX-5）。
            models.Index(
                fields=["deleted_at"],
                condition=models.Q(is_deleted=True),
                name="contract_deleted_at_partial",
            ),
        ]

    def __str__(self):
        return self.title

    # save()（title/memo の *_normalized 再計算）とdisplay_nameプロパティの実体は
    # core.models.NormalizedTextFieldsMixin/UuidPrefixedFilenameMixinに集約済み
    # （documents.Documentとの重複をコード監査で発見、2026-08-25修正）。
    # extracted_text_normalized は抽出サービスが直接セットする（Mixin対象外、案1）。


class ContractRelation(models.Model):
    """契約書の関連書類（screen-storage2契約書モード「関連書類」欄）。

    Rev1.5までは物理ファイルをアップロードする`RelatedFile`だったが、Rev1.6（xlsx 保管!B478-484）で
    「関連する(紐付ける)契約書を選択する。既に保存済みの契約書を検索してセットする」方式に転換した
    ため、ファイルではなく**既存Contractへの参照**を保持する。契約書1件に対し複数レコードを持ち、
    UI上の並び順（「ファイルの選択」で確定した順）を`display_order`で保存する。

    `RelatedFile`（`t_contract_attachment`）は本番リリース前のためユーザー判断で完全撤去した
    （2026-09-09、HTML_REIMPL_CHECKLIST_ARCHIVE.md「R6-1」節）。

    両FKとも`on_delete=CASCADE`：紐付け先契約書が日次バッチ（purge_expired_deleted_records）で
    物理削除されたら関連行も静かに消える。論理削除（is_deleted=True）の場合は行は残り、検索・閲覧
    画面で「既に削除されている関連資料です」と赤表示する（R6-3、xlsx 検索・閲覧・変更!B677-680）。

    紐付け先（related_contract、非所有側）が物理削除されると、削除されていない所有側契約書の
    関連行も「関連書類が消えた記録を残さず」静かに消える。この挙動は認識済みで現状維持
    （物理削除自体が「削除から一定期間経過」の日次バッチのみ、監査 B-13）。
    """

    contract = models.ForeignKey(
        "contracts.Contract",
        verbose_name="契約書",
        on_delete=models.CASCADE,
        related_name="related_links",
    )
    related_contract = models.ForeignKey(
        "contracts.Contract",
        verbose_name="関連書類（契約書）",
        on_delete=models.CASCADE,
        related_name="linked_from",
    )
    display_order = models.PositiveIntegerField("表示順", default=0)

    class Meta:
        db_table = "t_contract_relation"
        verbose_name = "関連書類"
        verbose_name_plural = "関連書類"
        ordering = ["display_order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["contract", "related_contract"], name="uniq_contract_relation"
            ),
            # 自分自身を関連書類に指定させない（フォーム改ざん対策。サービス層でも除外するが
            # DB制約でも二重に防ぐ）。
            models.CheckConstraint(
                condition=~models.Q(contract=models.F("related_contract")),
                name="no_self_contract_relation",
            ),
        ]

    def __str__(self):
        return f"{self.contract_id} → {self.related_contract_id}"
