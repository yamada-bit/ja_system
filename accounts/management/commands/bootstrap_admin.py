import getpass
import logging

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import Error as DjangoDbError
from django.db import transaction

from accounts.models import Employee, Position, Rank
from organizations.models import Department
from permissions.models import PermissionProfile, PermissionRole

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """本番の最初の管理者職員を対話式にブートストラップする（RELEASE_PREP_NOTES.md「2.」）。

    accounts.Employee.department は null=False の必須外部キーだが、Django標準の
    `createsuperuser` は USERNAME_FIELD／REQUIRED_FIELDS（employee_no／name）しか対話
    プロンプトに出さないため、部署が1件も無いフレッシュDBでは department_id の NOT NULL
    制約違反で失敗する。部署管理画面自体もこの最初の管理者が居ないと開けず（権限管理も
    同様）、organizations.Department の Django管理サイト登録は閲覧専用
    （organizations/admin.py DepartmentAdmin(ReadOnlyModelAdmin)）、accounts.Employee は
    管理サイトに未登録のため、通常のUI・管理サイトいずれの経路でもこの循環依存は解けない。
    このコマンドは部署・最初の管理者職員（is_staff/is_superuser=True）・
    PermissionProfile(role=ADMIN) を1回のトランザクションでまとめて作成し、createsuperuser
    の代わりに本番構築手順（環境構築・実装手順書.xlsx シート2／シート5 手順9）で使う。
    """

    help = "本番の最初の管理者職員（部署＋職員＋権限プロファイル）を対話式に作成する。"

    def handle(self, *args, **options):
        if Employee.objects.exists():
            raise CommandError(
                "既に職員が1件以上登録されています。このコマンドは最初の管理者作成専用のため"
                "中断しました。2人目以降の職員登録は職員マスタ画面（/accounts/staff/regist/）を"
                "使ってください。"
            )

        self.stdout.write("=== 最初の管理者職員のブートストラップ ===")
        self.stdout.write("部署の情報を入力してください（本支所のみで部課が無い場合、部課コード・部課名は空欄で構いません）。")
        branch_code = self._prompt_required("本支所コード")
        branch_name = self._prompt_required("本支所名")
        section_code = self._prompt("部課コード")
        section_name = self._prompt("部課名")

        self.stdout.write("")
        self.stdout.write("管理者職員の情報を入力してください。")
        employee_no = self._prompt_employee_no()
        name = self._prompt_required("氏名")
        rank = self._prompt_choice("職階", Rank.choices)
        position = self._prompt_choice("役職", Position.choices)
        password = self._prompt_password(employee_no, name)

        try:
            with transaction.atomic():
                department, created = Department.objects.get_or_create(
                    branch_code=branch_code,
                    section_code=section_code,
                    defaults={"branch_name": branch_name, "section_name": section_name},
                )
                if created:
                    logger.info("部署を作成しました（ブートストラップ）: %s", department)
                else:
                    self.stdout.write(
                        self.style.WARNING(
                            f"本支所コード={branch_code}・部課コード={section_code}の部署は"
                            f"既に存在するため再利用します: {department}"
                        )
                    )

                employee = Employee.objects.create_superuser(
                    employee_no=employee_no,
                    name=name,
                    password=password,
                    department=department,
                    rank=rank,
                    position=position,
                )
                PermissionProfile.objects.create(employee=employee, role=PermissionRole.ADMIN)
        except DjangoDbError:
            # 例：職員番号・部署のunique制約に、対話入力後のごく短い間隙で別プロセスが先に同じ値を
            # 登録した場合のレースコンディション。事前チェック（_prompt_employee_no等）はあくまで
            # check-then-actであり、この例外捕捉が最終防衛線になる。
            logger.exception("最初の管理者職員のブートストラップに失敗しました: employee_no=%s", employee_no)
            raise CommandError("作成に失敗しました。ログを確認してください（データベースへの変更はロールバックされています）。")

        logger.info("最初の管理者職員を作成しました: employee_no=%s", employee_no)
        self.stdout.write(self.style.SUCCESS(f"管理者職員（職員番号={employee_no}・{name}）を作成しました。"))

    # --- prompt helpers ---

    def _prompt(self, label):
        return input(f"{label}: ").strip()

    def _prompt_required(self, label):
        while True:
            value = self._prompt(label)
            if value:
                return value
            self.stderr.write(self.style.ERROR(f"{label}は必須です。"))

    def _prompt_employee_no(self):
        while True:
            value = self._prompt_required("職員番号（半角数字）")
            if not value.isdigit():
                self.stderr.write(self.style.ERROR("職員番号は半角数字のみで入力してください。"))
                continue
            if Employee.objects.filter(employee_no=value).exists():
                self.stderr.write(self.style.ERROR("この職員番号は既に使われています。"))
                continue
            return value

    def _prompt_choice(self, label, choices):
        options = "  ".join(f"{code}:{text}" for code, text in choices)
        while True:
            self.stdout.write(f"{label}の選択肢 - {options}")
            value = self._prompt_required(f"{label}（コードを入力）")
            if value in dict(choices):
                return value
            self.stderr.write(self.style.ERROR("一覧に無いコードです。"))

    def _prompt_password(self, employee_no, name):
        # UserAttributeSimilarityValidatorはuser_attributes（既定でusername/first_name/
        # last_name/email）をgetattr(..., None)で参照するだけなので、Employeeに無い属性でも
        # 例外にはならない（未保存インスタンスで十分）。
        dummy_user = Employee(employee_no=employee_no, name=name)
        while True:
            password = getpass.getpass("パスワード: ")
            confirm = getpass.getpass("パスワード（確認）: ")
            if password != confirm:
                self.stderr.write(self.style.ERROR("パスワードが一致しません。"))
                continue
            try:
                validate_password(password, dummy_user)
            except DjangoValidationError as exc:
                for message in exc.messages:
                    self.stderr.write(self.style.ERROR(message))
                continue
            return password
