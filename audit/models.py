import logging

from django.contrib.postgres.indexes import GinIndex, OpClass
from django.db import models
from django.db.models import F, Value
from django.db.models.functions import Replace

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
            # documents.Document/contracts.Contractと同じpg_trgm(gin_trgm_ops)方針をicontains検索に
            # 適用する（品質レビューで発見、無制限に増え続けるテーブルに対しキーワード検索のたびに
            # フルスキャンが発生していた、2026-08-26修正）。
            # employee_nameは core.text_normalization.filter_by_full_name が
            # Replace(Replace(F("employee_name"), "　", ""), " ", "") というスペース除去済みの式で
            # icontains検索するため、素の列に対するGinIndexでは使われない。実際に検索で評価される
            # 式と完全に一致する式インデックスを張る必要がある。
            GinIndex(
                OpClass(
                    Replace(Replace(F("employee_name"), Value("　"), Value("")), Value(" "), Value("")),
                    name="gin_trgm_ops",
                ),
                name="auditlog_employee_name_trgm",
            ),
            # event_messageはfilter_audit_log_querysetでスペース区切りAND複数icontainsを行うのみで
            # 変換式を挟まないため、素の列へのGinIndexで足りる。
            GinIndex(fields=["event_message"], name="auditlog_event_message_trgm", opclasses=["gin_trgm_ops"]),
        ]

    def __str__(self):
        return f"{self.timestamp} {self.employee_name} {self.action}"
