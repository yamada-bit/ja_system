import logging

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views import View

from core.api import BaseOptionListAPIView
from core.file_type_services import get_preview_kind
from core.notice_services import is_expiring_soon
from core.upload_views import BaseChunkUploadAPIView
from documents.models import Document
from documents.services import can_delete
from documents.views import PENDING_SESSION_KEY
from masters.models import DocKbn
from permissions.services import can_download, can_select_department

logger = logging.getLogger(__name__)


class OptionListAPIView(BaseOptionListAPIView):
    doc_kbn = DocKbn.DOCUMENT
    visible_groups_kind = "document"


class ChunkUploadAPIView(BaseChunkUploadAPIView):
    """screen-storage1（文書）のチャンク分割アップロードAPI。PENDING_SESSION_KEYは
    documents.views.UploadStep1Viewが読み書きしているセッションキーと同一にする必要がある。"""

    pending_session_key = PENDING_SESSION_KEY


class DetailAPIView(LoginRequiredMixin, View):
    """popup-detail（文書詳細プロパティ）用のJSON API。screen-searchの一覧ダブルクリックで
    JSがfetchし、ポップアップに描画する。"""

    def get(self, request, pk):
        document = get_object_or_404(
            Document.objects.select_related("department", "group", "category", "retention_period", "uploader"),
            pk=pk,
        )
        if not can_select_department(request.user) and document.department_id != request.user.department_id:
            logger.warning(
                "他部署の文書への不正アクセス試行: employee_no=%s document_id=%s",
                request.user.employee_no,
                pk,
            )
            raise PermissionDenied("この文書を閲覧する権限がありません。")

        is_expired = document.expiry_date < timezone.localdate()
        can_dl = can_download(request.user, kind="document")
        soon = is_expiring_soon(document.expiry_date)
        return JsonResponse(
            {
                "title": document.title,
                "department": str(document.department),
                "group": document.group.name,
                "category": document.category.name,
                "year": document.year,
                "retention_period": str(document.retention_period),
                "expiry_date": str(document.expiry_date),
                "privacy_flag": document.privacy_flag,
                "memo": document.memo,
                "uploader": document.uploader.name,
                # xlsx検索・閲覧画面の詳細ポップアップ「保存日時」欄用（Rev1.1で追加）。
                # 原本モック表示（"2026-01-20 09:34:06"）に合わせてローカル時刻で整形して返す。
                "save_date": timezone.localtime(document.save_date).strftime("%Y-%m-%d %H:%M:%S"),
                "updated_at": document.updated_at.isoformat(),
                "is_expired": is_expired,
                "is_expiring_soon": soon,
                "is_deleted": document.is_deleted,
                "can_download": can_dl,
                # edit_urlはis_deleted=Trueの間はNoneにする（監査で発見：
                # DocumentEditView.get_object()はis_deleted=Falseでしか対象を取得できないため、
                # 削除済み文書に対してURLを渡すと変更が404になっていた。common.jsの
                # renderDetailPopup()側でもdata.is_deletedを見てボタンをdisabledにするが、
                # can_download/download_urlと同じ考え方でAPI側でもNoneにしておく）。
                "edit_url": reverse("documents:edit", args=[document.pk]) if not document.is_deleted else None,
                # download_urlもxlsx 検索・閲覧・変更!B331(Rev1.2)「削除されている(削除フラグが
                # True)文書は、ボタンを非表示とする」に従いis_deletedをgatingに加える（監査で発見：
                # 以前はcan_download権限のみを見ており、削除済み文書でもダウンロードボタンが
                # 表示され続けていた。documents.views.DownloadView側もis_deleted=Falseに揃えて
                # URL直打ち対策済み）。
                "download_url": (
                    reverse("documents:download", args=[document.pk])
                    if can_dl and not document.is_deleted
                    else None
                ),
                # 詳細ポップアップの実プレビュー表示用（ユーザー依頼2026-08-12で追加）。
                # preview_urlは実データを指すためcan_download権限でgatingするが、preview_kind
                # （拡張子判定）は権限に関わらず返す。common.jsのrenderDetailPopup()側で
                # 「画像／PDFなのに権限不足で見せられない」ケースを判別し、権限不足である旨を
                # 明示するために必要（2026-08-13ユーザー報告対応。documents/views._pending_preview_
                # contextと同じ考え方）。
                "preview_url": reverse("documents:preview", args=[document.pk]) if can_dl else None,
                "preview_kind": get_preview_kind(document.display_name),
                # delete_urlはis_deleted=Trueの間は常に返す（DeleteView.postがis_deleted=False
                # なら論理削除、is_deleted=Trueなら完全削除、と対象の状態に応じて分岐するため。
                # ユーザー依頼2026-08-12：ゴミ箱保管中の文書は削除ボタンで完全削除できるようにした）。
                # is_deleted=Falseの場合はxlsx「初回登録から1週間以上経過しているものは削除不可、
                # ボタンを非表示にする」（documents.services.can_delete）に従いNoneにする。
                "delete_url": reverse("documents:delete", args=[document.pk]) if can_delete(document) else None,
            }
        )
