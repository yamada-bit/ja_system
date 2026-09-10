import logging

from django.db import models

logger = logging.getLogger(__name__)


class PermissionRole(models.TextChoices):
    """システム権限。1:管理者/2:所属長/3:一般（xlsx 権限管理!I50,I58-59）。

    格納値 "admin"/"manager"/"staff" のアルファベット順が、xlsx が要求する権限コード
    1→2→3（管理者→所属長→一般）の昇順と**偶然一致**している。一覧のソート
    （`permissions.services.filter_authority_queryset` の `order_by("permission_profile__role")` /
    `AUTHORITY_SORT_FIELDS["role"]`）はこの一致に依存している。将来この格納値を変える場合は
    ソートが崩れるため、`Case/When` による明示マッピングを導入すること（監査 B-11）。
    """

    ADMIN = "admin", "管理者"
    MANAGER = "manager", "所属長"
    STAFF = "staff", "一般"


# PermissionProfileの権限フラグ(BooleanField)・多対多(ManyToManyField)フィールドの一覧。
# permissions/forms.py（AuthorityEditFormの入力項目）とaccounts/services.py
# （reset_permission_profile_if_neededの安全側リセット対象）の両方がこの一覧に依存する。
# 以前は両ファイルにハードコードされた別々のリストとして重複していたため、新しい権限フラグ追加時に
# 片方だけ更新してもう片方（特にリセット対象）を更新し忘れる、というドリフトリスクがあった
# （コード監査で発見、2026-08-24修正）。新しいBooleanField/ManyToManyFieldをPermissionProfileに
# 追加する際は、このリストへの追加も忘れないこと。
# 加えてpermissions/views.py（AuthorityCsvExportView._flags_row・CSVヘッダーのwriterow）は
# このリストを直接参照せず各フィールドを個別に手書きしているため、このリストとは別に手動同期が
# 必要な3箇所目（コード監査で発見、2026-08-24追記）。フラグ追加時はそちらの更新も忘れないこと。
FLAG_FIELDS = [
    "doc_retention_edit",
    "doc_download",
    "contract_edit",
    "contract_download",
    "eapproval_view_setting",
    "eapproval_doc_name_manage",
    "eapproval_retention",
]

MULTI_FIELDS = ["doc_visible_groups", "contract_visible_departments", "contract_visible_groups"]


class PermissionProfile(models.Model):
    """権限管理（screen-authority-list/edit）。職員1名につき1レコード。

    Rev1.1で画面が大きく再設計され（権限管理!B8「画面変更」）、以下の変更が入った：
    - 詳細画面（screen-authority-detail）が廃止され、一覧「編集」ボタンから直接編集画面へ遷移する
      （HTML確定版もscreen-authority-detailへ遷移するボタンが無くなり、到達不能な死んだマークアップ
      として残っているのみ。原本フィデリティ運用方針「モックとして壊れている箇所は再現しない」に
      従い、本実装でも詳細画面（AuthorityDetailView等）は削除する）。
    - 部署・事業所／カテゴリー単位の「作成・変更・削除」権限、「所属長への権限付与」
      「職員への権限付与」フラグを全廃し、システム権限プルダウン（1段階の選択）に統一。
    - 文書管理側の「部門間閲覧設定」を廃止（文書側は検索画面の部署選択自体が管理者のみに単純化
      された、permissions.services.can_select_department参照）。契約書側は
      `contract_cross_department_view`（真偽値）から`contract_visible_departments`（対象部署の
      複数選択、doc_visible_groups等と同じ構成）に変わった。
    - 新規権限「文書管理-文書-保存満了日変更」（`doc_retention_edit`）を追加。OFFの場合、対象者は
      保存済み文書の保存期間を編集できない（documents.forms.EditForm参照）。
    - 契約書-分類-表示（contract_visible_groups）、文書管理・契約書それぞれのダウンロード権限は
      Rev1.0から変更なし。

    電子決裁の3フラグは「※保留」（xlsx B211-215）で仕様自体が未確定だが、screen-authority-edit
    画面上に引き続きチェックボックスとして存在するためフィールドとしては保持する。

    Rev1.2（2026-08-24反映）での変更：
    - 新規権限「契約書-契約書-契約書情報変更」（`contract_edit`）を追加。文書管理側に対応する
      フラグは無い（xlsx上も文書側は変更されておらず、文書の保存・編集は引き続き無条件で可能）。
    - `contract_visible_departments`（契約書-部門間閲覧設定）の編集画面での表示・設定は
      「管理者のみ」に narrow された（xlsx 権限管理!H182「※権限：管理者のみ表示」。以前は
      管理者・所属長の双方が設定可能だった）。一覧画面の「部署」検索プルダウンも同様に
      管理者のみ表示に変更（xlsx 権限管理!B35）。いずれもpermissions/views.py
      AuthorityEditView/AuthorityListViewが`request.user`の役職を見てテンプレート側の表示を
      制御する（モデル自体には制約を持たせない）。
    """

    employee = models.OneToOneField(
        "accounts.Employee",
        verbose_name="職員",
        on_delete=models.CASCADE,
        related_name="permission_profile",
    )
    # xlsx 職員マスタ D118「新規登録時に『権限管理』は初期値をセットしておく」。初期値 STAFF が
    # 生成経路（CSV取込の即時 create／手動登録後の遅延 get_or_create）に散在していたため、
    # フィールドの default として一元化する（監査 D-1）。※遅延生成フロー自体の統一は別スコープ。
    role = models.CharField(
        "システム権限", max_length=10, choices=PermissionRole.choices, default=PermissionRole.STAFF
    )

    # 文書管理
    # doc_visible_groups / contract_visible_groups とも masters.Group への M2M（related_name="+"）。
    # Group は論理削除で物理行が残るため、削除済み Group への中間テーブル行も残るが、消費側
    # （core.forms.scoped_group_and_category_querysets、AuthorityEditForm 等）が必ず is_deleted=False で
    # 絞るため実害はない。Group 側からの棚卸し経路が必要になったら related_name を付ける（監査 B-10）。
    doc_visible_groups = models.ManyToManyField(
        "masters.Group",
        verbose_name="文書管理-分類(表示)",
        related_name="+",
        blank=True,
        help_text="この職員が保存/検索時に選択できる分類の一覧（xlsx 権限管理!B167-170）",
    )
    doc_retention_edit = models.BooleanField(
        "文書管理-文書(保存満了日変更)",
        default=False,
        help_text="OFFの場合、保存した文書の保存期間を編集できない（xlsx 権限管理!B172-175、Rev1.1で追加）",
    )
    doc_download = models.BooleanField(
        "文書管理-文書(ダウンロード)",
        default=False,
        help_text=(
            "OFFの場合、検索・閲覧画面で文書のダウンロード／実プレビューができない"
            "（xlsx 権限管理!B177-180、要再確認No.20〜22。permissions.services.can_download参照。"
            "管理者はフラグ値に関わらず常に可）"
        ),
    )

    # 契約書
    contract_visible_departments = models.ManyToManyField(
        "organizations.Department",
        verbose_name="契約書-部門間閲覧設定",
        related_name="+",
        blank=True,
        help_text=(
            "この職員が契約書検索画面の「部署」で自部署以外に選択できる部署の一覧"
            "（xlsx 権限管理!B182-183・検索・閲覧・変更!B421-423、Rev1.1で真偽値から複数選択に変更）"
        ),
    )
    contract_visible_groups = models.ManyToManyField(
        "masters.Group",
        verbose_name="契約書-分類(表示)",
        related_name="+",
        blank=True,
    )
    contract_edit = models.BooleanField(
        "契約書-契約書(契約書情報変更)",
        default=False,
        help_text=(
            "OFFの場合、対象者は契約書の保存・編集ができない（xlsx 権限管理!B193-198、Rev1.2で新規追加）。"
            "保存不可＝メイン画面の保管枠内「契約書」ボタン非表示、編集不可＝契約書詳細画面の「編集」"
            "「削除」ボタン非表示、として制御する（permissions.services.can_edit_contract参照）。"
        ),
    )
    contract_download = models.BooleanField(
        "契約書-契約書(ダウンロード)",
        default=False,
        help_text=(
            "OFFの場合、検索・閲覧画面で契約書のダウンロード／実プレビューができない"
            "（xlsx 権限管理!B193-194、要再確認No.20〜22。permissions.services.can_download参照。"
            "管理者はフラグ値に関わらず常に可）"
        ),
    )

    # 電子決裁（※保留、xlsx 権限管理!B211-215。電子決裁機能自体は本実装のスコープ外のため、
    # 下記3フラグは値の保持のみで連動先が無い。詳細はCLAUDE.md「既知の未実装・保留事項」参照）
    eapproval_view_setting = models.BooleanField(
        "電子決裁-書類毎の閲覧設定",
        default=False,
        help_text="※保留（xlsx 権限管理!B211-215）。電子決裁機能はスコープ外のため値の保持のみ・連動先なし",
    )
    eapproval_doc_name_manage = models.BooleanField(
        "電子決裁-書類名(作成・変更)",
        default=False,
        help_text="※保留（xlsx 権限管理!B211-215）。電子決裁機能はスコープ外のため値の保持のみ・連動先なし",
    )
    eapproval_retention = models.BooleanField(
        "電子決裁-申請書(保存期間)",
        default=False,
        help_text="※保留（xlsx 権限管理!B211-215）。電子決裁機能はスコープ外のため値の保持のみ・連動先なし",
    )

    # 他マスタ（Group/Category/RetentionPeriod 等）と揃えて作成時刻も残す（監査 B-7）。
    created_at = models.DateTimeField("作成日時", auto_now_add=True)
    updated_at = models.DateTimeField("更新日時", auto_now=True)

    class Meta:
        db_table = "t_staff_permission"
        verbose_name = "権限管理"
        verbose_name_plural = "権限管理"

    def __str__(self):
        return f"{self.employee} ({self.get_role_display()})"


# permissions/views.py AuthorityCsvExportView（一覧のCSV出力）が使うフラグ列の並び順
# （＝原本HTML一覧の列順、モデルのフィールド宣言順と一致）。以前はCSVヘッダー・_flags_row()の
# どちらもFLAG_FIELDS/MULTI_FIELDSを参照せず個別に手書きされており、両ファイルとは別に手動同期が
# 必要な3箇所目になっていた（コード監査で発見、2026-08-24追記）。ヘッダー文言は各フィールドの
# verbose_name（このファイル内で定義済み）をそのまま使うため、ここでは文言を持たない。
# 並び順自体はモデルのフィールド宣言順から機械的に導出できない（ManyToManyFieldはモデルの
# `_meta.get_fields()`がアプリ起動完了前（AppRegistryNotReady）に呼べず、モジュール読み込み時には
# 解決できないため）ので、この列挙自体は手書きのまま残す。ただしFLAG_FIELDS/MULTI_FIELDSに
# 追加したフィールドをここに追加し忘れた場合はpermissions.tests.PermissionModelsTest
# .test_csv_export_fields_matches_flag_and_multi_fieldsが即座に検知する
# （コード監査で発見、2026-08-25修正）。
CSV_EXPORT_FIELDS = [
    "doc_visible_groups",
    "doc_retention_edit",
    "doc_download",
    "contract_visible_departments",
    "contract_visible_groups",
    "contract_edit",
    "contract_download",
    "eapproval_view_setting",
    "eapproval_doc_name_manage",
    "eapproval_retention",
]
