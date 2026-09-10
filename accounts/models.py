import logging

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.core.validators import RegexValidator
from django.db import models

logger = logging.getLogger(__name__)

# 半角数字のみ許可（xlsx 職員マスタ!B173 等）。フォームの clean_* が NFKC 正規化（全角→半角）を
# 済ませた上でこの validator を通す想定。full_clean() を通らない CSV 取込は
# accounts.csv_import_services 側で同等の正規化＋チェックを別途持つ（監査 B-VAL-1）。
_HANKAKU_DIGITS_VALIDATOR = RegexValidator(r"^[0-9]+$", "半角数字で入力してください")


class EmployeeManager(BaseUserManager):
    """`職員番号`をログインIDとするEmployeeの生成ヘルパー。"""

    def create_user(self, employee_no, name, password=None, **extra_fields):
        """職員番号・氏名・パスワードで一般職員を1名作成する（職員番号は必須）。"""
        if not employee_no:
            raise ValueError("職員番号は必須です")
        employee = self.model(employee_no=employee_no, name=name, **extra_fields)
        employee.set_password(password)
        employee.save(using=self._db)
        return employee

    def create_superuser(self, employee_no, name, password=None, **extra_fields):
        """Django 管理サイト用のスーパーユーザーを作成する（is_staff / is_superuser を暗黙で True）。"""
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self.create_user(employee_no, name, password, **extra_fields)


class Rank(models.TextChoices):
    """職階。screen-staff-regist/editのプルダウン固定値。専用のマスタ管理画面がHTML上に
    存在しないため、DBマスタ化せずDjangoのchoicesとして保持する。"""

    KOSAYAKU = "20", "考査役"
    CHOSAYAKU = "25", "調査役"
    SHUJI = "35", "主事"
    SENNIN = "70", "専任職員"
    RINJI = "80", "臨時職員"
    HAKEN = "98", "派遣社員"


class Position(models.TextChoices):
    """役職。screen-staff-regist/editのプルダウン固定値（Rankと同様、専用マスタ画面が無い）。"""

    KACHO = "16", "課長"
    KAKARICHO = "40", "係長"
    IPPAN = "60", "一般職"
    SENNIN = "74", "専任職員"
    # 原本 index.html:2195 は「臨時時給（翌月払」で閉じ括弧が欠落しているが、表示上のタイポとして
    # 補正のまま確定（Rank/Position は原本にマスタ管理画面が無い固定値、2026-09-10、監査 A-5）。
    RINJI = "90", "臨時時給（翌月払）"
    HAKEN = "98", "派遣社員"


class Employee(AbstractBaseUser):
    """職員マスタ（screen-staff-list/detail/regist/edit）。

    `employee_no`をログインID(USERNAME_FIELD)として使う。「削除」機能はxlsx上で明示的に
    「無い」とされているため（職員マスタ!D120、要再確認No.1）、is_deleted等の論理削除フィールドは
    設けていない。退職者は`is_retired`で区別する（一覧から除外せず赤字表示、xlsx 職員マスタ!B70）。

    権限（システム権限・各種フラグ）はこのモデルには持たせず、permissions.PermissionProfile
    （screen-authority-edit）に分離する。screen-authority-editが「権限管理」として独立した
    編集画面を持ち、職員登録そのもの（screen-staff-regist/edit）とは別の業務フローのため。
    Django標準のPermissionsMixin（groups/user_permissions）は使わない。認可はPermissionProfileの
    フラグで独自に判定するため不要であり、`groups`フィールドがmasters.Group（分類マスタ、
    画面上の呼称も「分類」「Group」）と紛らわしくなることも避けたい。
    """

    # AbstractBaseUser 由来の password / last_login は verbose_name が英語のままで、
    # is_staff / is_superuser を日本語で上書きしているのと非対称だった（監査 C-2）。
    # 定義は AbstractBaseUser と同一で verbose_name だけ日本語化する（set_password 等の挙動に影響なし）。
    password = models.CharField("パスワード", max_length=128)
    last_login = models.DateTimeField("最終ログイン", blank=True, null=True)

    employee_no = models.CharField(
        "職員番号", max_length=20, unique=True, validators=[_HANKAKU_DIGITS_VALIDATOR]
    )
    name = models.CharField("氏名", max_length=100)
    department = models.ForeignKey(
        "organizations.Department",
        verbose_name="所属部署",
        on_delete=models.PROTECT,
        related_name="employees",
    )
    rank = models.CharField("職階", max_length=2, choices=Rank.choices)
    position = models.CharField("役職", max_length=2, choices=Position.choices)
    is_retired = models.BooleanField("退職", default=False)

    is_staff = models.BooleanField("Django管理サイトアクセス可否", default=False)
    is_superuser = models.BooleanField("Django管理サイト全権限", default=False)

    created_at = models.DateTimeField("作成日時", auto_now_add=True)
    updated_at = models.DateTimeField("更新日時", auto_now=True)

    objects = EmployeeManager()

    USERNAME_FIELD = "employee_no"
    REQUIRED_FIELDS = ["name"]

    class Meta:
        db_table = "m_staff"
        verbose_name = "職員"
        verbose_name_plural = "職員マスタ"

    def __str__(self):
        return f"{self.employee_no} {self.name}"

    @property
    def is_active(self):
        """「退職 ⟺ ログイン不可」を単一の真実源（is_retired）から導出する（監査 B-12）。
        以前は独立した is_active BooleanField（常時 True・どこからも更新されない）だったため、
        退職者でも is_active=True のままで、退職者ログイン拒否は LoginForm.confirm_login_allowed
        1箇所頼みだった。プロパティ化により Django の ModelBackend.user_can_authenticate /
        get_user（セッション復元）も退職者を自動的に弾く。setter は用意しない
        （is_retired 経由でのみ変える）。"""
        return not self.is_retired

    # has_perm / has_module_perms は Django 管理サイトが要求する最小実装（監査 C-5）。
    # 本システムの認可は permissions アプリ（PermissionProfile のフラグ）で独自判定するため、
    # PermissionsMixin は使わず、admin 用にはスーパーユーザーか否かだけを返す。
    def has_perm(self, perm, obj=None):
        return self.is_superuser

    def has_module_perms(self, app_label):
        return self.is_superuser
