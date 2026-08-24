import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import Error as DBError, transaction
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import UpdateView

from audit import services as audit_services
from contracts.forms import SearchForm, UploadStep2Form
from contracts.models import Contract, RelatedFile
from contracts.search_services import build_queryset
from contracts.services import (
    apply_contract_edit,
    calculate_expiry_date,
    can_delete,
    parse_remove_related_ids,
)
from core import bulk_edit_services, upload_services
from core.double_submit import consume_token, issue_token
from core.file_type_services import get_preview_kind
from core.text_extraction_services import try_immediate_text_layer_extraction
from permissions.services import can_download, can_edit_contract, can_select_department

logger = logging.getLogger(__name__)

PENDING_SESSION_KEY = "contracts_pending_upload"
BULK_EDIT_SESSION_KEY = "contracts_bulk_edit"


class UploadStep1View(LoginRequiredMixin, View):
    """screen-storage1（契約書）。xlsx 権限管理!B196-197(Rev1.2)「保存不可…メイン画面の
    保管枠内「契約書」ボタンを非表示にする」に対応し、URL直叩き対策としてサーバー側でも拒否する
    （templates/core/menu.htmlのボタン非表示と同じ判定、permissions.services.can_edit_contract）。
    """

    template_name = "contracts/storage1.html"

    def dispatch(self, request, *args, **kwargs):
        if not can_edit_contract(request.user):
            logger.warning(
                "契約書情報変更権限が無いユーザーによる保管画面アクセスを拒否しました: employee_no=%s",
                request.user.employee_no,
            )
            raise PermissionDenied("契約書を保存する権限がありません。")
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        upload_services.clear_pending_files(request.session, PENDING_SESSION_KEY)
        return render(request, self.template_name, self._context())

    def post(self, request):
        files = request.FILES.getlist("files")
        # documents.views.UploadStep1View.postと同じ理由：大容量ファイルはstorage1.htmlのJSが
        # upload/chunk/へチャンク分割送信し、combine_upload_chunksがこのセッションキーへ直接
        # 追記済みのため、通常のfile inputが0件でもチャンク経由で登録済みなら処理を続行する。
        existing_pending = upload_services.get_pending_files(request.session, PENDING_SESSION_KEY)
        if not files and not existing_pending:
            messages.error(request, "ファイルが選択されていません。")
            return render(request, self.template_name, self._context())
        if files:
            try:
                upload_services.save_pending_files(request.session, PENDING_SESSION_KEY, files)
            except upload_services.PendingFileStorageError:
                # MEDIA_ROOT/tmp_uploads への一時保存に失敗（ディスク容量不足・権限エラー等）。
                # documents.views.UploadStep1Viewと同じ理由（save_pending_filesはOSErrorを
                # PendingFileStorageErrorにラップして送出するため、これを捕捉する必要がある）。
                logger.exception(
                    "アップロードファイルの一時保存に失敗しました: employee_no=%s", request.user.employee_no
                )
                messages.error(request, "ファイルの保存に失敗しました。もう一度お試しください。")
                return render(request, self.template_name, self._context())
        return redirect("contracts:upload_step2")

    def _context(self):
        return {"max_upload_size_bytes": settings.MAX_UPLOAD_SIZE_BYTES}


class UploadStep2View(LoginRequiredMixin, View):
    """screen-storage2（契約書モード・登録）。関連書類の添付は、バッチ内ファイルが1件の場合のみ
    対応する（複数契約書を一括登録するバッチに対して関連書類をどう振り分けるかはHTML/xlsxに
    明記が無いため、あいまいさを避けるスコープ限定）。
    """

    template_name = "contracts/storage2.html"
    form_id = "contracts_upload_step2"

    def dispatch(self, request, *args, **kwargs):
        # UploadStep1View.dispatchと同じ理由（保管フロー全体をURL直叩きから守る）。
        if not can_edit_contract(request.user):
            logger.warning(
                "契約書情報変更権限が無いユーザーによる保管画面アクセスを拒否しました: employee_no=%s",
                request.user.employee_no,
            )
            raise PermissionDenied("契約書を保存する権限がありません。")
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        pending = upload_services.get_pending_files(request.session, PENDING_SESSION_KEY)
        if not pending:
            messages.error(request, "保管する契約書が選択されていません。")
            return redirect("contracts:upload_step1")
        initial_titles = [_strip_ext(item["original_name"]) for item in pending]
        form = UploadStep2Form(
            employee=request.user, file_count=len(pending), initial_titles=initial_titles
        )
        token = issue_token(request.session, self.form_id)
        return render(
            request,
            self.template_name,
            {
                "form": form,
                "file_rows": _file_rows(form, pending),
                "token": token,
                "mode": "create",
                **_pending_preview_context(request, pending),
            },
        )

    def post(self, request):
        pending = upload_services.get_pending_files(request.session, PENDING_SESSION_KEY)
        if not pending:
            messages.error(request, "保管する契約書が選択されていません。")
            return redirect("contracts:upload_step1")

        submitted_token = request.POST.get("token", "")
        if not consume_token(request.session, self.form_id, submitted_token):
            messages.error(request, "二重に送信された可能性があるため処理を中断しました。もう一度やり直してください。")
            return redirect("contracts:upload_step1")

        form = UploadStep2Form(request.POST, employee=request.user, file_count=len(pending))
        if not form.is_valid():
            token = issue_token(request.session, self.form_id)
            return render(
                request,
                self.template_name,
                {
                    "form": form,
                    "file_rows": _file_rows(form, pending),
                    "token": token,
                    "mode": "create",
                    **_pending_preview_context(request, pending),
                },
            )

        department = form.cleaned_data["department"]
        if not can_select_department(request.user):
            department = request.user.department

        titles = form.titles(len(pending))
        save_date = timezone.now()
        created = []
        try:
            # 複数契約書を1回のリクエストでまとめて登録するため、途中の1件（本体または
            # 関連書類）でファイルI/O例外が起きた場合に一部だけDBへコミット済みという
            # 中途半端な状態を残さないよう、ループ全体を1トランザクションにする
            # （documents.views.UploadStep2Viewと同じ理由。原本フィデリティ監査で発見）。
            with transaction.atomic():
                for doc_index, (pending_item, title) in enumerate(zip(pending, titles)):
                    contract = Contract(
                        title=title,
                        department=department,
                        group=form.cleaned_data["group"],
                        category=form.cleaned_data["category"],
                        year=form.cleaned_data["year"],
                        contract_date=form.cleaned_data["contract_date"],
                        contract_period_start=form.cleaned_data["contract_period_start"],
                        contract_period_end=form.cleaned_data["contract_period_end"],
                        renewal_date=form.cleaned_data["renewal_date"],
                        contract_amount=form.cleaned_data["contract_amount"],
                        contract_partner=form.cleaned_data["contract_partner"],
                        memo=form.cleaned_data["memo"],
                        uploader=request.user,
                        expiry_date=calculate_expiry_date(save_date.date()),
                    )
                    temp_file = upload_services.open_pending_file(pending_item["temp_name"])
                    try:
                        contract.file.save(pending_item["original_name"], temp_file, save=False)
                    finally:
                        temp_file.close()
                    contract.save()
                    # 原本index.html:1567-1589のsetupStorageFormForActiveDoc()通り、一括登録時も
                    # 文書ごとに独立した関連書類欄（storage2.htmlのrelated_files_{doc_index}）を持つ
                    # （原本フィデリティ監査で発見：以前は1件登録時のみ許可していた）。
                    for i, related in enumerate(request.FILES.getlist(f"related_files_{doc_index}")):
                        RelatedFile.objects.create(contract=contract, file=related, display_order=i)
                    audit_services.log(
                        employee=request.user,
                        action="保管画面２ 登録",
                        event_message=f"契約書「{contract.title}」を保管しました。",
                    )
                    created.append(contract)
        except OSError:
            # open_pending_file()／file.save()（本体・関連書類とも）でのファイルI/O失敗。
            # transaction.atomic()によりここまでの登録はロールバックされる
            # （documents.views.UploadStep2Viewと同じ理由）。
            logger.exception(
                "契約書の保管処理中にファイルI/Oエラーが発生しました: employee_no=%s", request.user.employee_no
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
                "file_rows": _file_rows(form, pending),
                "token": token,
                "mode": "create",
                "complete": {"created": created, "mode": "create"},
                "preview_kinds": [get_preview_kind(c.display_name) or "" for c in created],
                "preview_urls": preview_urls,
            },
        )


class ContractEditView(LoginRequiredMixin, UpdateView):
    """screen-storage2（契約書編集）。Rev1.2で追加された「契約書-契約書-契約書情報変更」
    （xlsx 権限管理!B193-198）がOFFの職員は編集不可（documents側に対応するフラグは無く、
    文書の編集は従来通り無条件で可能。permissions.services.can_edit_contract参照）。
    """

    model = Contract
    template_name = "contracts/edit.html"
    context_object_name = "contract"
    form_id = "contracts_edit"

    def dispatch(self, request, *args, **kwargs):
        if not can_edit_contract(request.user):
            logger.warning(
                "契約書情報変更権限が無いユーザーによる編集アクセスを拒否しました: "
                "employee_no=%s contract_id=%s",
                request.user.employee_no,
                kwargs.get("pk"),
            )
            raise PermissionDenied("契約書を編集する権限がありません。")
        return super().dispatch(request, *args, **kwargs)

    def get_object(self, queryset=None):
        return get_object_or_404(
            Contract.objects.prefetch_related("related_files"), pk=self.kwargs["pk"], is_deleted=False
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
                "preview_kind": get_preview_kind(self.object.display_name),
                "can_download": can_download(request.user, kind="contract"),
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
                    "preview_kind": get_preview_kind(self.object.display_name),
                    "can_download": can_download(request.user, kind="contract"),
                },
            )

        contract = self.object
        remove_ids = parse_remove_related_ids(
            request.POST.get("remove_related_ids", ""), employee_no=request.user.employee_no
        )
        new_related_files = request.FILES.getlist("related_files")

        try:
            apply_contract_edit(contract, form.cleaned_data, request.user, remove_ids, new_related_files)
        except OSError:
            logger.exception(
                "契約書の更新処理中にファイルI/Oエラーが発生しました: contract_id=%s, employee_no=%s",
                contract.pk,
                request.user.employee_no,
            )
            messages.error(request, "ファイルの保存に失敗しました。もう一度お試しください。")
            return redirect("contracts:edit", pk=contract.pk)
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
            action="保管画面２ 更新",
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
                "complete": {"created": [contract], "mode": "update"},
                "preview_kind": get_preview_kind(self.object.display_name),
                "can_download": can_download(request.user, kind="contract"),
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


class BulkEditStartView(LoginRequiredMixin, View):
    """screen-search「一括編集」ボタン（契約書側）。documents.views.BulkEditStartViewと同じ設計
    （詳細はそちらのdocstring参照）だが、Rev1.2で追加された「契約書-契約書-契約書情報変更」
    がOFFの職員は一括編集も不可（ContractEditView.dispatchと同じ判定、
    permissions.services.can_edit_contract参照）。
    """

    def post(self, request):
        if not can_edit_contract(request.user):
            logger.warning(
                "契約書情報変更権限が無いユーザーによる一括編集開始を拒否しました: employee_no=%s",
                request.user.employee_no,
            )
            raise PermissionDenied("契約書を編集する権限がありません。")
        pks = request.POST.getlist("pks")
        if not pks:
            messages.error(request, "編集する契約書を選択してください。")
            return redirect("contracts:search")

        valid_pks = []
        for p in pks:
            try:
                valid_pks.append(int(p))
            except (TypeError, ValueError):
                logger.warning(
                    "一括編集の選択値(pks)に不正な値が含まれていたため除外しました: "
                    "employee_no=%s value=%r",
                    request.user.employee_no,
                    p,
                )

        existing_pks = set(
            Contract.objects.filter(pk__in=valid_pks, is_deleted=False).values_list("pk", flat=True)
        )
        ordered_pks = [pk for pk in valid_pks if pk in existing_pks]
        if not ordered_pks:
            messages.error(request, "編集する契約書を選択してください。")
            return redirect("contracts:search")

        bulk_edit_services.start_bulk_edit(request.session, BULK_EDIT_SESSION_KEY, ordered_pks)
        return redirect("contracts:bulk_edit")


class BulkEditView(LoginRequiredMixin, View):
    """一括編集ウィザード本体（契約書側）。documents.views.BulkEditViewと同じ設計・同じ
    save-as-you-go方式（詳細はそちらのdocstring参照）。ContractEditViewと同じく関連書類の
    追加・削除もステップの保存に含まれる。BulkEditStartView.postと同じくRev1.2の
    「契約書-契約書-契約書情報変更」がOFFの職員はアクセス不可
    （URL直叩き対策、dispatchで一元的に判定する）。
    """

    template_name = "contracts/edit.html"
    form_id = "contracts_bulk_edit"

    def dispatch(self, request, *args, **kwargs):
        if not can_edit_contract(request.user):
            logger.warning(
                "契約書情報変更権限が無いユーザーによる一括編集アクセスを拒否しました: employee_no=%s",
                request.user.employee_no,
            )
            raise PermissionDenied("契約書を編集する権限がありません。")
        return super().dispatch(request, *args, **kwargs)

    def _state(self, request):
        state = bulk_edit_services.get_bulk_edit_state(request.session, BULK_EDIT_SESSION_KEY)
        if not state:
            messages.error(request, "編集対象が選択されていません。検索結果一覧からやり直してください。")
            return None
        return state

    def get(self, request):
        state = self._state(request)
        if state is None:
            return redirect("contracts:search")

        self.object = get_object_or_404(
            Contract.objects.prefetch_related("related_files"),
            pk=state["pks"][state["index"]],
            is_deleted=False,
        )
        form = self._build_form()
        token = issue_token(request.session, self.form_id)
        return render(request, self.template_name, self._context(request, form, token, state))

    def post(self, request):
        state = self._state(request)
        if state is None:
            return redirect("contracts:search")

        self.object = get_object_or_404(
            Contract.objects.prefetch_related("related_files"),
            pk=state["pks"][state["index"]],
            is_deleted=False,
        )
        submitted_token = request.POST.get("token", "")
        if not consume_token(request.session, self.form_id, submitted_token):
            messages.error(request, "二重に送信された可能性があるため処理を中断しました。もう一度やり直してください。")
            return redirect("contracts:bulk_edit")

        form = self._build_form(data=request.POST)
        if not form.is_valid():
            token = issue_token(request.session, self.form_id)
            return render(request, self.template_name, self._context(request, form, token, state))

        contract = self.object
        remove_ids = parse_remove_related_ids(
            request.POST.get("remove_related_ids", ""), employee_no=request.user.employee_no
        )
        new_related_files = request.FILES.getlist("related_files")
        try:
            apply_contract_edit(contract, form.cleaned_data, request.user, remove_ids, new_related_files)
        except OSError:
            logger.exception(
                "契約書の一括編集処理中にファイルI/Oエラーが発生しました: contract_id=%s, employee_no=%s",
                contract.pk,
                request.user.employee_no,
            )
            messages.error(request, "ファイルの保存に失敗しました。もう一度お試しください。")
            token = issue_token(request.session, self.form_id)
            return render(request, self.template_name, self._context(request, form, token, state))
        except DBError:
            logger.exception(
                "契約書の一括編集処理中にDBエラーが発生しました: contract_id=%s, employee_no=%s",
                contract.pk,
                request.user.employee_no,
            )
            messages.error(request, "更新に失敗しました。もう一度お試しください。")
            token = issue_token(request.session, self.form_id)
            return render(request, self.template_name, self._context(request, form, token, state))

        audit_services.log(
            employee=request.user,
            action="保管画面２ 更新",
            event_message=f"契約書「{contract.title}」を更新しました。",
        )

        total = len(state["pks"])
        index = state["index"]
        if request.POST.get("bulk_nav") == "prev" and index > 0:
            bulk_edit_services.set_bulk_edit_index(request.session, BULK_EDIT_SESSION_KEY, index - 1)
            return redirect("contracts:bulk_edit")
        if index < total - 1:
            bulk_edit_services.set_bulk_edit_index(request.session, BULK_EDIT_SESSION_KEY, index + 1)
            return redirect("contracts:bulk_edit")

        edited_contracts_by_pk = {c.pk: c for c in Contract.objects.filter(pk__in=state["pks"])}
        edited_contracts = [edited_contracts_by_pk[pk] for pk in state["pks"] if pk in edited_contracts_by_pk]
        bulk_edit_services.clear_bulk_edit_state(request.session, BULK_EDIT_SESSION_KEY)
        token = issue_token(request.session, self.form_id)
        return render(
            request,
            self.template_name,
            {
                "form": form,
                "contract": self.object,
                "token": token,
                "title_field": form["title_0"],
                "complete": {"created": edited_contracts, "mode": "update"},
                "preview_kind": get_preview_kind(self.object.display_name),
                "can_download": can_download(request.user, kind="contract"),
            },
        )

    def _context(self, request, form, token, state):
        total = len(state["pks"])
        index = state["index"]
        return {
            "form": form,
            "contract": self.object,
            "token": token,
            "title_field": form["title_0"],
            "preview_kind": get_preview_kind(self.object.display_name),
            "can_download": can_download(request.user, kind="contract"),
            "bulk": {
                "index": index + 1,
                "total": total,
                "has_prev": index > 0,
                "has_next": index < total - 1,
            },
        }

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


class SearchView(LoginRequiredMixin, View):
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
            form, employee=request.user, notice=notice, pks=pks, sort_key=sort_key, sort_dir=sort_dir
        )
        paginator = Paginator(qs, self.PAGE_SIZE)
        page_obj = paginator.get_page(request.GET.get("page"))
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


class DownloadView(LoginRequiredMixin, View):
    def get(self, request, pk):
        contract = get_object_or_404(Contract, pk=pk)
        if not can_download(request.user, kind="contract"):
            logger.warning(
                "ダウンロード権限の無いユーザーによる試行: employee_no=%s contract_id=%s",
                request.user.employee_no,
                pk,
            )
            raise PermissionDenied("ダウンロード権限がありません。")
        try:
            response = FileResponse(
                contract.file.open("rb"), as_attachment=True, filename=contract.display_name
            )
        except OSError:
            # FileNotFoundError（実体欠損）だけでなくPermissionError（ロック・権限エラー等）も
            # OSErrorのサブクラスのため、ストレージI/O境界で起こりうるOSError全般をここで
            # 利用者向けのHttp404に変換する（documents.views.DownloadViewと同じ理由）。
            logger.exception("ファイル実体の取得に失敗しました: contract_id=%s", pk)
            raise Http404("ファイルが見つかりません。")
        # documents.views.DownloadViewと同じ追加対応（2026-08-12）。登録・更新・削除は記録される
        # のに、ダウンロード（誰がいつ持ち出したか）だけ監査ログに一切残っていなかった。
        audit_services.log(
            employee=request.user,
            action="契約書検索 ダウンロード",
            event_message=f"契約書「{contract.title}」をダウンロードしました。",
        )
        return response


class PreviewView(LoginRequiredMixin, View):
    """documents.views.PreviewView参照。screen-search（契約書モード）「文書イメージ」欄用。"""

    def get(self, request, pk):
        contract = get_object_or_404(Contract, pk=pk)
        if not can_download(request.user, kind="contract"):
            logger.warning(
                "プレビュー権限の無いユーザーによる試行: employee_no=%s contract_id=%s",
                request.user.employee_no,
                pk,
            )
            raise PermissionDenied("プレビュー権限がありません。")
        try:
            response = FileResponse(
                contract.file.open("rb"), as_attachment=False, filename=contract.display_name
            )
        except OSError:
            logger.exception("ファイル実体の取得に失敗しました: contract_id=%s", pk)
            raise Http404("ファイルが見つかりません。")
        # documents.views.PreviewViewと同じ追加対応（2026-08-12）。
        audit_services.log(
            employee=request.user,
            action="契約書検索 プレビュー",
            event_message=f"契約書「{contract.title}」をプレビュー表示しました。",
        )
        return response


class BulkDownloadView(LoginRequiredMixin, View):
    """screen-search（契約書モード）「一括ダウンロード」。documents.views.BulkDownloadViewと同様
    （xlsx 検索・閲覧・変更!B596-600「※文書管理と同じ」によりB264-265のルールを準用、
    要再確認No.22の「契約書-ダウンロード」フラグで権限判定）。
    """

    def post(self, request):
        pks = request.POST.getlist("pks")
        if not pks:
            messages.error(request, "ダウンロードする契約書を選択してください。")
            return redirect("contracts:search")
        if not can_download(request.user, kind="contract"):
            logger.warning(
                "ダウンロード権限の無いユーザーによる一括ダウンロード試行: employee_no=%s",
                request.user.employee_no,
            )
            raise PermissionDenied("ダウンロード権限がありません。")

        # pksはURLパスコンバータを経由しない生のPOST値のため、改ざんや誤ったリンク等で
        # 数値以外が混入し得る（contracts.search_services.build_queryset参照）。無効な値は
        # 除外しつつ、不正アクセス試行の兆候として警告ログに残す。
        valid_pks = []
        for p in pks:
            try:
                valid_pks.append(int(p))
            except (TypeError, ValueError):
                logger.warning(
                    "一括ダウンロードの選択値(pks)に不正な値が含まれていたため除外しました: "
                    "employee_no=%s value=%r",
                    request.user.employee_no,
                    p,
                )

        import io
        import zipfile

        from django.http import HttpResponse

        contracts = Contract.objects.filter(pk__in=valid_pks, is_deleted=False)
        total_count = contracts.count()
        missing_count = 0
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for contract in contracts:
                try:
                    with contract.file.open("rb") as fh:
                        zf.writestr(contract.file.name.rsplit("/", 1)[-1], fh.read())
                except FileNotFoundError:
                    # 1件のファイル実体欠損でZIP全体のダウンロードを失敗させない設計判断
                    # （documents.views.BulkDownloadViewと同じ理由）。件数の不一致は下の
                    # messages.warningで利用者にも案内する。
                    logger.exception("一括ダウンロード中にファイル実体が見つかりません: contract_id=%s", contract.pk)
                    missing_count += 1

        logger.info(
            "一括ダウンロードを実行しました: employee_no=%s 件数=%s", request.user.employee_no, total_count
        )
        # documents.views.BulkDownloadViewと同じ追加対応（2026-08-12）。ZIPに含まれる契約書数だけ
        # ログが増殖しないよう、一括操作1回につき1件だけ記録する。
        audit_services.log(
            employee=request.user,
            action="契約書検索 一括ダウンロード",
            event_message=f"契約書{total_count}件を一括ダウンロードしました。",
        )
        if missing_count:
            messages.warning(
                request,
                f"選択した{total_count}件中{missing_count}件のファイルが見つからなかったため、"
                "ダウンロードされたZIPに含まれていません。",
            )
        response = HttpResponse(buffer.getvalue(), content_type="application/zip")
        response["Content-Disposition"] = 'attachment; filename="contracts.zip"'
        return response


class DeleteView(LoginRequiredMixin, View):
    """詳細ポップアップ「削除」ボタン。論理削除（is_deleted=True）のみを行う。

    documents.views.DeleteViewと同じ理由（2026-08-12にユーザー依頼で追加した「ゴミ箱保管中の
    契約書を削除ボタンで完全削除する」機能を、Rev1.2改訂〈xlsx 検索・閲覧・変更!B659,B663
    「削除されている契約書は、ボタンを非表示とする」〉でユーザー判断によりxlsx優先とし、
    2026-08-24に廃止した）。AJAX呼び出し時はJsonResponseを返す
    （fetch().then(r=>r.json())とのプロトコル不整合の修正）。
    """

    def post(self, request, pk):
        is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

        try:
            contract = get_object_or_404(Contract.objects.prefetch_related("related_files"), pk=pk)
        except Http404:
            # documents.views.DeleteViewと同じ理由（common.js側はfetch().then(r=>r.json())で
            # 応答をJSONとしてparseするため、AJAX時にHTML 404を返すと壊れる）。
            if is_ajax:
                return JsonResponse({"success": False, "message": "対象の契約書が見つかりません。"}, status=404)
            raise

        if not can_delete(contract):
            # xlsx 検索・閲覧・変更!B659,B663,B664-665「削除済みの契約書、および初回登録から
            # 1週間以上経過しているものは削除不可。ボタンを非表示にする」。
            # documents.views.DeleteViewと同じ理由でサーバー側でも拒否する。
            logger.warning(
                "削除できない契約書への削除操作を拒否しました: employee_no=%s contract_id=%s is_deleted=%s",
                request.user.employee_no,
                pk,
                contract.is_deleted,
            )
            message = "この契約書は既に削除されています。" if contract.is_deleted else "保存から1週間以上経過した契約書は削除できません。"
            if is_ajax:
                return JsonResponse({"success": False, "message": message}, status=403)
            raise PermissionDenied(message)

        try:
            contract.is_deleted = True
            contract.deleted_at = timezone.now()
            contract.save(update_fields=["is_deleted", "deleted_at"])
        except DBError:
            logger.exception("契約書の削除処理に失敗しました: contract_id=%s", pk)
            if is_ajax:
                return JsonResponse(
                    {"success": False, "message": "削除に失敗しました。もう一度お試しください。"}, status=500
                )
            messages.error(request, "削除に失敗しました。もう一度お試しください。")
            return redirect("contracts:search")

        audit_services.log(
            employee=request.user,
            action="検索・閲覧画面 削除",
            event_message=f"契約書「{contract.title}」を削除しました。",
        )
        success_message = "契約書を削除しました。"

        if is_ajax:
            return JsonResponse({"success": True, "message": success_message})
        messages.success(request, success_message)
        return redirect("contracts:search")


def _strip_ext(filename):
    return filename.rsplit(".", 1)[0] if "." in filename else filename


def _file_rows(form, pending):
    return [(item, form[f"title_{i}"]) for i, item in enumerate(pending)]


def _pending_preview_context(request, pending):
    """documents.views._pending_preview_contextと同じ理由（保管画面２のPDFモックプレビューを、
    画像／PDFの場合のみPendingPreviewView経由の実データ表示に切り替える）。"""
    preview_kinds = [get_preview_kind(item["original_name"]) or "" for item in pending]
    if can_download(request.user, kind="contract"):
        preview_urls = [
            reverse("contracts:upload_step2_preview", args=[i]) for i in range(len(pending))
        ]
    else:
        preview_urls = []
    return {"preview_kinds": preview_kinds, "preview_urls": preview_urls}


class PendingPreviewView(LoginRequiredMixin, View):
    """documents.views.PendingPreviewViewと同じ理由（保管画面２・登録前の保留ファイルを
    セッションの一覧indexで参照して実データを返す）。"""

    def get(self, request, index):
        if not can_download(request.user, kind="contract"):
            logger.warning(
                "プレビュー権限の無いユーザーによる試行: employee_no=%s", request.user.employee_no
            )
            raise PermissionDenied("プレビュー権限がありません。")
        pending = upload_services.get_pending_files(request.session, PENDING_SESSION_KEY)
        if index >= len(pending):
            raise Http404("プレビュー対象のファイルが見つかりません。")
        item = pending[index]
        try:
            temp_file = upload_services.open_pending_file(item["temp_name"])
        except upload_services.PendingFileStorageError:
            raise Http404("プレビュー対象のファイルが見つかりません。")
        return FileResponse(temp_file, as_attachment=False, filename=item["original_name"])
