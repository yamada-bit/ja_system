import logging

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views import View

from contracts.models import Contract
from contracts.services import can_delete
from contracts.views import PENDING_SESSION_KEY
from core.api import BaseOptionListAPIView
from core.file_type_services import get_preview_kind
from core.notice_services import is_expiring_soon
from core.upload_views import BaseChunkUploadAPIView
from masters.models import DocKbn
from permissions.services import can_download, can_edit_contract, contract_searchable_department_ids

logger = logging.getLogger(__name__)


class OptionListAPIView(BaseOptionListAPIView):
    doc_kbn = DocKbn.CONTRACT
    visible_groups_kind = "contract"
    department_kind = "contract"


class ChunkUploadAPIView(BaseChunkUploadAPIView):
    """screen-storage1（契約書）のチャンク分割アップロードAPI。documents側と同様
    PENDING_SESSION_KEYはcontracts.views.UploadStep1Viewと同一のセッションキーを使う。"""

    pending_session_key = PENDING_SESSION_KEY


class DetailAPIView(LoginRequiredMixin, View):
    """popup-detail（契約書詳細プロパティ）用のJSON API。"""

    def get(self, request, pk):
        contract = get_object_or_404(
            Contract.objects.select_related("department", "group", "category", "uploader").prefetch_related(
                "related_files"
            ),
            pk=pk,
        )
        allowed_department_ids = contract_searchable_department_ids(request.user)
        if allowed_department_ids is not None and contract.department_id not in allowed_department_ids:
            logger.warning(
                "他部署の契約書への不正アクセス試行: employee_no=%s contract_id=%s",
                request.user.employee_no,
                pk,
            )
            raise PermissionDenied("この契約書を閲覧する権限がありません。")

        is_expired = contract.expiry_date < timezone.localdate()
        can_dl = can_download(request.user, kind="contract")
        can_edit = can_edit_contract(request.user)
        soon = is_expiring_soon(contract.expiry_date)
        return JsonResponse(
            {
                "title": contract.title,
                "department": str(contract.department),
                "group": contract.group.name,
                "category": contract.category.name,
                "year": contract.year,
                "contract_date": str(contract.contract_date) if contract.contract_date else "",
                "contract_period_start": str(contract.contract_period_start) if contract.contract_period_start else "",
                "contract_period_end": str(contract.contract_period_end) if contract.contract_period_end else "",
                "renewal_date": str(contract.renewal_date) if contract.renewal_date else "",
                "contract_amount": str(contract.contract_amount) if contract.contract_amount else "",
                "contract_partner": contract.contract_partner,
                "expiry_date": str(contract.expiry_date),
                "memo": contract.memo,
                "related_files": [rf.display_name for rf in contract.related_files.all()],
                "uploader": contract.uploader.name,
                # documents.api.DetailAPIViewと同じ理由（xlsx検索・閲覧画面の詳細ポップアップ
                # 「保存日時」欄、Rev1.1で追加）。
                "save_date": timezone.localtime(contract.save_date).strftime("%Y-%m-%d %H:%M:%S"),
                "updated_at": contract.updated_at.isoformat(),
                "is_expired": is_expired,
                "is_expiring_soon": soon,
                "is_deleted": contract.is_deleted,
                "can_download": can_dl,
                # documents.api.DetailAPIViewと同じ理由（削除済み契約書に対してedit_urlを渡すと
                # 変更が404になる）に加え、xlsx 権限管理!B193-198(Rev1.2)「契約書-契約書-契約書情報
                # 変更」がOFFの場合は編集不可（編集画面自体もContracts.views.ContractEditViewで
                # 同じ権限チェックをサーバー側で行う）。
                "edit_url": (
                    reverse("contracts:edit", args=[contract.pk])
                    if not contract.is_deleted and can_edit
                    else None
                ),
                "download_url": reverse("contracts:download", args=[contract.pk]) if can_dl else None,
                # documents.api.DetailAPIViewと同じ理由（詳細ポップアップの実プレビュー表示用、
                # 2026-08-13ユーザー報告対応でpreview_kindは権限に関わらず返すよう変更）。
                "preview_url": reverse("contracts:preview", args=[contract.pk]) if can_dl else None,
                "preview_kind": get_preview_kind(contract.display_name),
                # xlsx 検索・閲覧・変更!B331,B337,B659,B663(Rev1.2)「削除済み、または初回登録から
                # 1週間以上経過しているものは削除不可・ボタン非表示」に加え、B198「契約書-契約書-
                # 契約書情報変更」がOFFの場合も削除不可にする（xlsx B198「編集不可…検索・閲覧画面の
                # 検索結果一覧の明細ダブルクリック後に開く契約書詳細画面の「編集」「削除」ボタンを
                # 非表示にする」）。
                "delete_url": (
                    reverse("contracts:delete", args=[contract.pk]) if can_delete(contract) and can_edit else None
                ),
            }
        )
