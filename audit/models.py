import logging

from django.db import models

logger = logging.getLogger(__name__)


class AuditLog(models.Model):
    """操作履歴ログ（screen-log-list）。職員番号・部署名・職員名はイベント発生時点のスナップショットを
    そのまま保存する（accounts.Employee/organizations.DepartmentへのFKではなく非正規化テキスト）。
    異動・部署改編・（将来）退職者情報の変更があっても、当時の記録をそのまま保つための設計判断。
    """

    timestamp = models.DateTimeField("操作日時", auto_now_add=True)
    employee_no = models.CharField("職員番号", max_length=20)
    employee_name = models.CharField("職員名", max_length=100)
    department_name = models.CharField("部署名", max_length=200)
    action = models.CharField(
        "操作内容",
        max_length=100,
        help_text="「画面名 ＋ 全角スペース ＋ ボタン名」形式（xlsx 操作履歴ログ!B63）",
    )
    event_message = models.TextField("イベントメッセージ")
    personal_info_flag = models.BooleanField(
        "個人情報",
        default=False,
        help_text="個人情報書類フラグがセットされた文書を扱ったイベントか（xlsx 操作履歴ログ!B43）",
    )

    class Meta:
        db_table = "t_audit_log"
        verbose_name = "操作履歴ログ"
        verbose_name_plural = "操作履歴ログ"
        indexes = [
            models.Index(fields=["-timestamp"]),
        ]

    def __str__(self):
        return f"{self.timestamp} {self.employee_name} {self.action}"
