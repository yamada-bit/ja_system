import datetime
import logging

from django.conf import settings
from django.db import transaction

from audit import services as audit_services
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

    部署スコープ外pkへの直打ちアクセス試行はlogger.warningに加えて操作履歴ログ（audit）へも
    記録する（`on_denied`、review_rule_doc_contract.txt No.1、2026-09-09ユーザー確定）。
    """
    return scoping_services.scoped_get_object_or_404(
        base_qs,
        employee,
        pk,
        dept_ids_resolver=contract_searchable_department_ids,
        entity_name="契約書",
        on_denied=lambda: audit_services.log_denied_cross_department_access(
            employee=employee, entity_name="契約書", pk=pk
        ),
    )


def build_zip_archive(contracts) -> tuple[bytes, int]:
    """documents.services.build_zip_archiveと同じ考え方（詳細はそちらのdocstring参照）。
    views.BulkDownloadView.postのZIP構築を分離する（規約準拠監査で発見：documents側は既に
    分離済みだったが、contracts側は同型のビジネスロジックがビューに直書きされたまま
    残っていた。2026-08-25修正）。実体はcore.zip_services.build_zip_archiveに集約済み
    （documents.services.build_zip_archiveとの重複をコード監査で発見、2026-08-25修正）。
    """
    return zip_services.build_zip_archive(contracts, entity_label="contract")


def apply_contract_edit(contract, cleaned_data, employee, related_ids):
    """編集フォーム（`UploadStep2Form`, edit_mode=True）のcleaned_dataをcontractに反映して保存する。
    `contracts.views.ContractEditView.post`と一括編集`BulkEditView.post`の両方から呼ばれる
    共通処理（documents.services.apply_document_editと同じ位置付け）。関連書類（紐付け先契約書）の
    同期も本体保存と同じトランザクションにまとめる。DB境界の例外（DBError）は握りつぶさず
    そのまま呼び出し元に伝播させる（単体編集とBulkEditViewとで失敗時に取るべき応答が異なるため）。

    `related_ids` は「この契約書に紐付けたい契約書pkの並び順つき全量リスト」（差分ではない）。
    Rev1.5までのRelatedFile方式（add/removeの差分＋物理ファイルI/O）から、Rev1.6の「ポップアップ
    検索で選び直した結果を丸ごと確定する」方式に合わせて全量同期にした。呼び出し側で
    `filter_valid_related_ids()` を通し、実在・閲覧権限内・自分自身でない pk だけに絞ってから渡すこと。

    `expiry_date`（保存満了日）は編集時に一切触らない。契約書は保存期間が選択式ではなく
    `settings.CONTRACT_RETENTION_YEARS`固定で、編集で変えられる要素が無いため引き直す理由が
    無い（文書側`apply_document_edit`が「保存期間変更時のみ引き直す」に整理されたのと同じ考え方。
    2026-08-28ユーザー確定、レビュー指摘C-1）。
    """
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
        sync_related_contracts(contract, related_ids)
    return contract


def sync_related_contracts(contract, related_ids):
    """`contract` の関連書類（ContractRelation）を `related_ids`（並び順つき全量リスト）に一致させる。
    リストから外れた行は削除、新規は追加、既存は `display_order` を並び順に合わせる。
    呼び出し側で `filter_valid_related_ids()` を通したpkリストを渡す前提（重複除去・順序保持済み）。
    """
    from contracts.models import ContractRelation

    ContractRelation.objects.filter(contract=contract).exclude(
        related_contract_id__in=related_ids
    ).delete()
    existing = {
        r.related_contract_id: r
        for r in ContractRelation.objects.filter(contract=contract)
    }
    for order, rid in enumerate(related_ids):
        row = existing.get(rid)
        if row is None:
            ContractRelation.objects.create(
                contract=contract, related_contract_id=rid, display_order=order
            )
        elif row.display_order != order:
            row.display_order = order
            row.save(update_fields=["display_order"])


def filter_valid_related_ids(ids, *, employee, exclude_pk=None, keep_ids=None):
    """関連書類として紐付けてよい契約書pkだけに絞る（並び順は維持、重複は除去）。

    ポップアップ検索API（`contracts.api.RelatedSearchAPIView`）は元々「閲覧権限内・削除されて
    いない・自分自身でない」契約書しか返さないが、hidden inputは生POST値なので改ざんで任意の
    pkが混入し得る。保存前にサーバー側でも同じ条件で検証し、外れた値は不正アクセス試行の兆候
    として警告ログに残す（`core.bulk_edit_services.resolve_ordered_pks` と同じ方針）。

    `keep_ids`（＝この契約書に既に紐付いている契約書pkの集合）に含まれるpkは、論理削除済みで
    閲覧範囲外検索から選び直せなくなっていても、入力リストに残っている限り維持する。紐付け時に
    一度検証済みであり、`ContractRelation` docstring「論理削除（is_deleted=True）の場合は行は
    残る」に従うため。これが無いと、削除済み関連書類を持つ契約書を別項目編集しただけで
    紐付けが黙って消え、かつ正常操作なのに「紐付け不可」警告ログが毎回残っていた
    （コードレビュー A No.1、2026-09-09。単独編集・一括編集の両経路で発生していた）。
    """
    from contracts.models import Contract

    keep_ids = {int(k) for k in keep_ids} if keep_ids else set()

    int_ids = []
    for raw in ids:
        try:
            int_ids.append(int(raw))
        except (TypeError, ValueError):
            logger.warning("関連書類の指定に非数値が含まれていたため除外しました: value=%r", raw)

    allowed_department_ids = contract_searchable_department_ids(employee)
    qs = Contract.objects.filter(pk__in=int_ids, is_deleted=False)
    if allowed_department_ids is not None:
        qs = qs.filter(department_id__in=allowed_department_ids)
    if exclude_pk is not None:
        qs = qs.exclude(pk=exclude_pk)
    valid = set(qs.values_list("pk", flat=True))

    seen = set()
    result = []
    for pk in int_ids:
        if pk in seen:
            continue
        seen.add(pk)
        # exclude_pk（自分自身）は keep_ids に入っていても必ず除外する。
        if pk != exclude_pk and (pk in valid or pk in keep_ids):
            result.append(pk)
        else:
            logger.warning("紐付け不可の契約書pkが関連書類に指定されたため除外しました: pk=%s", pk)
    return result


def contract_edit_is_dirty(contract, cleaned_data, employee, *, related_changed=False) -> bool:
    """documents.services.document_edit_is_dirtyの契約書版（2026-08-28ユーザー確定：一括編集の
    「更新」で変更が無いページは「更新なし」とする）。`apply_contract_edit`と同じ`department`
    正規化を行った上で全コピー対象フィールドを比較し、加えて関連書類の増減（`related_changed`）が
    あれば dirty とみなす。
    """
    department = cleaned_data["department"]
    if not can_select_department(employee):
        department = employee.department
    return (
        related_changed
        or contract.title != cleaned_data["title_0"]
        or contract.department_id != department.pk
        or contract.group_id != cleaned_data["group"].pk
        or contract.category_id != cleaned_data["category"].pk
        or contract.year != cleaned_data["year"]
        or contract.contract_date != cleaned_data["contract_date"]
        or contract.contract_period_start != cleaned_data["contract_period_start"]
        or contract.contract_period_end != cleaned_data["contract_period_end"]
        or contract.renewal_date != cleaned_data["renewal_date"]
        or contract.contract_amount != cleaned_data["contract_amount"]
        or (contract.contract_partner or "") != (cleaned_data["contract_partner"] or "")
        or (contract.memo or "") != (cleaned_data["memo"] or "")
    )


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
