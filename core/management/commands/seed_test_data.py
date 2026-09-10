import datetime
import logging

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import Employee, Position, Rank
from contracts.models import Contract
from documents.models import Document
from masters.models import (
    Category,
    DocKbn,
    Group,
    RetentionKbn,
    RetentionPeriod,
    RetentionPeriodUnit,
)
from organizations.models import Department, MenuItemSetting
from permissions.models import PermissionProfile, PermissionRole

logger = logging.getLogger(__name__)

# 一覧・検索画面（screen-search/screen-storage2等）の動作確認用。本番投入は想定しない
# （マイグレーションではなくmanagement commandにしているのはこのため）。部署・職員・分類・
# カテゴリーは自然キー（部署コード/職員番号/分類コード等）でget_or_createし、再実行しても
# 重複登録されないようにする。文書・契約書は自然キーを持たないため、タイトル接頭辞
# 「【テストデータ】」の存在有無で既存投入済みかどうかを判定し、再実行時はスキップする。

TEST_DATA_TITLE_PREFIX = "【テストデータ】"

# 実ファイルを開かずにプレビュー欄が最低限崩れないよう、有効なPDF構造の最小サンプルを使う。
MINIMAL_PDF_BYTES = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
    b"xref\n0 4\ntrailer<</Size 4/Root 1 0 R>>\nstartxref\n0\n%%EOF"
)


class Command(BaseCommand):
    help = "一覧・検索画面の動作確認用にダミーの部署・職員・分類・文書・契約書データを登録する"

    def handle(self, *args, **options):
        departments = self._seed_departments()
        self._seed_menu_item_settings(departments)
        employees = self._seed_employees(departments)
        groups, categories = self._seed_masters()
        self._seed_retention_periods()
        retention_periods = list(RetentionPeriod.objects.filter(kbn="document").order_by("display_order"))

        if Document.objects.filter(title__startswith=TEST_DATA_TITLE_PREFIX).exists():
            self.stdout.write(self.style.WARNING("文書のテストデータは投入済みのためスキップします"))
        else:
            self._seed_documents(departments, employees, groups, categories, retention_periods)

        if Contract.objects.filter(title__startswith=TEST_DATA_TITLE_PREFIX).exists():
            self.stdout.write(self.style.WARNING("契約書のテストデータは投入済みのためスキップします"))
        else:
            self._seed_contracts(departments, employees, groups, categories)

        self.stdout.write(self.style.SUCCESS("テストデータ登録が完了しました"))

    def _seed_departments(self):
        specs = [
            ("000", "本店", "01", "総務部"),
            ("000", "本店", "02", "営業部"),
            ("100", "八女支店", "01", "業務課"),
            ("900", "物流センター", "", ""),
        ]
        departments = {}
        for branch_code, branch_name, section_code, section_name in specs:
            dept, created = Department.objects.get_or_create(
                branch_code=branch_code,
                section_code=section_code,
                defaults={"branch_name": branch_name, "section_name": section_name},
            )
            departments[(branch_code, section_code)] = dept
            if created:
                logger.info("部署を作成しました: %s", dept)
        return departments

    def _seed_employees(self, departments):
        honten_somu = departments[("000", "01")]
        honten_eigyo = departments[("000", "02")]
        yame_gyomu = departments[("100", "01")]

        specs = [
            # (employee_no, name, department, rank, position, role, is_retired)
            # 職員番号1（菅 理太郎）は本番では手動作成・パスワード手動運用の管理者だが、フレッシュDBでも
            # seed_test_data だけで動作確認を完結できるよう get_or_create で用意する（既存があればそのまま
            # 使い、パスワード等は上書きしない）。原本HTMLのログインユーザー固定表示「総務部｜菅 理太郎」に
            # 対応する。
            ("1", "菅 理太郎", honten_somu, Rank.KOSAYAKU, Position.KACHO, PermissionRole.ADMIN, False),
            ("9002", "係長 花子", honten_eigyo, Rank.CHOSAYAKU, Position.KAKARICHO, PermissionRole.MANAGER, False),
            ("9003", "一般 次郎", yame_gyomu, Rank.SHUJI, Position.IPPAN, PermissionRole.STAFF, False),
            ("9004", "退職 三郎", honten_somu, Rank.SENNIN, Position.SENNIN, PermissionRole.STAFF, True),
            ("9005", "管理 四郎", honten_somu, Rank.KOSAYAKU, Position.KACHO, PermissionRole.ADMIN, False),
        ]
        employees = {}
        for employee_no, name, department, rank, position, role, is_retired in specs:
            employee, created = Employee.objects.get_or_create(
                employee_no=employee_no,
                defaults={
                    "name": name,
                    "department": department,
                    "rank": rank,
                    "position": position,
                    "is_retired": is_retired,
                },
            )
            if created:
                employee.set_password("TestPass2026!")
                employee.save()
                PermissionProfile.objects.create(employee=employee, role=role)
                logger.info("職員を作成しました: %s", employee)
            employees[employee_no] = employee
        return employees

    def _seed_menu_item_settings(self, departments):
        """メイン画面のボタン表示制御（screen-other-main「メイン画面項目」、通常は設定画面で登録）。
        未設定の部署は全ボタン非表示（xlsx その他設定!B73）＝seed 直後にメイン画面から何も操作
        できないため、動作確認用に電子決裁以外を全て表示にしておく（get_or_create で再実行しても
        既存設定は上書きしない）。"""
        for dept in departments.values():
            MenuItemSetting.objects.get_or_create(
                department=dept,
                defaults={
                    "show_search_document": True,
                    "show_search_contract": True,
                    "show_search_eapproval": False,
                    "show_storage_document": True,
                    "show_storage_contract": True,
                },
            )

    def _seed_retention_periods(self):
        """文書用の保存期間設定（screen-retention-doc、通常は保存期間設定マスタ画面で登録する）。
        seed_test_data だけでフレッシュDBの動作確認を完結させるため、テスト文書 specs が使う
        1年/3年/5年/6年/10年/永年 を用意する（get_or_create で再実行しても重複しない）。"""
        specs = [
            (1, RetentionPeriodUnit.YEAR, 1),
            (3, RetentionPeriodUnit.YEAR, 2),
            (5, RetentionPeriodUnit.YEAR, 3),
            (6, RetentionPeriodUnit.YEAR, 4),
            (10, RetentionPeriodUnit.YEAR, 5),
            (None, RetentionPeriodUnit.PERMANENT, 6),
        ]
        for period_value, period_unit, display_order in specs:
            _, created = RetentionPeriod.objects.get_or_create(
                kbn=RetentionKbn.DOCUMENT,
                doc_name="",
                period_value=period_value,
                period_unit=period_unit,
                is_deleted=False,
                defaults={"display_order": display_order},
            )
            if created:
                logger.info("保存期間設定を作成しました: %s%s", period_value or "", period_unit)

    def _seed_masters(self):
        group_specs = [
            ("A", "分類Ａ", DocKbn.DOCUMENT),
            ("B", "分類Ｂ", DocKbn.DOCUMENT),
            ("CA", "契約分類Ａ", DocKbn.CONTRACT),
            ("CB", "契約分類Ｂ", DocKbn.CONTRACT),
        ]
        groups = {}
        for code, name, doc_kbn in group_specs:
            group, created = Group.objects.get_or_create(
                code=code, is_deleted=False, defaults={"name": name, "doc_kbn": doc_kbn}
            )
            groups[code] = group
            if created:
                logger.info("分類を作成しました: %s", group)

        category_specs = [
            ("001", "一般文書", "A", DocKbn.DOCUMENT),
            ("002", "予算関係文書", "B", DocKbn.DOCUMENT),
            ("C001", "一般契約", "CA", DocKbn.CONTRACT),
            ("C002", "業務委託契約", "CB", DocKbn.CONTRACT),
        ]
        categories = {}
        for code, name, group_code, doc_kbn in category_specs:
            category, created = Category.objects.get_or_create(
                code=code,
                is_deleted=False,
                defaults={"name": name, "group": groups[group_code], "doc_kbn": doc_kbn},
            )
            categories[code] = category
            if created:
                logger.info("カテゴリーを作成しました: %s", category)
        return groups, categories

    def _dummy_file(self, name):
        return ContentFile(MINIMAL_PDF_BYTES, name=name)

    def _seed_documents(self, departments, employees, groups, categories, retention_periods):
        today = timezone.localdate()
        honten_somu = departments[("000", "01")]
        honten_eigyo = departments[("000", "02")]
        yame_gyomu = departments[("100", "01")]

        # (件名サフィックス, 部署, 分類コード, カテゴリーコード, 年, 保存期間, 保存満了日, 個人情報フラグ, メモ, 削除済み, 担当職員)
        specs = [
            ("予算計画書2024", honten_somu, "A", "001", 2024, "3", today - datetime.timedelta(days=10), True,
             "2024年度予算計画に関する資料。予算という単語でのフリーワード検索確認用。", False, "1"),
            ("予算実績報告2025", honten_eigyo, "B", "002", 2025, "1", today + datetime.timedelta(days=20), True,
             "2025年度予算実績の報告書。有効期限切れまで1ヶ月以内の通知確認用。", False, "9002"),
            ("総会議事録2023", honten_somu, "A", "001", 2023, "5", today - datetime.timedelta(days=400), False,
             "定時総会の議事録。保存満了日が過去の「有効期限切れ」表示確認用。", False, "1"),
            ("業務マニュアル2026", yame_gyomu, "B", "002", 2026, "10", today + datetime.timedelta(days=3650), False,
             "業務手順をまとめたマニュアル。個人情報フラグOFFの表示確認用。", False, "9003"),
            ("永年保存規程集", honten_somu, "A", "001", 2020, "6", today + datetime.timedelta(days=18250), True,
             "社内規程集（永年保存）。", False, "1"),
            ("廃棄予定文書2019", honten_eigyo, "B", "002", 2019, "1", today - datetime.timedelta(days=5), True,
             "保存期間満了済みの文書サンプル。", False, "9002"),
            ("削除済み旧年度資料", honten_somu, "A", "001", 2022, "3", today - datetime.timedelta(days=200), False,
             "論理削除済み文書。「直近削除された」通知の確認用。", True, "1"),
            ("八女支店定例資料2026", yame_gyomu, "A", "001", 2026, "1", today + datetime.timedelta(days=15), True,
             "支店の定例会資料。部署フィルタ（部門間閲覧設定）確認用。", False, "9003"),
        ]

        retention_by_str = {str(rp.period_value) if rp.period_value else "permanent": rp for rp in retention_periods}

        created_count = 0
        for suffix, department, group_code, category_code, year, retention_key, expiry_date, privacy_flag, memo, is_deleted, uploader_no in specs:
            retention_period = retention_by_str.get(retention_key) or retention_periods[0]
            doc = Document(
                title=f"{TEST_DATA_TITLE_PREFIX}{suffix}",
                department=department,
                group=groups[group_code],
                category=categories[category_code],
                year=year,
                retention_period=retention_period,
                expiry_date=expiry_date,
                privacy_flag=privacy_flag,
                memo=memo,
                uploader=employees[uploader_no],
                is_deleted=is_deleted,
            )
            doc.file.save(f"{suffix}.pdf", self._dummy_file(f"{suffix}.pdf"), save=False)
            doc.save()
            if is_deleted:
                Document.objects.filter(pk=doc.pk).update(deleted_at=timezone.now() - datetime.timedelta(days=5))
            created_count += 1
        logger.info("文書のテストデータを%d件作成しました", created_count)
        self.stdout.write(f"文書テストデータ: {created_count}件作成")

    def _seed_contracts(self, departments, employees, groups, categories):
        today = timezone.localdate()
        honten_somu = departments[("000", "01")]
        honten_eigyo = departments[("000", "02")]
        yame_gyomu = departments[("100", "01")]

        # (件名サフィックス, 部署, 分類コード, カテゴリーコード, 年, 契約日, 開始, 終了, 更新日, 金額, 契約先, 保存満了日, 削除済み, 担当職員)
        specs = [
            ("業務委託契約2024", honten_somu, "CA", "C001", 2024,
             today - datetime.timedelta(days=300), today - datetime.timedelta(days=300),
             today + datetime.timedelta(days=65), today + datetime.timedelta(days=65),
             1200000, "株式会社サンプル商事", today + datetime.timedelta(days=3285), False, "1"),
            ("保守契約2025", honten_eigyo, "CB", "C002", 2025,
             today - datetime.timedelta(days=100), today - datetime.timedelta(days=100),
             today + datetime.timedelta(days=25), today + datetime.timedelta(days=25),
             580000, "テストシステムズ株式会社", today + datetime.timedelta(days=3550), False, "9002"),
            ("賃貸借契約2019", yame_gyomu, "CA", "C001", 2019,
             today - datetime.timedelta(days=2500), today - datetime.timedelta(days=2500),
             today - datetime.timedelta(days=10), None,
             3000000, "八女不動産株式会社", today - datetime.timedelta(days=10), False, "9003"),
            ("削除済み旧契約2020", honten_somu, "CB", "C002", 2020,
             today - datetime.timedelta(days=2000), today - datetime.timedelta(days=2000),
             today - datetime.timedelta(days=1600), None,
             450000, "旧取引先株式会社", today - datetime.timedelta(days=1600), True, "1"),
        ]

        created_count = 0
        for (suffix, department, group_code, category_code, year, contract_date, period_start, period_end,
             renewal_date, amount, partner, expiry_date, is_deleted, uploader_no) in specs:
            contract = Contract(
                title=f"{TEST_DATA_TITLE_PREFIX}{suffix}",
                department=department,
                group=groups[group_code],
                category=categories[category_code],
                year=year,
                contract_date=contract_date,
                contract_period_start=period_start,
                contract_period_end=period_end,
                renewal_date=renewal_date,
                contract_amount=amount,
                contract_partner=partner,
                expiry_date=expiry_date,
                memo=f"{suffix}のテストデータ。",
                uploader=employees[uploader_no],
                is_deleted=is_deleted,
            )
            contract.file.save(f"{suffix}.pdf", self._dummy_file(f"{suffix}.pdf"), save=False)
            contract.save()
            if is_deleted:
                Contract.objects.filter(pk=contract.pk).update(
                    deleted_at=timezone.now() - datetime.timedelta(days=5)
                )
            created_count += 1
        logger.info("契約書のテストデータを%d件作成しました", created_count)
        self.stdout.write(f"契約書テストデータ: {created_count}件作成")
