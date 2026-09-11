import logging

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import Error as DBError, transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import UpdateView

from audit import services as audit_services
from contracts.forms import SearchForm, UploadStep2Form
from contracts.models import Contract
from contracts.search_services import build_queryset
from contracts.services import (
    apply_contract_edit,
    build_zip_archive,
    calculate_expiry_date,
    contract_edit_is_dirty,
    filter_valid_related_ids,
    scoped_get_object_or_404,
    sync_related_contracts,
)
from core import (
    bulk_edit_services,
    bulk_edit_views,
    deletion_services,
    record_views,
    search_services,
    upload_services,
    upload_views,
)
from core.double_submit import consume_token, issue_token
from core.file_type_services import get_preview_kind
from core.text_extraction_services import try_immediate_text_layer_extraction
from permissions.services import (
    can_download,
    can_edit_contract,
    can_select_department,
    contract_searchable_department_ids,
)

logger = logging.getLogger(__name__)

PENDING_SESSION_KEY = "contracts_pending_upload"
BULK_EDIT_SESSION_KEY = "contracts_bulk_edit"


class RequiresContractEditMixin(LoginRequiredMixin):
    """xlsx 権限管理!B196-198(Rev1.2)「契約書-契約書-契約書情報変更」がOFFの職員による
    保存・編集系画面へのURL直打ちをサーバー側でも拒否する共通ミックスイン。

    品質レビューで発見：この判定を`dispatch()`で個別に持っていた5クラス
    （UploadStep1View/UploadStep2View/ContractEditView/BulkEditView、contracts.api.
    ChunkUploadAPIView）はいずれも`class Foo(LoginRequiredMixin, View)`のように
    LoginRequiredMixinを直接の基底クラスにしつつ、そのクラス自身が`dispatch()`を
    オーバーライドしてcan_edit_contract判定→`super().dispatch()`という順で呼んでいた。
    Pythonのメソッド解決はまず「自分自身が定義したdispatch()」を使うため、この構造では
    can_edit_contractの判定がLoginRequiredMixinの認証チェックより先に走ってしまう。
    未ログイン（AnonymousUser）でこれらのURLに直接アクセスすると、can_edit_contract内部の
    `employee.permission_profile`アクセスがAnonymousUserには存在しない属性のため
    AttributeErrorとなり、本来期待されるログイン画面へのリダイレクトの代わりに500エラーに
    なっていた。

    `request.user.is_authenticated`を自前でも確認し、未認証時はcan_edit_contractを呼ばずに
    そのまま`super().dispatch()`へ委ねる（LoginRequiredMixin自身の認証チェックへ進み、
    ログイン画面へリダイレクトする）。

    このミックスイン自体がLoginRequiredMixinを継承するため、`class Foo(RequiresContractEditMixin,
    View)`のようにLoginRequiredMixinを併記しなくても、MRO上に必ずLoginRequiredMixinが
    含まれることが保証される（セキュリティレビューで発見：以前はLoginRequiredMixinを
    自前で継承していない構造だったため、将来このミックスインだけを付けてLoginRequiredMixinを
    書き忘れると、is_authenticatedチェック自体は残るため500エラーにはならないものの、
    未認証ユーザーがログイン画面へリダイレクトされずそのままView本体に到達してしまう
    〈静かな認証バイパス〉になり得た。2026-08-25修正。あわせて5クラスに重複していた
    ほぼ同一の判定ブロックも1箇所に集約した）。

    そのため各ビュー側では`class Foo(RequiresContractEditMixin, View)`のように
    LoginRequiredMixinの併記を省略する（`class Foo(LoginRequiredMixin, RequiresContractEditMixin,
    View)`と併記するとLoginRequiredMixinの継承順序が矛盾しMRO解決エラーになるため、
    併記しないことが必須になる。`ChunkUploadAPIView(RequiresContractEditMixin,
    BaseChunkUploadAPIView)`のようにLoginRequiredMixinを継承した別クラスと組み合わせる場合は
    従来通り問題なく解決できる）。
    """

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not can_edit_contract(request.user):
            logger.warning(
                "契約書情報変更権限が無いユーザーによるアクセスを拒否しました: "
                "employee_no=%s path=%s",
                request.user.employee_no,
                request.path,
            )
            raise PermissionDenied("契約書を保存・編集する権限がありません。")
        return super().dispatch(request, *args, **kwargs)


class UploadStep1View(RequiresContractEditMixin, upload_views.BaseUploadStep1View):
    """screen-storage1（契約書）。xlsx 権限管理!B196-197(Rev1.2)「保存不可…メイン画面の
    保管枠内「契約書」ボタンを非表示にする」に対応し、URL直叩き対策としてサーバー側でも拒否する
    （templates/core/menu.htmlのボタン非表示と同じ判定、RequiresContractEditMixin参照）。
    実体はcore.upload_views.BaseUploadStep1Viewに集約済み（documents.views.UploadStep1Viewとの
    重複をコード監査で発見、2026-08-25修正）。
    """

    template_name = "contracts/storage1.html"
    pending_session_key = PENDING_SESSION_KEY
    next_url_name = "contracts:upload_step2"


class UploadStep2View(RequiresContractEditMixin, View):
    """screen-storage2（契約書モード・登録）。複数ファイルを一括選択した場合、メタデータ
    （部署・分類・年・カテゴリー・契約日等・メモ）も関連書類もページャーで表示中のファイル
    ごとに個別入力する（メタデータのファイルごと化は2026-08-31ユーザー確定、
    documents.views.UploadStep2View／UploadStep2Form docstring参照）。関連書類はRev1.6で
    「既に保管済みの契約書をポップアップ検索して複数紐付ける」方式になり、hidden input
    `related_contract_ids_{index}`（カンマ区切りのpk並び）で送られる。保存ループは
    `form.file_data(i)` を通す。保管フロー全体のURL直叩き対策は RequiresContractEditMixin参照。
    """

    template_name = "contracts/storage2.html"
    form_id = "contracts_upload_step2"

    def _render_form(self, request, form, pending, active_doc_index=0, per_file_related_ids=None):
        """GET・バリデーションエラー再描画・「削除」後の再描画で共通の保管画面２レンダリング。
        `per_file_related_ids` はファイルごとの紐付け先契約書pkリスト。GET時はNone＝全ファイル空。"""
        token = issue_token(request.session, self.form_id)
        return render(
            request,
            self.template_name,
            {
                "form": form,
                "file_rows": upload_views.file_rows(form, pending),
                "file_field_sets": _merge_related_into_field_sets(
                    upload_views.file_field_sets(form, pending, UploadStep2Form.PER_FILE_FIELDS),
                    per_file_related_ids,
                    request.user,
                ),
                "active_doc_index": active_doc_index,
                "token": token,
                "mode": "create",
                "related_search_url": reverse("contracts:api_related_search"),
                **_pending_preview_context(request, pending),
            },
        )

    def _handle_remove(self, request, pending):
        """「削除」ボタン＝表示中ファイルのアップロード取り消し。残りのファイルの入力値を
        詰め直して再描画する（documents.views.UploadStep2View._handle_remove と同じ。
        契約書の関連書類はhidden inputのため、他ファイルのメタデータと同じく
        remap_step2_initial_after_remove で詰め直せる＝選び直し不要）。"""
        try:
            index = int(request.POST.get("remove_index", ""))
        except (TypeError, ValueError):
            logger.warning(
                "保管画面２ アップロード取り消しに不正なindexが送られました: employee_no=%s value=%r",
                request.user.employee_no, request.POST.get("remove_index"),
            )
            return redirect("contracts:upload_step2")
        removed = upload_services.remove_pending_file(request.session, PENDING_SESSION_KEY, index)
        if removed is None:
            return redirect("contracts:upload_step2")
        logger.info(
            "保管画面２ アップロード取り消し: employee_no=%s file=%s",
            request.user.employee_no, removed["original_name"],
        )
        remaining = upload_services.get_pending_files(request.session, PENDING_SESSION_KEY)
        if not remaining:
            messages.info(request, "アップロードを取り消しました。契約書を選択し直してください。")
            return redirect("contracts:upload_step1")
        initial = upload_views.remap_step2_initial_after_remove(
            request.POST, removed_index=index, new_count=len(remaining),
            per_file_fields=UploadStep2Form.PER_FILE_FIELDS,
        )
        form = UploadStep2Form(
            employee=request.user,
            file_count=len(remaining),
            initial_titles=[_strip_ext(item["original_name"]) for item in remaining],
            initial=initial,
        )
        # 関連書類（hidden inputのpk並び）も削除位置に合わせて添字を詰め直す。
        remapped_ids = _remap_related_ids_after_remove(
            request.POST, removed_index=index, new_count=len(remaining)
        )
        messages.info(request, f"「{removed['original_name']}」のアップロードを取り消しました。")
        return self._render_form(
            request, form, remaining, active_doc_index=min(index, len(remaining) - 1),
            per_file_related_ids=remapped_ids,
        )

    def get(self, request):
        pending = upload_services.get_pending_files(request.session, PENDING_SESSION_KEY)
        if not pending:
            messages.error(request, "保管する契約書が選択されていません。")
            return redirect("contracts:upload_step1")
        initial_titles = [_strip_ext(item["original_name"]) for item in pending]
        form = UploadStep2Form(
            employee=request.user, file_count=len(pending), initial_titles=initial_titles
        )
        return self._render_form(request, form, pending)

    def post(self, request):
        pending = upload_services.get_pending_files(request.session, PENDING_SESSION_KEY)
        if not pending:
            messages.error(request, "保管する契約書が選択されていません。")
            return redirect("contracts:upload_step1")

        # 「削除」（表示中ファイルのアップロード取り消し）。他ファイルの入力を保持したまま再描画。
        if request.POST.get("action") == "remove":
            return self._handle_remove(request, pending)

        submitted_token = request.POST.get("token", "")
        if not consume_token(request.session, self.form_id, submitted_token):
            messages.error(request, "二重に送信された可能性があるため処理を中断しました。もう一度やり直してください。")
            return redirect("contracts:upload_step1")

        form = UploadStep2Form(request.POST, employee=request.user, file_count=len(pending))
        if not form.is_valid():
            error_index = form.first_error_file_index()
            if len(pending) > 1:
                messages.error(request, f"{error_index + 1}件目に入力エラーがあります。")
            return self._render_form(
                request, form, pending, active_doc_index=error_index,
                per_file_related_ids=[
                    request.POST.getlist(f"related_contract_ids_{i}") for i in range(len(pending))
                ],
            )

        can_select = can_select_department(request.user)
        # 保存満了日の起算日はJST（settings.TIME_ZONE="Asia/Tokyo"）の「今日」。timezone.now().date()
        # だとUTC日付になり、JST 00:00〜09:00の登録でexpiry_dateが1日手前にずれていた
        # （documents.views.UploadStep2Viewと同一原因。コードレビュー A No.2、2026-09-09）。
        save_date = timezone.localdate()
        created = []
        try:
            # 複数契約書を1回のリクエストでまとめて登録するため、途中の1件でファイルI/O例外が
            # 起きた場合に一部だけDBへコミット済みという中途半端な状態を残さないよう、ループ全体を
            # 1トランザクションにする（documents.views.UploadStep2Viewと同じ理由。原本フィデリティ
            # 監査で発見）。
            with transaction.atomic():
                for doc_index, pending_item in enumerate(pending):
                    # メタデータは2026-08-31ユーザー確定でファイルごとに個別入力
                    # （form.file_data(i)。documents.views.UploadStep2Viewと同じ）。
                    fd = form.file_data(doc_index)
                    department = fd["department"]
                    if not can_select:
                        department = request.user.department
                    contract = Contract(
                        title=fd["title"],
                        department=department,
                        group=fd["group"],
                        category=fd["category"],
                        year=fd["year"],
                        contract_date=fd["contract_date"],
                        contract_period_start=fd["contract_period_start"],
                        contract_period_end=fd["contract_period_end"],
                        renewal_date=fd["renewal_date"],
                        contract_amount=fd["contract_amount"],
                        contract_partner=fd["contract_partner"],
                        memo=fd["memo"],
                        uploader=request.user,
                        expiry_date=calculate_expiry_date(save_date),
                    )
                    temp_file = upload_services.open_pending_file(pending_item["temp_name"])
                    try:
                        contract.file.save(pending_item["original_name"], temp_file, save=False)
                    finally:
                        temp_file.close()
                    contract.save()
                    # 関連書類（Rev1.6）：ファイルごとに独立した hidden input
                    # `related_contract_ids_{doc_index}`（紐付け先契約書pkの繰り返し）を、実在・
                    # 閲覧権限内のものだけに絞ってContractRelationへ同期する。
                    valid_related_ids = filter_valid_related_ids(
                        request.POST.getlist(f"related_contract_ids_{doc_index}"),
                        employee=request.user,
                    )
                    sync_related_contracts(contract, valid_related_ids)
                    # イベントメッセージは原本index.html:3320の操作履歴ログサンプル
                    # 「文書　アップロード｜ファイル名：契約書_100」に合わせ、タイトルではなく
                    # 実ファイル名(display_name)を「ファイル名：」形式で記録する
                    # （原本フィデリティ監査で発見：以前は原本に無い独自形式だった）。
                    audit_services.log(
                        employee=request.user,
                        action="保管画面２　登録",
                        event_message=f"ファイル名：{contract.display_name}",
                    )
                    created.append(contract)
        except (OSError, DBError):
            # open_pending_file()／file.save()でのファイルI/O失敗に加え、contract.save()／
            # ContractRelationのDB制約違反等（DBError）も対象にする（documents.views.
            # UploadStep2Viewと同じ理由。品質レビューで発見：以前はOSErrorしか捕捉しておらず
            # DBErrorは未捕捉のまま生の500エラーになっていた）。transaction.atomic()によりDBへの
            # 登録はロールバックされるが、ロールバック対象の契約書について既にストレージへ書き込み
            # 済みだったファイル実体はDBトランザクションの対象外のため孤児化する。createdに積まれた
            # （=save()まで成功していた）ファイル実体をここで明示的に削除して孤児ファイルを防ぐ
            # （関連書類はRev1.6で物理ファイルを持たなくなったため後始末は本体ファイルのみ）。
            for contract in created:
                contract.file.delete(save=False)
            logger.exception(
                "契約書の保管処理中にエラーが発生しました: employee_no=%s", request.user.employee_no
            )
            messages.error(request, "ファイルの保存に失敗しました。もう一度お試しください。")
            return redirect("contracts:upload_step2")

        # documents.views.UploadStep2Viewと同じ理由（全文検索：テキスト層のあるPDFを同期抽出）。
        for contract in created:
            try_immediate_text_layer_extraction(contract, label="contract")

        upload_services.clear_pending_files(request.session, PENDING_SESSION_KEY)
        # documents.views.UploadStep2View.postと同じ理由（原本フィデリティ監査で発見：
        # 別テンプレートstorage_complete.htmlに丸ごと差し替えると、原本のoverlay-modalと違い
        # 背後の保管画面が消えてしまう）。storage2.htmlをGET時と同じcontextで再描画し、
        # completeキーで完了モーダルを重ねる。
        # プレビュー画像URLも documents.views.UploadStep2View.post と同じ理由で、
        # clear_pending_filesで一時ファイル・セッションが既に消えているため
        # PendingPreviewView（保留ファイルindex参照）ではなく、登録済みcreatedのpkを使う
        # PreviewView（pkベース）を指す。
        if can_download(request.user, kind="contract"):
            preview_urls = [reverse("contracts:preview", args=[c.pk]) for c in created]
        else:
            preview_urls = []
        token = issue_token(request.session, self.form_id)
        return render(
            request,
            self.template_name,
            {
                "form": form,
                "file_rows": upload_views.file_rows(form, pending),
                "file_field_sets": _merge_related_into_field_sets(
                    upload_views.file_field_sets(form, pending, UploadStep2Form.PER_FILE_FIELDS),
                    [
                        list(c.related_links.values_list("related_contract_id", flat=True))
                        for c in created
                    ],
                    request.user,
                ),
                "active_doc_index": 0,
                "token": token,
                "mode": "create",
                "related_search_url": reverse("contracts:api_related_search"),
                "complete": {"created": created, "mode": "create"},
                "preview_kinds": [get_preview_kind(c.display_name) or "" for c in created],
                "preview_urls": preview_urls,
            },
        )


class ContractEditView(RequiresContractEditMixin, UpdateView):
    """screen-storage2（契約書編集）。Rev1.2で追加された「契約書-契約書-契約書情報変更」
    （xlsx 権限管理!B193-198）がOFFの職員は編集不可（documents側に対応するフラグは無く、
    文書の編集は従来通り無条件で可能。RequiresContractEditMixin参照）。
    """

    model = Contract
    template_name = "contracts/edit.html"
    context_object_name = "contract"
    form_id = "contracts_edit"

    def get_object(self, queryset=None):
        # セキュリティレビューで発見：部署スコープ外の契約書へのURL直打ちを防ぐ
        # （contracts.services.scoped_get_object_or_404 docstring参照。2026-08-25修正）。
        return scoped_get_object_or_404(
            Contract.objects.prefetch_related("related_links__related_contract").filter(is_deleted=False),
            self.request.user,
            self.kwargs["pk"],
        )

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        form = self._build_form()
        token = issue_token(request.session, self.form_id)
        return render(
            request,
            self.template_name,
            {
                "form": form,
                "contract": self.object,
                "token": token,
                "title_field": form["title_0"],
                "related_rows": _related_rows_for_contract(self.object, request.user),
                "related_search_url": reverse("contracts:api_related_search"),
                "preview_kind": get_preview_kind(self.object.display_name),
                "can_download": can_download(request.user, kind="contract"),
                **_edit_delete_context(self.object),
            },
        )

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        submitted_token = request.POST.get("token", "")
        if not consume_token(request.session, self.form_id, submitted_token):
            messages.error(request, "二重に送信された可能性があるため処理を中断しました。もう一度やり直してください。")
            return redirect("contracts:edit", pk=self.object.pk)

        form = self._build_form(data=request.POST)
        if not form.is_valid():
            token = issue_token(request.session, self.form_id)
            return render(
                request,
                self.template_name,
                {
                    "form": form,
                    "contract": self.object,
                    "token": token,
                    "title_field": form["title_0"],
                    "related_rows": _resolve_related_rows(
                        request.POST.getlist("related_contract_ids"), request.user
                    ),
                    "related_search_url": reverse("contracts:api_related_search"),
                    "preview_kind": get_preview_kind(self.object.display_name),
                    "can_download": can_download(request.user, kind="contract"),
                    **_edit_delete_context(self.object),
                },
            )

        contract = self.object
        related_ids = filter_valid_related_ids(
            request.POST.getlist("related_contract_ids"),
            employee=request.user,
            exclude_pk=contract.pk,
            # 既存の紐付け（論理削除済みを含む）はリストに残っていれば維持する（レビュー A No.1）。
            keep_ids=contract.related_links.values_list("related_contract_id", flat=True),
        )

        try:
            apply_contract_edit(contract, form.cleaned_data, request.user, related_ids)
        except DBError:
            logger.exception(
                "契約書の更新処理中にDBエラーが発生しました: contract_id=%s, employee_no=%s",
                contract.pk,
                request.user.employee_no,
            )
            messages.error(request, "更新に失敗しました。もう一度お試しください。")
            return redirect("contracts:edit", pk=contract.pk)

        audit_services.log(
            employee=request.user,
            action="保管画面２　更新",
            event_message=f"契約書「{contract.title}」を更新しました。",
        )
        # UploadStep2View.postと同じ理由（別テンプレートへの丸ごと差し替えをやめ、edit.htmlを
        # 再描画した上でcomplete経由で完了モーダルを重ねる）。
        token = issue_token(request.session, self.form_id)
        return render(
            request,
            self.template_name,
            {
                "form": form,
                "contract": contract,
                "token": token,
                "title_field": form["title_0"],
                "related_rows": _related_rows_for_contract(contract, request.user),
                "related_search_url": reverse("contracts:api_related_search"),
                "complete": {"created": [contract], "mode": "update"},
                "preview_kind": get_preview_kind(self.object.display_name),
                "can_download": can_download(request.user, kind="contract"),
                **_edit_delete_context(self.object),
            },
        )

    def _build_form(self, data=None):
        obj = self.object
        return UploadStep2Form(
            data,
            employee=self.request.user,
            file_count=1,
            initial_titles=[obj.title],
            edit_mode=True,
            initial={
                "department": obj.department_id,
                "group": obj.group_id,
                "category": obj.category_id,
                "year": obj.year,
                "contract_date": obj.contract_date,
                "contract_period_start": obj.contract_period_start,
                "contract_period_end": obj.contract_period_end,
                "renewal_date": obj.renewal_date,
                "contract_amount": obj.contract_amount,
                "contract_partner": obj.contract_partner,
                "memo": obj.memo,
            },
        )


class BulkEditStartView(RequiresContractEditMixin, View):
    """screen-search「一括編集」ボタン（契約書側）。documents.views.BulkEditStartViewと同じ設計
    （詳細はそちらのdocstring参照）だが、Rev1.2で追加された「契約書-契約書-契約書情報変更」
    がOFFの職員は一括編集も不可（RequiresContractEditMixin参照）。
    """

    def post(self, request):
        pks = request.POST.getlist("pks")
        # 文言は原本html4のstartBulkEdit（alert("編集するデータが選択されていません。")）に合わせる
        # （B599「文書管理と同じ」。2026-08-27、原本フィデリティ監査）。
        if not pks:
            messages.error(request, "編集するデータが選択されていません。")
            return redirect("contracts:search")

        # pks検証・部署スコープ絞り込みの実体はcore.bulk_edit_services.resolve_ordered_pksに
        # 集約済み（documents.views.BulkEditStartViewとの重複をコード監査で発見、2026-08-25修正）。
        ordered_pks = bulk_edit_services.resolve_ordered_pks(
            pks, model=Contract, dept_ids_resolver=contract_searchable_department_ids, employee=request.user
        )
        if not ordered_pks:
            messages.error(request, "編集するデータが選択されていません。")
            return redirect("contracts:search")

        # 開始のたび、前回の中断で残ったステージ内容を掃除する。
        bulk_edit_services.discard_bulk_edit(request.session, BULK_EDIT_SESSION_KEY)
        bulk_edit_services.start_bulk_edit(request.session, BULK_EDIT_SESSION_KEY, ordered_pks)
        return redirect("contracts:bulk_edit")


# 一括編集で各ページの生POST値としてセッションへ退避するフォームフィールド名。
CONTRACT_BULK_FORM_FIELDS = (
    "department", "group", "category", "year",
    "contract_date", "contract_period_start", "contract_period_end",
    "renewal_date", "contract_amount", "contract_partner", "memo", "title_0",
)


class BulkEditView(RequiresContractEditMixin, bulk_edit_views.BaseBulkEditView):
    """一括編集ウィザード本体（契約書側・ステージング型）。制御フロー・画面遷移の実体は
    core.bulk_edit_views.BaseBulkEditView に集約済み（コードレビュー B No.4、2026-09-09。
    documents.views.BulkEditView とモデル・フォーム初期値・監査ログ文言・関連書類ステージ以外
    行単位でほぼ一致していたため）。BulkEditStartView と同じく Rev1.2 の「契約書-契約書-契約書
    情報変更」がOFFの職員はアクセス不可（RequiresContractEditMixin 参照）。

    契約書側の固有部分：関連書類（Rev1.6 で既存契約書への参照）を「更新」までセッションに
    ステージし、確定時に紐付けの増減も dirty 判定に含める。編集画面には現在（またはステージ中）の
    紐付け行と関連書類検索APIのURLをコンテキストで渡す。
    """

    model = Contract
    template_name = "contracts/edit.html"
    form_id = "contracts_bulk_edit"
    session_key = BULK_EDIT_SESSION_KEY
    entity_name = "契約書"
    kind = "contract"
    context_object_name = "contract"
    form_field_names = CONTRACT_BULK_FORM_FIELDS
    search_url_name = "contracts:search"
    bulk_edit_url_name = "contracts:bulk_edit"
    scoped_lookup = staticmethod(scoped_get_object_or_404)
    dept_ids_resolver = staticmethod(contract_searchable_department_ids)

    def base_queryset(self):
        return Contract.objects.prefetch_related("related_links__related_contract").filter(
            is_deleted=False
        )

    def commit_queryset(self, pks):
        return Contract.objects.prefetch_related("related_links").filter(pk__in=pks)

    def build_form(self, obj, data=None, marked_delete=False):
        form = UploadStep2Form(
            data,
            employee=self.request.user,
            file_count=1,
            initial_titles=[obj.title],
            edit_mode=True,
            initial={
                "department": obj.department_id,
                "group": obj.group_id,
                "category": obj.category_id,
                "year": obj.year,
                "contract_date": obj.contract_date,
                "contract_period_start": obj.contract_period_start,
                "contract_period_end": obj.contract_period_end,
                "renewal_date": obj.renewal_date,
                "contract_amount": obj.contract_amount,
                "contract_partner": obj.contract_partner,
                "memo": obj.memo,
            },
        )
        if marked_delete:
            for field in form.fields.values():
                field.disabled = True
        return form

    def stage_extra(self, request, obj):
        # 関連書類（紐付け先契約書pkの並び）もそのページの hidden input を丸ごとステージする。
        related_ids = filter_valid_related_ids(
            request.POST.getlist("related_contract_ids"),
            employee=request.user,
            exclude_pk=obj.pk,
            # 既存の紐付け（論理削除済みを含む）はリストに残っていれば維持する（レビュー A No.1）。
            keep_ids=obj.related_links.values_list("related_contract_id", flat=True),
        )
        bulk_edit_services.stage_related_ids(
            request.session, self.session_key, obj.pk, related_ids
        )

    def commit_one_update(self, request, obj, form, state):
        # ステージ済みの紐付け先契約書pk（未編集ページはNone＝現状維持）。
        staged_ids = bulk_edit_services.staged_related_ids_for(state, obj.pk)
        current_ids = list(obj.related_links.values_list("related_contract_id", flat=True))
        related_ids = current_ids if staged_ids is None else staged_ids
        # 並び替えのみ（集合は同じで順序だけ違う）も変更として扱う。単独編集経路は
        # apply_contract_edit を無条件に呼んで display_order を更新するため、set 比較だと
        # 一括編集だけ並べ替えが黙って破棄されて非一貫だった（コードレビュー C7）。
        related_changed = staged_ids is not None and list(staged_ids) != current_ids
        if contract_edit_is_dirty(
            obj, form.cleaned_data, request.user, related_changed=related_changed
        ):
            apply_contract_edit(obj, form.cleaned_data, request.user, related_ids)
            return True
        return False

    def render_context_extra(self, request, form, state):
        return {
            "related_rows": self._related_rows(state, request.user),
            "related_search_url": reverse("contracts:api_related_search"),
        }

    def complete_context_extra(self, request, form):
        return {
            "related_rows": _related_rows_for_contract(self.object, request.user),
            "related_search_url": reverse("contracts:api_related_search"),
        }

    def _related_rows(self, state, employee):
        """一括編集画面の[3]関連書類の表示行。そのページで関連書類を編集済み（ステージあり）なら
        ステージ内容を、未編集なら現在の紐付けを表示する（他のフォーム欄と同じ「ステージ優先・
        なければ現状」方式）。"""
        staged_ids = bulk_edit_services.staged_related_ids_for(state, self.object.pk)
        if staged_ids is None:
            return _related_rows_for_contract(self.object, employee)
        return _resolve_related_rows(staged_ids, employee)


class SearchView(LoginRequiredMixin, View):
    """screen-search（契約書モード）。一覧・検索。1ページ100件（コーディング規約のPaginator方針、Rev1.1で50→100件）。
    文書モードとUIは共通だが、保存期間の絞り込みが無く契約特有項目（契約日・契約先名等）を持つ点が異なる。"""

    template_name = "contracts/search.html"
    PAGE_SIZE = 100

    def get(self, request):
        notice = request.GET.get("notice")
        sort_key = request.GET.get("sort")
        sort_dir = request.GET.get("dir", "asc")
        pks_param = request.GET.get("pks")
        pks = [p for p in pks_param.split(",") if p] if pks_param else None
        # request.GET or Noneは避ける（accounts.services.filter_staff_querysetのコメント参照）。
        form = SearchForm(request.GET, employee=request.user)
        qs = build_queryset(
            form,
            employee=request.user,
            notice=notice,
            pks=pks,
            sort_key=sort_key,
            sort_dir=sort_dir,
            dept_ids=form.contract_dept_ids,
        )
        paginator = Paginator(qs, self.PAGE_SIZE)
        page_obj = paginator.get_page(request.GET.get("page"))
        # 原本index.html:3315の操作履歴ログサンプル「契約書　検索｜分類：XXX,年：XXX,カテゴリー：
        # XXX,タイトル：XXX,フリーワード：XXX」に対応（未実装改善候補の棚卸しで発見：検索操作
        # 自体が一度も監査ログに記録されていなかった）。ページャー/ソートの再アクセスは新たな
        # 検索操作ではないため対象外にする（core.search_services.is_search_form_submission
        # docstring参照）。
        if form.is_valid() and search_services.is_search_form_submission(request.GET, form.fields.keys()):
            audit_services.log(
                employee=request.user,
                action="契約書検索　検索",
                event_message=search_services.build_search_audit_message(form, request.GET.keys()),
            )
        return render(
            request,
            self.template_name,
            {
                "form": form,
                "page_obj": page_obj,
                "can_download": can_download(request.user, kind="contract"),
                "sort_key": sort_key,
                "sort_dir": sort_dir,
                "notice": notice,
            },
        )


class DownloadView(LoginRequiredMixin, record_views.BaseFileServeView):
    """documents.views.DownloadViewと同じ理由（xlsx 検索・閲覧・変更!B659(Rev1.2)「削除されている
    (削除フラグがTrue)契約書は、ボタンを非表示とする」）で、is_deleted=Falseでしか対象を
    取得できないようにする。実体はcore.record_views.BaseFileServeViewに集約済み
    （documents.views.DownloadViewとの重複をコード監査で発見、2026-08-25修正）。
    """

    model = Contract
    kind = "contract"
    scoped_lookup = staticmethod(scoped_get_object_or_404)
    as_attachment = True
    audit_action = "契約書検索　ダウンロード"
    entity_label = "契約書"


class SearchablePdfView(LoginRequiredMixin, record_views.BaseSearchablePdfView):
    """documents.views.SearchablePdfView と対（監査 案3、2026-09-11）。旧 Contract.searchable_file を
    置き換え。`ocr_textdata` が保存されたスキャン文書のみ生成可。まだどの画面からもリンクしていない。"""

    model = Contract
    kind = "contract"
    scoped_lookup = staticmethod(scoped_get_object_or_404)
    audit_action = "契約書検索　検索用PDFダウンロード"


class PreviewView(LoginRequiredMixin, record_views.BaseFileServeView):
    """documents.views.PreviewView参照。screen-search（契約書モード）「文書イメージ」欄用。実体は
    core.record_views.BaseFileServeViewに集約済み（documents.views.PreviewViewとの重複を
    コード監査で発見、2026-08-25修正）。
    """

    model = Contract
    kind = "contract"
    scoped_lookup = staticmethod(scoped_get_object_or_404)
    as_attachment = False
    audit_action = "契約書検索　プレビュー"
    entity_label = "契約書"


class BulkDownloadView(LoginRequiredMixin, record_views.BaseBulkDownloadView):
    """screen-search（契約書モード）「一括ダウンロード」。documents.views.BulkDownloadViewと同様
    （xlsx 検索・閲覧・変更!B596-600「※文書管理と同じ」によりB264-265のルールを準用、
    要再確認No.22の「契約書-ダウンロード」フラグで権限判定）。実体はcore.record_views.
    BaseBulkDownloadViewに集約済み（documents.views.BulkDownloadViewとの重複をコード監査で発見、
    2026-08-25修正）。
    """

    model = Contract
    kind = "contract"
    dept_ids_resolver = staticmethod(contract_searchable_department_ids)
    zip_builder = staticmethod(build_zip_archive)
    audit_action = "契約書検索　一括ダウンロード"
    entity_label = "契約書"
    search_url_name = "contracts:search"
    zip_filename = "contracts.zip"


class DeleteView(LoginRequiredMixin, record_views.BaseDeleteView):
    """詳細ポップアップ「削除」ボタン。論理削除（is_deleted=True）のみを行う。

    documents.views.DeleteViewと同じ理由（2026-08-12にユーザー依頼で追加した「ゴミ箱保管中の
    契約書を削除ボタンで完全削除する」機能を、Rev1.2改訂〈xlsx 検索・閲覧・変更!B659,B663
    「削除されている契約書は、ボタンを非表示とする」〉でユーザー判断によりxlsx優先とし、
    2026-08-24に廃止した）。実体はcore.record_views.BaseDeleteViewに集約済み（documents.views.
    DeleteViewとの重複をコード監査で発見、2026-08-25修正）。
    """

    model = Contract
    scoped_lookup = staticmethod(scoped_get_object_or_404)
    entity_label = "契約書"
    search_url_name = "contracts:search"

    def extra_permission_check(self, request, obj):
        if not can_edit_contract(request.user):
            # xlsx 権限管理!B198(Rev1.2)「編集不可…検索・閲覧画面の検索結果一覧の明細ダブル
            # クリック後に開く契約書詳細画面の「編集」「削除」ボタンを非表示にする」。監査で発見：
            # DetailAPIViewのdelete_urlは`can_delete(contract) and can_edit`で判定しボタン自体は
            # 隠していたが、DeleteView.post側にcan_edit_contractの検証が無く、URL直打ちで
            # 契約書-契約書-契約書情報変更がOFFの職員でも削除できてしまっていた
            # （ContractEditView.dispatch/UploadStep1View.dispatchと同じくサーバー側でも強制する）。
            logger.warning(
                "契約書情報変更権限が無いユーザーによる削除操作を拒否しました: "
                "employee_no=%s contract_id=%s",
                request.user.employee_no,
                obj.pk,
            )
            return "契約書を削除する権限がありません。"
        return None


class EditDeleteView(DeleteView):
    """単独編集画面（ContractEditView、edit.html）の[4]メモ欄直下「削除」ボタン。
    documents.views.EditDeleteViewと同じ（削除自体はDeleteView＝BaseDeleteViewと同一、監査ログの
    action名だけ違う。契約書側はDeleteView継承でextra_permission_check〈can_edit_contract〉を
    引き継ぐ）。一括編集画面の削除は「更新」ボタンでまとめて確定する別方式（ステージ型）のため
    このビューは通らない。2026-08-27ユーザー確定でメモ欄クリアからレコードの論理削除に変更。
    """

    audit_action = "保管画面２　削除"


def _strip_ext(filename):
    return filename.rsplit(".", 1)[0] if "." in filename else filename


# --- 関連書類（紐付け先契約書）の再描画用ヘルパー（Rev1.6） --------------------------------
# フォーム再描画（GET・バリデーションエラー・「削除」後・一括編集のページ移動）で、hidden input
# の pk 並びをテンプレートの表示行へ解決する。保存時の実在・権限チェックは
# contracts.services.filter_valid_related_ids が担い、ここは見た目のみ（存在しないpkは黙って落とす）。

def _related_row(contract, allowed_department_ids):
    """関連契約書1件の表示行。閲覧者の部署スコープ外なら、contracts.api.DetailAPIView.get
    （`_related_contract_payload`、review_security.txt No.1／S1）と同じくタイトルを伏せ字にする。
    `filter_valid_related_ids`（contracts/services.py）はスコープ変更後も既存の紐付けを
    `keep_ids`で維持する仕様のため、編集画面等で「今は閲覧できない契約書」への紐付けが
    普通に存在しうる（2026-09-11監査で発見：api.py側だけ対応済みで、この編集画面・一括編集・
    保管画面２側の描画には同種のガードが無く、取引先名等を含むタイトルがそのまま漏れていた）。"""
    out_of_scope = (
        allowed_department_ids is not None and contract.department_id not in allowed_department_ids
    )
    return {
        "id": contract.pk,
        "title": "（閲覧権限のない関連資料）" if out_of_scope else contract.title,
        "is_deleted": contract.is_deleted,
    }


def _related_rows_for_contract(contract, employee):
    """`contract.related_links`（related_contract を prefetch 済み前提）を編集画面の表示行へ。"""
    allowed_department_ids = contract_searchable_department_ids(employee)
    return [_related_row(link.related_contract, allowed_department_ids) for link in contract.related_links.all()]


def _resolve_related_rows(raw_ids, employee):
    """契約書pk（文字列可・順序保持・重複可）のリストを表示行 `[{id, title, is_deleted}]` に解決する。"""
    allowed_department_ids = contract_searchable_department_ids(employee)
    int_ids = []
    for tok in raw_ids:
        try:
            int_ids.append(int(tok))
        except (TypeError, ValueError):
            continue
    by_pk = {c.pk: c for c in Contract.objects.filter(pk__in=int_ids)}
    rows = []
    seen = set()
    for pk in int_ids:
        contract = by_pk.get(pk)
        if contract is not None and pk not in seen:
            seen.add(pk)
            rows.append(_related_row(contract, allowed_department_ids))
    return rows


def _merge_related_into_field_sets(field_sets, per_file_related_ids, employee):
    """`core.upload_views.file_field_sets` の各要素に、そのファイルの関連書類表示行
    （`related_contracts`）を足し込む。`per_file_related_ids` はファイルごとの契約書pkリストの
    リスト（None＝全ファイル空）。storage2.html はメタデータ欄と同じ添字で [3] 関連書類を描く。"""
    for i, field_set in enumerate(field_sets):
        raw = (
            per_file_related_ids[i]
            if per_file_related_ids and i < len(per_file_related_ids)
            else []
        )
        field_set["related_contracts"] = _resolve_related_rows(raw, employee)
    return field_sets


def _remap_related_ids_after_remove(post_data, *, removed_index, new_count):
    """「削除」（表示中ファイルの取り消し）で残ったファイルの related_contract_ids を添字詰め直し。
    remap_step2_initial_after_remove の関連書類版（あちらは単一値フォーム欄のみ扱う）。"""
    out = []
    src = 0
    for _dst in range(new_count):
        if src == removed_index:
            src += 1
        out.append(post_data.getlist(f"related_contract_ids_{src}"))
        src += 1
    return out


def _pending_preview_context(request, pending):
    return upload_views.build_pending_preview_context(
        request, pending, kind="contract", preview_url_name="contracts:upload_step2_preview"
    )


def _edit_delete_context(obj):
    """edit.htmlの[4]メモ欄直下「削除」ボタン（EditDeleteView）用。documents.views._edit_delete_context
    と同じ（can_delete=Falseならテンプレートでボタンごと非表示。xlsx 保管!B583「初回登録から
    1週間以上経過・削除済みはボタンを非表示」。Rev1.5まではB581、Rev1.6の関連書類節の行追加で+2）。"""
    return {
        "can_delete": deletion_services.can_delete(obj),
        "delete_action_url": reverse("contracts:edit_delete", args=[obj.pk]),
    }


class PendingPreviewView(RequiresContractEditMixin, upload_views.BasePendingPreviewView):
    """実体はcore.upload_views.BasePendingPreviewViewに集約済み（documents.views.
    PendingPreviewViewとの重複をコード監査で発見、2026-08-25修正）。UploadStep1View/
    UploadStep2Viewと同じ保管フローの一部であるため、RequiresContractEditMixinを適用する
    （品質レビューで発見：以前はcan_downloadのみで判定しており、セッション中にcontract_edit
    権限を剥奪された利用者でも保留ファイルの中身を参照できてしまっていた。2026-08-25修正）。
    """

    pending_session_key = PENDING_SESSION_KEY
    kind = "contract"
