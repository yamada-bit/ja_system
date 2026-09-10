"""操作履歴ログ(audit.AuditLog)のうち、保存期間を過ぎたものをDBレコードごと物理削除する
バッチコマンド。

xlsx 操作履歴ログ!B51-52「操作履歴ログの最大保存件数(=CSV出力最大件数)設定値は、初期値を
3ヵ月分とし、設定ファイル等で定義し、先方より変更依頼を受けた際に容易に変更できること」に対応する。
「3ヵ月分」は`settings.AUDIT_LOG_RETENTION_MONTHS`（.env経由、既定3ヵ月）で表現し、下限日は
`audit.services.retention_cutoff_date()`に集約している（一覧表示・CSV出力の絞り込みと同一の下限）。

Windowsタスクスケジューラから日次で実行する想定（core.management.commands.
purge_expired_deleted_recordsと同じ運用方式。頻繁な実行は不要）。
"""
import logging

from django.core.management.base import BaseCommand

from audit.models import AuditLog
from audit.services import retention_cutoff_date, retention_cutoff_datetime

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "保存期間(AUDIT_LOG_RETENTION_MONTHS)を過ぎた操作履歴ログを物理削除する。"

    def handle(self, *args, **options):
        cutoff = retention_cutoff_date()
        # 文書・契約書の物理削除（purge_expired_deleted_records）と違い、AuditLogはファイル実体を
        # 伴わず、1件ずつのファイルI/O失敗のような部分失敗要因が無いため、バルクdelete()で問題ない。
        # DATE() キャストを挟まない timestamp__lt で Index(fields=["-timestamp"]) を効かせる
        # （filter_audit_log_queryset の下限と同値。コードレビュー audit/core No.5）。
        deleted, _ = AuditLog.objects.filter(timestamp__lt=retention_cutoff_datetime()).delete()
        # この物理削除イベント自体は操作履歴ログに記録しない：記録しても次回以降のパージ対象に
        # なって増えるだけで追跡価値が乏しく、かつ「操作」ではなく保守バッチのため。運用ログには残す。
        logger.info("操作履歴ログの物理削除を実行しました: cutoff=%s 削除=%s件", cutoff, deleted)
        self.stdout.write(f"操作履歴ログ物理削除完了: {deleted}件（{cutoff}より前）")
