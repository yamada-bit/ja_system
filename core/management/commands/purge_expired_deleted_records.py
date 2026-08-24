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

from contracts.models import Contract
from core.notice_services import add_months
from documents.models import Document

logger = logging.getLogger(__name__)


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
        queryset = Document.objects.filter(
            is_deleted=True, deleted_at__date__lt=since
        ).order_by("pk")
        purged = 0
        failed = 0
        for document in queryset:
            file_field = document.file
            searchable_file_field = document.searchable_file
            try:
                document.delete()
            except DBError:
                logger.exception("文書の物理削除に失敗しました: document_id=%s", document.pk)
                failed += 1
                continue
            # documents.views.DeleteView（廃止前）と同じ理由：DBレコード削除が成功した後に
            # ファイル実体を削除し、ファイル削除の失敗自体はログに残した上で握りつぶす
            # （本処理の主目的はDBレコードを消すことであり孤児ファイルは実害が小さいため）。
            self._delete_file(file_field, "document", document.pk)
            if searchable_file_field:
                self._delete_file(searchable_file_field, "document(searchable_file)", document.pk)
            purged += 1
        return purged, failed

    def _purge_contracts(self, since):
        queryset = Contract.objects.filter(
            is_deleted=True, deleted_at__date__lt=since
        ).prefetch_related("related_files").order_by("pk")
        purged = 0
        failed = 0
        for contract in queryset:
            file_field = contract.file
            searchable_file_field = contract.searchable_file
            related_files = list(contract.related_files.all())
            try:
                # RelatedFileはon_delete=CASCADEでDBレコードは一緒に消えるが、ファイル実体までは
                # 自動削除されないため、delete()前に一覧を確保しておく（上のrelated_files）。
                contract.delete()
            except DBError:
                logger.exception("契約書の物理削除に失敗しました: contract_id=%s", contract.pk)
                failed += 1
                continue
            self._delete_file(file_field, "contract", contract.pk)
            if searchable_file_field:
                self._delete_file(searchable_file_field, "contract(searchable_file)", contract.pk)
            for related in related_files:
                self._delete_file(related.file, "contract related_file", contract.pk, related_pk=related.pk)
            purged += 1
        return purged, failed

    @staticmethod
    def _delete_file(file_field, label, pk, related_pk=None):
        try:
            file_field.delete(save=False)
        except OSError:
            logger.exception(
                "物理削除時のファイル実体削除に失敗しました: kind=%s pk=%s related_pk=%s",
                label, pk, related_pk,
            )
