import datetime
import logging

from django.conf import settings
from django.db import transaction

from core import deletion_services, scoping_services, zip_services
from permissions.services import can_select_department, contract_searchable_department_ids

logger = logging.getLogger(__name__)


def can_delete(contract) -> bool:
    """documents.services.can_deleteと同じ考え方（詳細はそちらのdocstring参照。Rev1.2で
    削除済み契約書はボタン非表示に統一、完全削除機能は廃止した）。
    実体はcore.deletion_services.can_deleteに集約済み（documents.services.can_deleteとの重複を
    コード監査で発見、2026-08-25修正）。
    """
    return deletion_services.can_delete(contract)


def deletion_denial_message(contract) -> str:
    """documents.services.deletion_denial_messageと同じ考え方（詳細はそちらのdocstring参照）。
    実体はcore.deletion_services.deletion_denial_messageに集約済み（documents.services.
    deletion_denial_messageとの重複をコード監査で発見、2026-08-25修正）。
    """
    return deletion_services.deletion_denial_message(contract, entity_name="契約書")


def scoped_get_object_or_404(base_qs, employee, pk):
    """契約書の詳細操作（ダウンロード・プレビュー・編集・削除・一括編集）で、部署スコープ
    （`permissions.services.contract_searchable_department_ids`）外のpkへのURL直打ちを404にしつつ、
    セキュリティ上意味のある事象としてlogger.warningに残す共通ヘルパー。

    セキュリティレビューで発見：`contracts.api.DetailAPIView`・検索一覧
    （`contracts.search_services.build_queryset`）は部署スコープを適用済みだったが、
    `DownloadView`/`PreviewView`/`ContractEditView`/`DeleteView`/一括編集の各ビューには
    適用されておらず、`contract_download`/`contract_edit`権限さえあれば部署をまたいだ
    直接pkアクセスで他部署の契約書を閲覧・編集・削除できてしまっていた（2026-08-25修正）。

    実体はcore.scoping_services.scoped_get_object_or_404に集約済み（documents.services.
    scoped_get_object_or_404との重複をコード監査で発見、2026-08-25修正）。
    """
    return scoping_services.scoped_get_object_or_404(
        base_qs, employee, pk, dept_ids_resolver=contract_searchable_department_ids, entity_name="契約書"
    )


def build_zip_archive(contracts) -> tuple[bytes, int]:
    """documents.services.build_zip_archiveと同じ考え方（詳細はそちらのdocstring参照）。
    views.BulkDownloadView.postのZIP構築を分離する（規約準拠監査で発見：documents側は既に
    分離済みだったが、contracts側は同型のビジネスロジックがビューに直書きされたまま
    残っていた。2026-08-25修正）。実体はcore.zip_services.build_zip_archiveに集約済み
    （documents.services.build_zip_archiveとの重複をコード監査で発見、2026-08-25修正）。
    """
    return zip_services.build_zip_archive(contracts, entity_label="contract")


def apply_contract_edit(contract, cleaned_data, employee, remove_ids, new_related_files):
    """編集フォーム（`UploadStep2Form`, edit_mode=True）のcleaned_dataをcontractに反映して保存する。
    `contracts.views.ContractEditView.post`と一括編集`BulkEditView.post`の両方から呼ばれる
    共通処理（documents.services.apply_document_editと同じ位置付け）。関連書類の追加・削除も
    本体保存と同じトランザクションにまとめる（元のContractEditView.postの設計をそのまま踏襲）。
    ファイルI/O・DB境界の例外（OSError/DBError）は握りつぶさずそのまま呼び出し元に伝播させる。
    単体編集とBulkEditViewとでは失敗時に取るべき応答（リダイレクトvs同じステップの再描画）が
    異なるため、対応は呼び出し側の責務とする。
    """
    from contracts.models import RelatedFile

    department = cleaned_data["department"]
    if not can_select_department(employee):
        department = employee.department

    contract.title = cleaned_data["title_0"]
    contract.department = department
    contract.group = cleaned_data["group"]
    contract.category = cleaned_data["category"]
    contract.year = cleaned_data["year"]
    contract.contract_date = cleaned_data["contract_date"]
    contract.contract_period_start = cleaned_data["contract_period_start"]
    contract.contract_period_end = cleaned_data["contract_period_end"]
    contract.renewal_date = cleaned_data["renewal_date"]
    contract.contract_amount = cleaned_data["contract_amount"]
    contract.contract_partner = cleaned_data["contract_partner"]
    contract.memo = cleaned_data["memo"]

    with transaction.atomic():
        contract.save()
        if remove_ids:
            RelatedFile.objects.filter(contract=contract, pk__in=remove_ids).delete()
        if new_related_files:
            next_order = RelatedFile.objects.filter(contract=contract).count()
            for i, related in enumerate(new_related_files):
                RelatedFile.objects.create(contract=contract, file=related, display_order=next_order + i)
    return contract


def parse_remove_related_ids(raw_value, *, employee_no):
    """remove_related_ids（JS側でhidden inputにカンマ区切りで積まれる想定）を数値のリストに
    変換する。フォーム改ざんで非数値が混じってもpk__inクエリの評価時に例外を出さないよう、
    数値変換できるものだけ採用し、できなかったものは不正アクセス試行の兆候としてログに残す
    （元のContractEditView.postのロジックをBulkEditViewと共有するために抽出）。
    """
    remove_ids = []
    for raw_id in [i for i in raw_value.split(",") if i]:
        try:
            remove_ids.append(int(raw_id))
        except ValueError:
            logger.warning(
                "remove_related_idsに不正な値が指定されました: employee_no=%s, value=%r",
                employee_no,
                raw_id,
            )
    return remove_ids


def calculate_expiry_date(save_date: datetime.date) -> datetime.date:
    """契約書の保存満了日を計算する。documents.services.calculate_expiry_dateと異なり保存期間の
    選択式は無く、`settings.CONTRACT_RETENTION_YEARS`（既定10年、xlsx メイン画面!B48
    「契約書の保存期限は固定で10年」）で一律計算する。
    """
    years = settings.CONTRACT_RETENTION_YEARS
    try:
        return save_date.replace(year=save_date.year + years)
    except ValueError:
        return save_date.replace(month=2, day=28, year=save_date.year + years)
