"""ゴミ箱保管中（is_deleted=True）の文書・契約書のうち、削除から一定期間が経過したものを
DBレコード・ファイル実体ごと完全削除するバッチコマンド。

xlsx メイン画面!B50-51(Rev1.2)「＜補足：削除されている文書、契約書について＞
"直近Xヵ月"で設定されているXヵ月が既に経過している文書、契約書は自動的に物理削除を行うこと。」
に対応する。"直近Xヵ月"はメイン画面お知らせ「直近Xヵ月内で削除された」と同じ
settings.NOTICE_DELETED_THRESHOLD_MONTHS を流用する（値の二重管理を避けるため）。

Windowsタスクスケジューラから日次で実行する想定（core.management.commands.
extract_pending_pdf_textと同じ運用方式。全文抽出バッチと異なり物理削除は取り消せないため、
5分間隔のような頻繁な実行ではなく日次を推奨する）。

2026-08-24（Rev1.2反映）：以前はdocuments/contracts.views.DeleteViewの「ゴミ箱保管中の
レコードに削除ボタンを押すと完全削除する」機能（ユーザー依頼2026-08-12）が完全削除の唯一の
経路だったが、xlsx改訂で「削除済みなら削除ボタン自体を非表示にする」仕様に変わったため
その手動経路は廃止し、本バッチによる自動物理削除に一本化した
（documents.services.can_delete/contracts.services.can_delete docstring参照）。
"""
import logging

from django.core.management.base import BaseCommand
from django.db import Error as DBError
from django.utils import timezone

from audit import services as audit_services
from contracts.models import Contract
from core.notice_services import add_months
from documents.models import Document

logger = logging.getLogger(__name__)

# 認証済みEmployeeを経由しないバッチ実行のため、audit_services.log_raw()の職員番号/職員名/部署名には
# 固定のプレースホルダーを使う（accounts.views.LoginView.form_invalidの「(不明)」と同じ考え方）。
BATCH_ACTOR_LABEL = "(自動バッチ)"


class Command(BaseCommand):
    help = "削除済みから一定期間(NOTICE_DELETED_THRESHOLD_MONTHS)が経過した文書・契約書を完全削除する。"

    def handle(self, *args, **options):
        from django.conf import settings

        since = add_months(timezone.localdate(), -settings.NOTICE_DELETED_THRESHOLD_MONTHS)

        doc_purged, doc_failed = self._purge_documents(since)
        contract_purged, contract_failed = self._purge_contracts(since)

        self.stdout.write(
            f"物理削除完了: 文書{doc_purged}件（失敗{doc_failed}件） / "
            f"契約書{contract_purged}件（失敗{contract_failed}件）"
        )

    def _purge_documents(self, since):
        # order_by("pk")で処理順を確定させる（extract_pending_pdf_textと同じ理由）。
        queryset = Document.objects.filter(is_deleted=True, deleted_at__date__lt=since).order_by("pk")
        return self._purge(
            queryset,
            kind="document",
            event_label="文書",
            personal_info_flag_fn=lambda obj: obj.privacy_flag,
        )

    def _purge_contracts(self, since):
        queryset = Contract.objects.filter(is_deleted=True, deleted_at__date__lt=since).order_by("pk")
        return self._purge(
            queryset,
            kind="contract",
            event_label="契約書",
            # 関連書類はRev1.6で既存契約書への参照（ContractRelation）になり物理ファイルを持たない。
            # ContractRelationは両FKとも on_delete=CASCADE なので obj.delete() で自動的に消える
            # （この契約書を related_contract として参照している他契約書の行も同様）。
        )

    def _purge(self, queryset, *, kind, event_label, personal_info_flag_fn=None):
        """is_deleted=Trueのqueryset1件ずつをDBレコード・ファイル実体ごと完全削除する共通処理。
        documents/contractsで構造（クエリ→ループ→ファイル欄退避→delete()→ファイル削除→監査ログ）が
        同一だったため集約した（documents側のprivacy_flagだけ personal_info_flag_fn で差分注入する）。
        ファイル実体は原本の `file` のみ（旧 searchable_file は 2026-09-11 に廃止＝監査 案3、
        OCR座標データ ocr_textdata は DB カラムのため obj.delete() で自動的に消える）。

        1件ずつdelete()する設計は意図的に維持している（バルクdelete()にまとめると、1件のDB制約
        違反等で全体がロールバックされ、ゴミ箱保管中の全対象が一切物理削除されなくなる。日次実行の
        本バッチでは通常数件〜十数件規模のため、1件の異常が他の正常な対象の削除まで巻き込む方が、
        バルク化によるDB往復削減より悪い結果になると判断した）。
        """
        purged = 0
        failed = 0
        for obj in queryset:
            # delete()が成功するとDjangoがインスタンスのpkをNoneにリセットするため、削除後の
            # ログ・ファイル削除呼び出し用に先に控えておく（pk=Noneでログに残ると追跡できなくなる
            # 問題への対処）。
            obj_pk = obj.pk
            file_field = obj.file
            try:
                obj.delete()
            except DBError:
                logger.exception("%sの物理削除に失敗しました: %s_id=%s", event_label, kind, obj_pk)
                failed += 1
                continue
            # documents/contracts.views.DeleteView（廃止前）と同じ理由：DBレコード削除が成功した後に
            # ファイル実体を削除し、ファイル削除の失敗自体はログに残した上で握りつぶす
            # （本処理の主目的はDBレコードを消すことであり孤児ファイルは実害が小さいため）。
            self._delete_file(file_field, kind, obj_pk)
            # documents/contracts.views.DeleteView（廃止前）が完全削除時に残していた監査ログを、
            # 唯一の完全削除経路になった本バッチでも引き続き記録する（CLAUDE.md「監査が必要な
            # イベント...は一元的な記録機構（auditアプリ）を通す」）。
            audit_services.log_raw(
                employee_no=BATCH_ACTOR_LABEL,
                employee_name=BATCH_ACTOR_LABEL,
                department_name=BATCH_ACTOR_LABEL,
                action="物理削除バッチ　完全削除",
                event_message=f"{event_label}「{obj.title}」を完全に削除しました。",
                personal_info_flag=personal_info_flag_fn(obj) if personal_info_flag_fn else False,
            )
            purged += 1
        return purged, failed

    @staticmethod
    def _delete_file(file_field, label, pk):
        try:
            file_field.delete(save=False)
        except OSError:
            logger.exception("物理削除時のファイル実体削除に失敗しました: kind=%s pk=%s", label, pk)
