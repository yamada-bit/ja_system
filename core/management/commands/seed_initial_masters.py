import logging

from django.core.management.base import BaseCommand

from masters.models import RetentionKbn, RetentionPeriod, RetentionPeriodUnit

logger = logging.getLogger(__name__)

# 保存期間設定マスタの初期値（RELEASE_PREP_NOTES.md「2.」）。文書用（kbn=DOCUMENT, doc_name=""）
# のみを対象にする——契約書は保存期間が選択式ではなくsettings.CONTRACT_RETENTION_YEARSで固定年数
# （CLAUDE.md）、電子決裁（kbn=EAPPROVAL）は恒久的にスコープ外の機能のため、いずれもここでは
# 投入しない。表示順は昇順（短い保存期間から長い保存期間、最後に永年）。
_DOCUMENT_RETENTION_SPECS = [
    (1, RetentionPeriodUnit.MONTH, 1),
    (1, RetentionPeriodUnit.YEAR, 2),
    (3, RetentionPeriodUnit.YEAR, 3),
    (5, RetentionPeriodUnit.YEAR, 4),
    (10, RetentionPeriodUnit.YEAR, 5),
    (None, RetentionPeriodUnit.PERMANENT, 6),
]


class Command(BaseCommand):
    """本番の初期マスタデータ（保存期間設定）を投入する（RELEASE_PREP_NOTES.md「2.」）。

    get_or_create によりべき等（再実行しても重複登録しない）。部署・最初の管理者職員は
    循環依存（部署管理・権限管理画面を開くには管理者が必要）があるため対象外——そちらは
    accounts.management.commands.bootstrap_admin が別途担う。職位・職階
    （accounts.Rank/Position）はDjangoのTextChoicesとしてコードに保持するのみで、DBマスタでは
    ないため投入対象そのものが存在しない。
    """

    help = "本番の初期マスタデータ（保存期間設定：文書用1ヵ月/1年/3年/5年/10年/永年）を投入する。"

    def handle(self, *args, **options):
        created_count = 0
        for period_value, period_unit, display_order in _DOCUMENT_RETENTION_SPECS:
            _, created = RetentionPeriod.objects.get_or_create(
                kbn=RetentionKbn.DOCUMENT,
                doc_name="",
                period_value=period_value,
                period_unit=period_unit,
                is_deleted=False,
                defaults={"display_order": display_order},
            )
            if created:
                created_count += 1
                logger.info("保存期間設定を作成しました: %s%s", period_value or "", period_unit)

        if created_count:
            self.stdout.write(self.style.SUCCESS(f"保存期間設定を{created_count}件作成しました。"))
        else:
            self.stdout.write(self.style.WARNING("保存期間設定は既に投入済みのため、新規作成はありませんでした。"))
