import logging

from django.db import models
from django.db.models import Q

logger = logging.getLogger(__name__)


class DocKbn(models.TextChoices):
    """書類管理区分。分類・カテゴリーが文書管理向けか契約書管理向けかを表す
    （screen-class-*/screen-cat-*の「書類管理区分」select、xlsx 分類管理/カテゴリー管理シート）。"""

    DOCUMENT = "document", "文書管理"
    CONTRACT = "contract", "契約書管理"


class Group(models.Model):
    """分類マスタ（screen-class-list/regist/edit/delete）。画面表示名は「分類」。
    permissions.PermissionProfileの分類表示範囲制御（doc_visible_groups等）からも参照される。
    削除は論理削除（xlsx 分類管理!B204「分類マスタから論理削除とする」、保存済みデータに
    影響しないこと）。一覧の削除ボタンは紐づく文書件数が0件のときのみ有効（xlsx 分類管理!B68）。
    """

    code = models.CharField("分類コード", max_length=20)
    name = models.CharField("分類名", max_length=100)
    doc_kbn = models.CharField("書類管理区分", max_length=10, choices=DocKbn.choices)
    is_deleted = models.BooleanField("削除済み", default=False)

    created_at = models.DateTimeField("作成日時", auto_now_add=True)
    updated_at = models.DateTimeField("更新日時", auto_now=True)

    class Meta:
        db_table = "m_group"
        verbose_name = "分類"
        verbose_name_plural = "分類マスタ"
        constraints = [
            # is_deleted=Falseの行同士でのみ一意（forms.GroupForm.clean_codeの重複チェックと同じ
            # 「論理削除済みのコードは再利用できる」という方針をDB制約でも保証する）。
            models.UniqueConstraint(fields=["code"], condition=Q(is_deleted=False), name="unique_group_code"),
        ]

    def __str__(self):
        return self.name


class Category(models.Model):
    """カテゴリーマスタ（screen-cat-list/regist/edit/delete）。分類(Group)の下位区分。
    削除は論理削除（xlsx カテゴリー管理!B196、分類と同様）。
    """

    code = models.CharField("カテゴリーコード", max_length=20)
    name = models.CharField("カテゴリー名", max_length=100)
    group = models.ForeignKey(
        "masters.Group", verbose_name="分類", on_delete=models.PROTECT, related_name="categories"
    )
    doc_kbn = models.CharField("書類管理区分", max_length=10, choices=DocKbn.choices)
    is_deleted = models.BooleanField("削除済み", default=False)

    created_at = models.DateTimeField("作成日時", auto_now_add=True)
    updated_at = models.DateTimeField("更新日時", auto_now=True)

    class Meta:
        db_table = "m_category"
        verbose_name = "カテゴリー"
        verbose_name_plural = "カテゴリーマスタ"
        constraints = [
            # Group同様、is_deleted=Falseの行同士でのみ一意にする。
            models.UniqueConstraint(fields=["code"], condition=Q(is_deleted=False), name="unique_category_code"),
        ]

    def __str__(self):
        return self.name


class RetentionKbn(models.TextChoices):
    DOCUMENT = "document", "文書"
    EAPPROVAL = "eapproval", "電子決裁"


class EapprovalDocName(models.TextChoices):
    """電子決裁の書類名。screen-retention-doc等のプルダウン固定値（xlsx 保存期間設定シート）。
    電子決裁機能自体は本実装のスコープ外（設定メニュー「電子決裁管理」ボタンはalert表示のみの
    未実装機能）だが、保存期間設定マスタ画面はこの2種別を管理対象として含んでいるため
    モデルとしては残す。
    """

    RINGISHO = "ringisho", "稟議書"
    KEIHI = "keihi", "経費支出伺"


class RetentionPeriodUnit(models.TextChoices):
    MONTH = "month", "ヵ月"
    YEAR = "year", "年"
    PERMANENT = "permanent", "永年"


class RetentionPeriod(models.Model):
    """保存期間設定（screen-retention-doc/regist-doc/edit-doc/delete）。文書用と電子決裁用
    （稟議書／経費支出伺）を`kbn`/`doc_name`で区別する（screen-retention-docのtbody1〜3に対応）。
    保存期間や表示順の重複登録は不可（xlsx 保存期間設定!B77,B191、フロント側のバリデーションは
    HTML上に実装が無いためモデル制約とフォーム側で保証する）。「永年」選択時は保存期間の数値を
    持たない（xlsx B73、`period_value`をnull許容にしている理由）。
    削除は論理削除（xlsx B146/B271「保存期間マスタから論理削除とする」、Group/Categoryと同じ
    方針）。documents.Document/contracts.Contractのretention_period外部キーはon_delete=PROTECTの
    ままだが、論理削除は行自体を消さないため参照整合性を壊さず、削除済みでも既存文書・契約書は
    引き続き参照できる。
    """

    kbn = models.CharField("区分", max_length=10, choices=RetentionKbn.choices)
    doc_name = models.CharField(
        "書類名（電子決裁のみ）", max_length=20, choices=EapprovalDocName.choices, blank=True, default=""
    )
    period_value = models.PositiveIntegerField("保存期間", null=True, blank=True)
    period_unit = models.CharField("保存期間単位", max_length=10, choices=RetentionPeriodUnit.choices)
    display_order = models.PositiveIntegerField("表示順")
    is_deleted = models.BooleanField("削除済み", default=False)

    class Meta:
        db_table = "m_retention_period"
        verbose_name = "保存期間設定"
        verbose_name_plural = "保存期間設定"
        constraints = [
            # Group/Category同様、is_deleted=Falseの行同士でのみ一意にする
            # （論理削除済みのkbn/doc_name/表示順の組み合わせは再利用可能にする）。
            models.UniqueConstraint(
                fields=["kbn", "doc_name", "display_order"],
                condition=Q(is_deleted=False),
                name="unique_retention_display_order",
            ),
        ]

    def __str__(self):
        if self.period_unit == RetentionPeriodUnit.PERMANENT:
            return "永年"
        return f"{self.period_value}{self.get_period_unit_display()}"


class SystemSetting(models.Model):
    """システム設定（シングルトン、DB上は常に1行のみを想定）。
    screen-other-main「自動ログアウト時間」タブ（screen-other-logout-edit）で編集する
    `session_idle_timeout_minutes`のほか、xlsxの各所で「設定ファイル等で定義し、先方より変更依頼を
    受けた際に容易に変更できること」と指定されている値をまとめて持つ。
    """

    session_idle_timeout_minutes = models.PositiveIntegerField("自動ログアウト時間(分)", default=60)
    # 「お知らせ」しきい値(notice_threshold_months)・契約書保存期限(contract_retention_years)は
    # 2026-08-13、settings.NOTICE_EXPIRING_THRESHOLD_MONTHS/NOTICE_DELETED_THRESHOLD_MONTHS/
    # CONTRACT_RETENTION_YEARS（.env経由）へ移行し、このモデルから削除した。DB編集用の管理画面・
    # Django管理サイトが無く、値を変更する経路が実質DB直接操作しか無かったため
    # （config/settings/base.py参照）。
    retention_permanent_years = models.PositiveIntegerField(
        "「永年」の実年数",
        default=50,
        help_text="保存期間「永年」の有効期限を計算する際に使う実際の年数（xlsx 保存期間設定!B74）",
    )
    audit_log_retention_months = models.PositiveIntegerField(
        "操作履歴ログ最大保存期間(ヵ月)",
        default=3,
        help_text="CSV出力の最大対象期間でもある（xlsx 操作履歴ログ!B48-49）",
    )

    class Meta:
        db_table = "m_system_setting"
        verbose_name = "システム設定"
        verbose_name_plural = "システム設定"

    def __str__(self):
        return "システム設定"
