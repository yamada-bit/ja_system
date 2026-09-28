"""core.models.ConsumedFormToken（二重送信対策トークンの消費記録、core.double_submit.
consume_token()のTOCTOU対策）のうち、settings.DOUBLE_SUBMIT_TOKEN_RETENTION_HOURSより古い
行を物理削除するバッチコマンド。

消費記録は「同じトークンが二度使われていないか」をDBのユニーク制約で判定するためだけの行で、
セッション側では既にissue_token()の再発行で無効化・上書き済みのため、一定時間より古い行は
再送信検知の役目を終えており安全に削除できる（core.models.ConsumedFormTokenのdocstring参照）。

Windowsタスクスケジューラから日次で実行する想定（core.management.commands.
purge_expired_audit_logsと同じ運用方式。頻繁な実行は不要）。
"""
import logging

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import ConsumedFormToken

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "保存期間(DOUBLE_SUBMIT_TOKEN_RETENTION_HOURS)を過ぎた二重送信対策トークン消費記録を物理削除する。"

    def handle(self, *args, **options):
        cutoff = timezone.now() - timezone.timedelta(hours=settings.DOUBLE_SUBMIT_TOKEN_RETENTION_HOURS)
        # AuditLogの物理削除（purge_expired_audit_logs）と同じ理由でファイル実体を伴わず部分失敗
        # 要因も無いため、バルクdelete()で問題ない。
        deleted, _ = ConsumedFormToken.objects.filter(consumed_at__lt=cutoff).delete()
        logger.info("二重送信対策トークン消費記録の物理削除を実行しました: cutoff=%s 削除=%s件", cutoff, deleted)
        self.stdout.write(f"二重送信対策トークン消費記録の物理削除完了: {deleted}件（{cutoff}より前）")
