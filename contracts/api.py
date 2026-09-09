import logging

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views import View

from audit import services as audit_services
from contracts.models import Contract
from contracts.services import can_delete
from contracts.views import PENDING_SESSION_KEY, RequiresContractEditMixin
from core import search_services
from core.api import BaseOptionListAPIView
from core.file_type_services import get_preview_kind
from core.forms import MATCH_AND, MATCH_OR
from core.notice_services import is_expiring_soon
from core.upload_views import BaseChunkUploadAPIView
from masters.models import DocKbn
from permissions.services import can_download, can_edit_contract, contract_searchable_department_ids

# 関連書類ポップアップ検索の1回あたり最大返却件数（xlsx 保管!B480「簡易的に検索」に沿って
# 大量ヒット時も上限で打ち切る。popup-select の一覧描画コストの目安に合わせた）。
RELATED_SEARCH_LIMIT = 50

logger = logging.getLogger(__name__)


class OptionListAPIView(BaseOptionListAPIView):
    doc_kbn = DocKbn.CONTRACT
    visible_groups_kind = "contract"
    department_kind = "contract"


class ChunkUploadAPIView(RequiresContractEditMixin, BaseChunkUploadAPIView):
    """screen-storage1（契約書）のチャンク分割アップロードAPI。documents側と同様
    PENDING_SESSION_KEYはcontracts.views.UploadStep1Viewと同一のセッションキーを使う。

    UploadStep1View/UploadStep2Viewは`can_edit_contract`でサーバー側アクセス制御しているが、
    このAPIはBaseChunkUploadAPIView（documents側と共有、documentsには契約書のような
    保存・編集権限フラグが無いためLoginRequiredMixinのみ）をそのまま継承しており、
    契約書側で追加された`contract_edit`権限チェックが漏れていた（コード監査で発見、
    2026-08-24修正）。UploadStep1View等と同じ判定をcontracts.views.RequiresContractEditMixin
    経由で共有する（2026-08-25修正、詳細は同ミックスインのdocstring参照）。
    """

    pending_session_key = PENDING_SESSION_KEY


class DetailAPIView(LoginRequiredMixin, View):
    """popup-detail（契約書詳細プロパティ）用のJSON API。"""

    def get(self, request, pk):
        contract = get_object_or_404(
            Contract.objects.select_related("department", "group", "category", "uploader").prefetch_related(
                "related_links__related_contract"
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
            # このビューはscoped_get_object_or_404を経由せず部署スコープ判定を直書きしているため、
            # 操作履歴ログ（audit）への記録もここで明示的に行う（review_rule_doc_contract.txt No.1、
            # 2026-09-09ユーザー確定。contracts.services.scoped_get_object_or_404側と同じ扱い）。
            audit_services.log_denied_cross_department_access(
                employee=request.user, entity_name="契約書", pk=pk
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
                # 契約金額0円は有効な入力。`if contract.contract_amount`だとDecimal('0')がfalsyで
                # 未入力(None)と区別できず金額欄が空表示になるため`is not None`で判定する
                # （コードレビューC-5、2026-08-28修正）。
                "contract_amount": str(contract.contract_amount) if contract.contract_amount is not None else "",
                "contract_partner": contract.contract_partner,
                "expiry_date": str(contract.expiry_date),
                "memo": contract.memo,
                # xlsx 検索・閲覧・変更!B677-680(Rev1.6)「関連資料」：紐付け先契約書1件ごとに
                # {title, is_deleted, preview_url}。preview_url は「削除されておらず、かつダウンロード
                # 権限がある」ときだけ埋める。common.js renderDetailPopup() が
                #  ・preview_url あり  → ファイル名をリンク化しクリックで別タブにPDFプレビュー
                #  ・is_deleted=true   → 赤フォント＋クリックで「既に削除されている関連資料です」
                #  ・どちらでもない    → 素テキスト（権限不足）
                # に振り分ける。
                "related_contracts": [
                    {
                        "title": link.related_contract.title,
                        "is_deleted": link.related_contract.is_deleted,
                        "preview_url": (
                            reverse("contracts:preview", args=[link.related_contract_id])
                            if can_dl and not link.related_contract.is_deleted
                            else None
                        ),
                    }
                    for link in contract.related_links.all()
                ],
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
                # documents.api.DetailAPIViewと同じ理由（xlsx 検索・閲覧・変更!B659(Rev1.2)
                # 「削除されている(削除フラグがTrue)契約書は、ボタンを非表示とする」。監査で発見：
                # 以前はcan_download権限のみを見ており、削除済み契約書でもダウンロードボタンが
                # 表示され続けていた）。
                "download_url": (
                    reverse("contracts:download", args=[contract.pk])
                    if can_dl and not contract.is_deleted
                    else None
                ),
                # documents.api.DetailAPIViewと同じ理由（詳細ポップアップの実プレビュー表示用、
                # 2026-08-13ユーザー報告対応でpreview_kindは権限に関わらず返すよう変更）。
                # download_urlと同じくis_deletedもgatingに加える（品質レビューで発見：documents側
                # と同型の漏れがcontracts側にもあった。contracts.views.PreviewView側もis_deleted=False
                # に揃えてURL直打ち対策済み。2026-08-25修正）。
                "preview_url": (
                    reverse("contracts:preview", args=[contract.pk])
                    if can_dl and not contract.is_deleted
                    else None
                ),
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


class RelatedSearchAPIView(RequiresContractEditMixin, View):
    """関連書類ポップアップ（保管画面２／編集画面の[3]関連書類「ファイルの選択」）用の契約書検索API。

    xlsx 保管!B478-484(Rev1.6)：「関連する(紐付ける)契約書を選択する。既に保存済みの契約書を
    検索してセットする」「検索画面はポップアップ形式とし『契約書タイトル』『フリーワード』で
    簡易的に検索できるものとする」「検索範囲はログインユーザーの閲覧権限範囲と同等とする」。

    - `title` / `freeword` クエリパラメータで絞り込む（両方空なら閲覧範囲の全件を上限まで）。
      マッチ方式は検索画面と揃えず、簡易検索として OR 固定（スペース区切りのいずれかを含む）。
    - `exclude` に自分自身の契約書pkを渡すと結果から外す（編集画面での自己紐付け防止）。
    - 削除済み（is_deleted=True）は対象外。並びは更新日時の新しい順、`RELATED_SEARCH_LIMIT` 件まで。

    保存・編集画面と同じ `RequiresContractEditMixin`（＝「契約書-契約書-契約書情報変更」権限）で
    保護する。閲覧範囲は検索一覧と同じ `contract_searchable_department_ids`。
    """

    def get(self, request):
        qs = Contract.objects.filter(is_deleted=False).select_related("department")
        allowed_department_ids = contract_searchable_department_ids(request.user)
        if allowed_department_ids is not None:
            qs = qs.filter(department_id__in=allowed_department_ids)

        exclude_raw = request.GET.get("exclude", "")
        if exclude_raw:
            try:
                qs = qs.exclude(pk=int(exclude_raw))
            except ValueError:
                logger.warning(
                    "関連書類検索APIに不正なexcludeが指定されました: value=%r user=%s",
                    exclude_raw, request.user.employee_no,
                )

        title = request.GET.get("title", "").strip()
        freeword = request.GET.get("freeword", "").strip()
        if title:
            qs = search_services.apply_word_filter(qs, "title", title, MATCH_OR, match_and=MATCH_AND)
        if freeword:
            qs = search_services.apply_freeword_filter(qs, freeword, MATCH_OR, match_and=MATCH_AND)

        items = [
            {
                "value": c.pk,
                "label": c.title,
                "sub": f"{c.department.section_name}／{c.year}年",
            }
            for c in qs.order_by("-updated_at")[:RELATED_SEARCH_LIMIT]
        ]
        return JsonResponse({"items": items})
