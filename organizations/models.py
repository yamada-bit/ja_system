import logging

from django.db import models

logger = logging.getLogger(__name__)

# 部課コード"99"は「退職」を表す特別な部課として扱う（xlsx 職員マスタ!B114-115「部課コードが
# "99"の場合...退職扱いとする」、部署管理!B45「(但し部課コード99の退職者は対象外)」）。
# 以前はaccounts.csv_import_services（CSV取込という末端の一機能）に定義されていたため、
# 本来は無関係なorganizations/forms.py・accounts/forms.pyの2箇所がこれを参照するためだけに
# 関数内ローカルimportを強いられていた（コード監査で発見、2026-08-24にDepartmentと同じ
# organizations/models.pyへ移設）。
RETIRED_SECTION_CODE = "99"


class Department(models.Model):
    """部署マスタ（screen-dept-list/regist/edit）。本支所＋部課の組み合わせを1レコードとして
    管理する（xlsx 部署管理!B87「既に存在している"本支所コード+部課コード"の場合は登録時に
    エラーとする」より、本支所と部課を別テーブルに正規化せずHTML/xlsxの一覧構成のまま
    1テーブルで保持する）。削除画面はHTML上に存在しないため削除機能は設けない。
    """

    branch_code = models.CharField("本支所コード", max_length=10)
    branch_name = models.CharField("本支所名", max_length=100)
    section_code = models.CharField("部課コード", max_length=10)
    section_name = models.CharField("部課名", max_length=100)

    created_at = models.DateTimeField("作成日時", auto_now_add=True)
    updated_at = models.DateTimeField("更新日時", auto_now=True)

    class Meta:
        db_table = "m_department"
        verbose_name = "部署"
        verbose_name_plural = "部署マスタ"
        constraints = [
            models.UniqueConstraint(
                fields=["branch_code", "section_code"], name="unique_department_branch_section"
            )
        ]

    def __str__(self):
        # Rev1.1原本index.html（例:2364,2461等）で部課名の表示から本支所名（「本　店|」）の
        # プレフィックスが撤去され、部課がある場合は部課名のみを表示する形に変更された
        # （部課の無い本支所は元々本支所名のみの表示のまま変更なし）。
        return self.section_name or self.branch_name


class DepartmentViewScope(models.Model):
    """閲覧部署範囲（xlsx 部署管理!B209-212(Rev1.1)「部署統合・分割」）。

    旧仕様は統合・分割時に対象部署を部署マスタから論理削除していたが、Rev1.1で
    「削除はせず、統合前/分割前の部署分も閲覧可能なように、閲覧部署範囲テーブルを更新する」に
    変更された。`viewer_department`に所属する職員は、自部署に加えて`visible_department`の
    文書・契約書も検索・閲覧できる（documents/contracts.search_services参照）。

    方向の解釈（xlsx本文に厳密な図解が無いため、部署管理!B155-212の「統合」「分割」の
    データ例から読み取った運用ルール）：
    - 統合（部署Xに部署Yを統合する）：viewer_department=X（存続する側＝編集対象の部署）、
      visible_department=Y（吸収される側＝選択した対象部署）で1件作成。
    - 分割（部署Xを対象部署へ分割する）：選択した対象部署それぞれについて
      viewer_department=対象部署（分割後の新部署）、visible_department=X（分割元＝編集対象の
      部署）で作成。
    """

    viewer_department = models.ForeignKey(
        "organizations.Department",
        verbose_name="閲覧する側の部署",
        on_delete=models.CASCADE,
        related_name="view_scopes_as_viewer",
    )
    visible_department = models.ForeignKey(
        "organizations.Department",
        verbose_name="閲覧可能になる部署",
        on_delete=models.CASCADE,
        related_name="view_scopes_as_visible",
    )
    ACTION_MERGE = "merge"
    ACTION_SPLIT = "split"
    ACTION_CHOICES = [(ACTION_MERGE, "統合"), (ACTION_SPLIT, "分割")]
    action = models.CharField("種別", max_length=10, choices=ACTION_CHOICES)
    created_at = models.DateTimeField("作成日時", auto_now_add=True)

    class Meta:
        db_table = "m_department_view_scope"
        verbose_name = "閲覧部署範囲"
        verbose_name_plural = "閲覧部署範囲"
        constraints = [
            models.UniqueConstraint(
                fields=["viewer_department", "visible_department"], name="unique_department_view_scope"
            )
        ]

    def __str__(self):
        return f"{self.viewer_department} ← {self.visible_department}"


class MenuItemSetting(models.Model):
    """メイン画面項目設定（screen-other-main「メイン画面項目」タブ／screen-other-main-edit）。
    部署ごとにメイン画面の検索・閲覧・変更／保管ボタンの表示可否を制御する
    （xlsx その他設定!B38「部署マスタとメニューボタン制御テーブルを結合した一覧を表示」）。
    未設定・新規部署のデフォルトは全項目OFF（xlsx その他設定!B73）。
    """

    department = models.OneToOneField(
        "organizations.Department",
        verbose_name="部署",
        on_delete=models.CASCADE,
        related_name="menu_item_setting",
    )
    show_search_document = models.BooleanField("検索・閲覧・変更-文書", default=False)
    show_search_contract = models.BooleanField("検索・閲覧・変更-契約書", default=False)
    show_search_eapproval = models.BooleanField("検索・閲覧・変更-電子決裁", default=False)
    show_storage_document = models.BooleanField("保管-文書", default=False)
    show_storage_contract = models.BooleanField("保管-契約書", default=False)

    class Meta:
        db_table = "m_menu_item_setting"
        verbose_name = "メイン画面項目設定"
        verbose_name_plural = "メイン画面項目設定"

    def __str__(self):
        return f"{self.department}"
