import logging

from django.db import models

logger = logging.getLogger(__name__)


class PermissionRole(models.TextChoices):
    """システム権限。1:管理者/2:所属長/3:一般（xlsx 権限管理!I50,I58-59）。"""

    ADMIN = "admin", "管理者"
    MANAGER = "manager", "所属長"
    STAFF = "staff", "一般"


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
    """

    employee = models.OneToOneField(
        "accounts.Employee",
        verbose_name="職員",
        on_delete=models.CASCADE,
        related_name="permission_profile",
    )
    role = models.CharField("システム権限", max_length=10, choices=PermissionRole.choices)

    # 文書管理
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
    doc_download = models.BooleanField("文書管理-文書(ダウンロード)", default=False)

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
    contract_download = models.BooleanField("契約書-契約書(ダウンロード)", default=False)

    # 電子決裁（※保留、xlsx 権限管理!B211-215。電子決裁機能自体は本実装のスコープ外）
    eapproval_view_setting = models.BooleanField("電子決裁-書類毎の閲覧設定", default=False)
    eapproval_doc_name_manage = models.BooleanField("電子決裁-書類名(作成・変更)", default=False)
    eapproval_retention = models.BooleanField("電子決裁-申請書(保存期間)", default=False)

    updated_at = models.DateTimeField("更新日時", auto_now=True)

    class Meta:
        db_table = "t_staff_permission"
        verbose_name = "権限管理"
        verbose_name_plural = "権限管理"

    def __str__(self):
        return f"{self.employee} ({self.get_role_display()})"
