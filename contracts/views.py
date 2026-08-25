import logging

from django.conf import settings
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
from contracts.models import Contract, RelatedFile
from contracts.search_services import build_queryset
from contracts.services import (
    apply_contract_edit,
    build_zip_archive,
    calculate_expiry_date,
    parse_remove_related_ids,
    scoped_get_object_or_404,
)
from core import bulk_edit_services, record_views, upload_services, upload_views
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
    """screen-storage2（契約書モード・登録）。関連書類の添付は、バッチ内ファイルが1件の場合のみ
    対応する（複数契約書を一括登録するバッチに対して関連書類をどう振り分けるかはHTML/xlsxに
    明記が無いため、あいまいさを避けるスコープ限定）。保管フロー全体のURL直叩き対策は
    RequiresContractEditMixin参照。
    """

    template_name = "contracts/storage2.html"
    form_id = "contracts_upload_step2"

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
                "file_rows": upload_views.file_rows(form, pending),
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
                    "file_rows": upload_views.file_rows(form, pending),
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
        created_related = []
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
                        created_related.append(
                            RelatedFile.objects.create(contract=contract, file=related, display_order=i)
                        )
                    audit_services.log(
                        employee=request.user,
                        action="保管画面２ 登録",
                        event_message=f"契約書「{contract.title}」を保管しました。",
                    )
                    created.append(contract)
        except (OSError, DBError):
            # open_pending_file()／file.save()（本体・関連書類とも）でのファイルI/O失敗に加え、
            # contract.save()/RelatedFile.objects.create()でのDB制約違反等（DBError）も対象にする
            # （documents.views.UploadStep2Viewと同じ理由。品質レビューで発見：以前はOSErrorしか
            # 捕捉しておらずDBErrorは未捕捉のまま生の500エラーになっていた）。
            # transaction.atomic()によりDBへの登録はロールバックされるが、ロールバック対象の
            # 契約書・関連書類について既にストレージへ書き込み済みだったファイル実体はDB
            # トランザクションの対象外のため孤児化する。created/created_relatedに積まれた
            # （=save()まで成功していた）ファイル実体をここで明示的に削除して孤児ファイルを防ぐ。
            for contract in created:
                contract.file.delete(save=False)
            for related_file in created_related:
                related_file.file.delete(save=False)
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
                "token": token,
                "mode": "create",
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
            Contract.objects.prefetch_related("related_files").filter(is_deleted=False),
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


class BulkEditStartView(RequiresContractEditMixin, View):
    """screen-search「一括編集」ボタン（契約書側）。documents.views.BulkEditStartViewと同じ設計
    （詳細はそちらのdocstring参照）だが、Rev1.2で追加された「契約書-契約書-契約書情報変更」
    がOFFの職員は一括編集も不可（RequiresContractEditMixin参照）。
    """

    def post(self, request):
        pks = request.POST.getlist("pks")
        if not pks:
            messages.error(request, "編集する契約書を選択してください。")
            return redirect("contracts:search")

        # pks検証・部署スコープ絞り込みの実体はcore.bulk_edit_services.resolve_ordered_pksに
        # 集約済み（documents.views.BulkEditStartViewとの重複をコード監査で発見、2026-08-25修正）。
        ordered_pks = bulk_edit_services.resolve_ordered_pks(
            pks, model=Contract, dept_ids_resolver=contract_searchable_department_ids, employee=request.user
        )
        if not ordered_pks:
            messages.error(request, "編集する契約書を選択してください。")
            return redirect("contracts:search")

        bulk_edit_services.start_bulk_edit(request.session, BULK_EDIT_SESSION_KEY, ordered_pks)
        return redirect("contracts:bulk_edit")


class BulkEditView(RequiresContractEditMixin, View):
    """一括編集ウィザード本体（契約書側）。documents.views.BulkEditViewと同じ設計・同じ
    save-as-you-go方式（詳細はそちらのdocstring参照）。ContractEditViewと同じく関連書類の
    追加・削除もステップの保存に含まれる。BulkEditStartViewと同じくRev1.2の
    「契約書-契約書-契約書情報変更」がOFFの職員はアクセス不可（RequiresContractEditMixin参照）。
    """

    template_name = "contracts/edit.html"
    form_id = "contracts_bulk_edit"

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

        # セキュリティレビューで発見：部署スコープ外の契約書へのセッション改ざん・URL直打ちを
        # 防ぐ（contracts.services.scoped_get_object_or_404 docstring参照。2026-08-25修正）。
        self.object = scoped_get_object_or_404(
            Contract.objects.prefetch_related("related_files").filter(is_deleted=False),
            request.user,
            state["pks"][state["index"]],
        )
        form = self._build_form()
        token = issue_token(request.session, self.form_id)
        return render(request, self.template_name, self._context(request, form, token, state))

    def post(self, request):
        state = self._state(request)
        if state is None:
            return redirect("contracts:search")

        # セキュリティレビューで発見：部署スコープ外の契約書へのセッション改ざん・URL直打ちを
        # 防ぐ（contracts.services.scoped_get_object_or_404 docstring参照。2026-08-25修正）。
        self.object = scoped_get_object_or_404(
            Contract.objects.prefetch_related("related_files").filter(is_deleted=False),
            request.user,
            state["pks"][state["index"]],
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
    audit_action = "契約書検索 ダウンロード"
    entity_label = "契約書"


class PreviewView(LoginRequiredMixin, record_views.BaseFileServeView):
    """documents.views.PreviewView参照。screen-search（契約書モード）「文書イメージ」欄用。実体は
    core.record_views.BaseFileServeViewに集約済み（documents.views.PreviewViewとの重複を
    コード監査で発見、2026-08-25修正）。
    """

    model = Contract
    kind = "contract"
    scoped_lookup = staticmethod(scoped_get_object_or_404)
    as_attachment = False
    audit_action = "契約書検索 プレビュー"
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
    audit_action = "契約書検索 一括ダウンロード"
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


def _strip_ext(filename):
    return filename.rsplit(".", 1)[0] if "." in filename else filename


def _pending_preview_context(request, pending):
    return upload_views.build_pending_preview_context(
        request, pending, kind="contract", preview_url_name="contracts:upload_step2_preview"
    )


class PendingPreviewView(RequiresContractEditMixin, upload_views.BasePendingPreviewView):
    """実体はcore.upload_views.BasePendingPreviewViewに集約済み（documents.views.
    PendingPreviewViewとの重複をコード監査で発見、2026-08-25修正）。UploadStep1View/
    UploadStep2Viewと同じ保管フローの一部であるため、RequiresContractEditMixinを適用する
    （品質レビューで発見：以前はcan_downloadのみで判定しており、セッション中にcontract_edit
    権限を剥奪された利用者でも保留ファイルの中身を参照できてしまっていた。2026-08-25修正）。
    """

    pending_session_key = PENDING_SESSION_KEY
    kind = "contract"
