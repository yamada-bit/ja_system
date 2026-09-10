import logging

from django.conf import settings
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Q

logger = logging.getLogger(__name__)


def _default_session_idle_timeout():
    """SystemSetting.session_idle_timeout_minutes の新規行既定値（監査 C-6）。
    `60` のハードコード（settings.SESSION_IDLE_TIMEOUT_MINUTES と重複）を避け、
    デプロイ環境の .env 値に追従させる。callable 参照なので migration でも
    `masters.models._default_session_idle_timeout` としてシリアライズされる。"""
    return settings.SESSION_IDLE_TIMEOUT_MINUTES

# 分類コード／カテゴリーコードは半角数字のみ許可（xlsx 分類管理!B116／カテゴリー管理!B113）。
# フォームの clean_code が NFKC 正規化（全角→半角）を済ませた上でこの validator を通す想定
# （監査 B-VAL-1、accounts.models._HANKAKU_DIGITS_VALIDATOR と同趣旨）。
_HANKAKU_DIGITS_VALIDATOR = RegexValidator(r"^[0-9]+$", "半角数字で入力してください")


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

    `department`はRev1.2（2026-08-24反映）で追加。分類マスタが部署単位で管理されるようになり、
    一覧・登録・編集は管理者は全部署、それ以外は自部署のみ（xlsx 分類管理!B73-75）。登録・編集
    画面の「部署」プルダウンは管理者のみ表示され、非管理者が作成した分類は自動的に自部署が
    設定される（masters/views.py参照）。移行前に作成された既存データは部署未設定
    （null）のままになりうるため、参照整合性を壊さないようnull許容にしている
    （on_delete=PROTECTはCategory.groupと同じ方針）。
    """

    code = models.CharField("分類コード", max_length=20, validators=[_HANKAKU_DIGITS_VALIDATOR])
    name = models.CharField("分類名", max_length=100)
    doc_kbn = models.CharField("書類管理区分", max_length=10, choices=DocKbn.choices)
    department = models.ForeignKey(
        "organizations.Department",
        verbose_name="部署",
        on_delete=models.PROTECT,
        related_name="+",
        null=True,
        blank=True,
    )
    is_deleted = models.BooleanField("削除済み", default=False)

    created_at = models.DateTimeField("作成日時", auto_now_add=True)
    updated_at = models.DateTimeField("更新日時", auto_now=True)

    class Meta:
        db_table = "m_group"
        verbose_name = "分類"
        verbose_name_plural = "分類マスタ"
        constraints = [
            # is_deleted=Falseの行同士で、かつ同一部署内でのみ一意にする。Rev1.2で分類は部署単位
            # 管理（非管理者は自部署のみ閲覧・編集）になったため、コードの一意性も部署内に限定する
            # （2026-09-10 No.1、ユーザー確認済み。全社一意のままだと、非管理者が一覧にも表示され
            # ない他部署の同一コードと衝突して理由の分からないエラーになる）。「論理削除済みのコードは
            # 再利用できる」方針（forms.GroupForm.clean_codeと同じ）もconditionで維持する。
            # departmentがNULL（Rev1.2移行前データ）の行同士はPostgresのNULL非同一仕様でこの制約の
            # 対象外になるが、移行後の新規・編集データは必ずdepartmentを持つため許容する。
            # 本番移行では旧データ（department IS NULL）の department を必ず補完する運用で確定
            # （null残置は許容しない、2026-09-10、モデル定義妥当性監査 A-3）。
            models.UniqueConstraint(
                fields=["department", "code"], condition=Q(is_deleted=False), name="unique_group_code"
            ),
        ]

    def __str__(self):
        return self.name


class Category(models.Model):
    """カテゴリーマスタ（screen-cat-list/regist/edit/delete）。分類(Group)の下位区分。
    削除は論理削除（xlsx カテゴリー管理!B196、分類と同様）。
    """

    code = models.CharField("カテゴリーコード", max_length=20, validators=[_HANKAKU_DIGITS_VALIDATOR])
    name = models.CharField("カテゴリー名", max_length=100)
    group = models.ForeignKey(
        "masters.Group", verbose_name="分類", on_delete=models.PROTECT, related_name="categories"
    )
    doc_kbn = models.CharField("書類管理区分", max_length=10, choices=DocKbn.choices)
    # Group.departmentと同じ理由・方針（Rev1.2で追加、null許容）。
    department = models.ForeignKey(
        "organizations.Department",
        verbose_name="部署",
        on_delete=models.PROTECT,
        related_name="+",
        null=True,
        blank=True,
    )
    is_deleted = models.BooleanField("削除済み", default=False)

    created_at = models.DateTimeField("作成日時", auto_now_add=True)
    updated_at = models.DateTimeField("更新日時", auto_now=True)

    def clean(self):
        """カテゴリーの書類管理区分は、紐付ける分類（group）の書類管理区分と一致していなければ
        ならない（documents/contracts 側は doc_kbn ごとに分類・カテゴリーを絞り込む前提で動く。
        監査 B-VAL-2）。CategoryForm.clean にも同じチェックがあるが、admin・将来の ModelForm など
        full_clean() を通る他経路のための多層防御としてモデル層にも持たせる。"""
        super().clean()
        if self.group_id and self.doc_kbn and self.group.doc_kbn != self.doc_kbn:
            from django.core.exceptions import ValidationError

            raise ValidationError(
                {
                    "doc_kbn": "書類管理区分が、紐付けた分類の書類管理区分と一致しません。",
                }
            )

    class Meta:
        db_table = "m_category"
        verbose_name = "カテゴリー"
        verbose_name_plural = "カテゴリーマスタ"
        constraints = [
            # Group同様、is_deleted=Falseの行同士で、かつ同一部署内でのみ一意にする
            # （Group.Meta.constraints unique_group_codeのコメント参照。2026-09-10 No.1）。
            # department IS NULL 行の本番移行補完も Group と同じ運用で確定（監査 A-3）。
            models.UniqueConstraint(
                fields=["department", "code"], condition=Q(is_deleted=False), name="unique_category_code"
            ),
        ]

    def __str__(self):
        return self.name


class RetentionKbn(models.TextChoices):
    """保存期間設定マスタの大区分。RetentionPeriod をどのタブ（screen-retention-doc の
    tbody1＝文書／tbody2〜3＝電子決裁の稟議書・経費支出伺）に属させるかを表す（xlsx
    保存期間設定シート）。電子決裁側は EapprovalDocName と組で使う。電子決裁機能自体は
    本実装のスコープ外だが、保存期間設定マスタ画面が管理対象に含むためモデルには残す。"""

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
    """保存期間の単位（screen-retention-* の「保存期間」入力の単位）。PERMANENT（永年）は
    period_value を持たず、満了日計算では settings.RETENTION_PERMANENT_YEARS の実年数へ
    読み替える（documents.services.calculate_expiry_date 参照）。xlsx 保存期間設定シート。"""

    MONTH = "month", "ヵ月"
    YEAR = "year", "年"
    PERMANENT = "permanent", "永年"


class RetentionPeriod(models.Model):
    """保存期間設定（screen-retention-doc/regist-doc/edit-doc/delete）。文書用と電子決裁用
    （稟議書／経費支出伺）を`kbn`/`doc_name`で区別する（screen-retention-docのtbody1〜3に対応）。
    保存期間や表示順の重複登録は不可（xlsx 保存期間設定!B77,B104,B191,B229、フロント側の
    バリデーションはHTML上に実装が無いためモデル制約とフォーム側で保証する）。「や」は表示順と
    保存期間の2つをそれぞれ一意にする趣旨で、下記3つのUniqueConstraintで担保する:
    - unique_retention_display_order: (kbn, doc_name, display_order)
    - unique_retention_period_value: (kbn, doc_name, period_value, period_unit)
      … 「ヵ月」「年」の重複（例: 「5年」を表示順違いで2件）を防ぐ
    - unique_retention_permanent: (kbn, doc_name) を period_unit='permanent' の行に限定
      … 「永年」はperiod_valueがNULLでPostgresが複数行を許容してしまうため、書類名毎に
      「永年」を1件だけにする専用の部分ユニーク制約が別途必要
    「永年」選択時は保存期間の数値を持たない（xlsx B73、`period_value`をnull許容にしている理由）。
    削除は論理削除（xlsx B146/B271「保存期間マスタから論理削除とする」、Group/Categoryと同じ
    方針）。documents.Document/contracts.Contractのretention_period外部キーはon_delete=PROTECTの
    ままだが、論理削除は行自体を消さないため参照整合性を壊さず、削除済みでも既存文書・契約書は
    引き続き参照できる。
    """

    kbn = models.CharField("区分", max_length=10, choices=RetentionKbn.choices)
    doc_name = models.CharField(
        "書類名（電子決裁のみ）", max_length=20, choices=EapprovalDocName.choices, blank=True, default=""
    )
    # 0ヵ月・0年保存は無意味なため下限1（監査 B-VAL-4）。「永年」時は null で検証スキップ。
    period_value = models.PositiveIntegerField(
        "保存期間", null=True, blank=True, validators=[MinValueValidator(1)]
    )
    period_unit = models.CharField("保存期間単位", max_length=10, choices=RetentionPeriodUnit.choices)
    # 表示順は1始まり（監査 B-VAL-4）。contracts.ContractRelation.display_order（0始まりの内部リンク順）
    # とは別物。
    display_order = models.PositiveIntegerField("表示順", validators=[MinValueValidator(1)])
    is_deleted = models.BooleanField("削除済み", default=False)

    # Group/Categoryと揃える（両者は最初からcreated_at/updated_atを持つ。RetentionPeriodだけ
    # 非対称だったのをリリース前作業で解消、review_pending.txt No.24）。論理削除
    # （RetentionDeleteView）でもupdated_atを更新する（Group/Categoryの
    # BaseScopedMasterDeleteViewと同じ挙動）。
    created_at = models.DateTimeField("作成日時", auto_now_add=True)
    updated_at = models.DateTimeField("更新日時", auto_now=True)

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
            # xlsx B77/B191: 保存期間そのものの重複も不可。period_valueがNULLになる「永年」は
            # この制約では複数行を許容してしまうため、下のunique_retention_permanentで別途担保する。
            models.UniqueConstraint(
                fields=["kbn", "doc_name", "period_value", "period_unit"],
                condition=Q(is_deleted=False),
                name="unique_retention_period_value",
            ),
            # 「永年」は書類名毎に1件だけ（period_value=NULLのため上の制約が効かない）。
            models.UniqueConstraint(
                fields=["kbn", "doc_name"],
                condition=Q(is_deleted=False, period_unit=RetentionPeriodUnit.PERMANENT),
                name="unique_retention_permanent",
            ),
        ]

    def __str__(self):
        """保存期間の表示名。「永年」は period_value を持たない（null 可）ため固定文字列を返し、
        それ以外は「5年」「3ヵ月」のように数値＋単位で組み立てる（監査 C-4）。"""
        if self.period_unit == RetentionPeriodUnit.PERMANENT:
            return "永年"
        return f"{self.period_value}{self.get_period_unit_display()}"


class SystemSetting(models.Model):
    """システム設定（シングルトン、DB上は常に1行のみを想定）。
    screen-other-main「自動ログアウト時間」タブ（screen-other-logout-edit）で編集する
    `session_idle_timeout_minutes`のほか、xlsxの各所で「設定ファイル等で定義し、先方より変更依頼を
    受けた際に容易に変更できること」と指定されている値をまとめて持つ。
    """

    # 0分＝即時ログアウトで機能破綻するため下限1（監査 B-VAL-4）。既定値は settings 参照（C-6）。
    session_idle_timeout_minutes = models.PositiveIntegerField(
        "自動ログアウト時間(分)",
        default=_default_session_idle_timeout,
        validators=[MinValueValidator(1)],
    )
    # 他の設定テーブルと揃えてタイムスタンプを持つ（監査 B-8。screen-other-logout-edit から更新）。
    created_at = models.DateTimeField("作成日時", auto_now_add=True)
    updated_at = models.DateTimeField("更新日時", auto_now=True)
    # 「お知らせ」しきい値(notice_threshold_months)・契約書保存期限(contract_retention_years)・
    # 「永年」の実年数(retention_permanent_years)・操作履歴ログ最大保存期間(audit_log_retention_months)
    # は、settings.NOTICE_EXPIRING_THRESHOLD_MONTHS/NOTICE_DELETED_THRESHOLD_MONTHS/
    # CONTRACT_RETENTION_YEARS/RETENTION_PERMANENT_YEARS/AUDIT_LOG_RETENTION_MONTHS（.env経由）へ
    # 順次移行し、このモデルから削除した（2026-08-13、retention_permanent_yearsのみ2026-08-27・
    # audit_log_retention_monthsのみ2026-09-03フィデリティ監査で発見・追随)。DB編集用の管理画面・
    # Django管理サイトが無く、値を変更する経路が実質DB直接操作しか無かったため
    # （config/settings/base.py参照）。この移行の結果、SystemSettingで実際に使うのは
    # session_idle_timeout_minutes（screen-other-logout-editで管理者が随時変更）のみ。

    class Meta:
        db_table = "m_system_setting"
        verbose_name = "システム設定"
        verbose_name_plural = "システム設定"

    def __str__(self):
        return "システム設定"

    @classmethod
    def load(cls):
        """シングルトン行（pk=1）を取得する唯一の入口（監査 B-VAL-7）。以前は読み口が
        core/views.py の get_or_create(pk=1) と core/middleware.py の .first() で不統一だった
        （.first() は0行なら None を返し、呼び出し側が実質フォールバック settings 値に頼っていた）。
        DB の CheckConstraint(pk=1) はPostgresのシーケンスがロールバックで戻らない都合で
        objects.create() 主体のテスト・admin と相性が悪いため採らず、アクセサをこの1関数へ集約して
        「常に pk=1 の1行」を保証する。"""
        return cls.objects.get_or_create(pk=1)[0]
