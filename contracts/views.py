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
from contracts.models import Contract, RelatedFile
from contracts.search_services import build_queryset
from contracts.services import (
    apply_contract_edit,
    build_zip_archive,
    calculate_expiry_date,
    contract_edit_is_dirty,
    parse_remove_related_ids,
    scoped_get_object_or_404,
)
from core import (
    bulk_edit_services,
    deletion_services,
    record_views,
    search_services,
    upload_services,
    upload_views,
)
from core.double_submit import consume_token, issue_token
from core.file_type_services import get_preview_kind
from core.upload_services import PendingFileStorageError
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
    documents.views.UploadStep2View／UploadStep2Form docstring参照。関連書類は
    `related_files_{index}` で以前から一括登録対応済み）。保存ループは `form.file_data(i)` を通す。
    保管フロー全体のURL直叩き対策は RequiresContractEditMixin参照。
    """

    template_name = "contracts/storage2.html"
    form_id = "contracts_upload_step2"

    def _render_form(self, request, form, pending, active_doc_index=0):
        """GET・バリデーションエラー再描画・「削除」後の再描画で共通の保管画面２レンダリング。"""
        token = issue_token(request.session, self.form_id)
        return render(
            request,
            self.template_name,
            {
                "form": form,
                "file_rows": upload_views.file_rows(form, pending),
                "file_field_sets": upload_views.file_field_sets(
                    form, pending, UploadStep2Form.PER_FILE_FIELDS
                ),
                "active_doc_index": active_doc_index,
                "token": token,
                "mode": "create",
                **_pending_preview_context(request, pending),
            },
        )

    def _handle_remove(self, request, pending):
        """「削除」ボタン＝表示中ファイルのアップロード取り消し。残りのファイルの入力値を
        詰め直して再描画する（documents.views.UploadStep2View._handle_remove と同じ。
        契約書の関連書類はファイル入力のためブラウザ仕様で復元不可＝選び直しが必要）。"""
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
        messages.info(request, f"「{removed['original_name']}」のアップロードを取り消しました。")
        return self._render_form(
            request, form, remaining, active_doc_index=min(index, len(remaining) - 1)
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
            return self._render_form(request, form, pending, active_doc_index=error_index)

        can_select = can_select_department(request.user)
        save_date = timezone.now()
        created = []
        created_related = []
        try:
            # 複数契約書を1回のリクエストでまとめて登録するため、途中の1件（本体または
            # 関連書類）でファイルI/O例外が起きた場合に一部だけDBへコミット済みという
            # 中途半端な状態を残さないよう、ループ全体を1トランザクションにする
            # （documents.views.UploadStep2Viewと同じ理由。原本フィデリティ監査で発見）。
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
                    # イベントメッセージは原本index.html:3320の操作履歴ログサンプル
                    # 「文書　アップロード｜ファイル名：契約書_100」に合わせ、タイトルではなく
                    # 実ファイル名(display_name)を「ファイル名：」形式で記録する
                    # （原本フィデリティ監査で発見：以前は原本に無い独自形式だった）。
                    audit_services.log(
                        employee=request.user,
                        action="保管画面２ 登録",
                        event_message=f"ファイル名：{contract.display_name}",
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
                "file_field_sets": upload_views.file_field_sets(
                    form, pending, UploadStep2Form.PER_FILE_FIELDS
                ),
                "active_doc_index": 0,
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
                    "preview_kind": get_preview_kind(self.object.display_name),
                    "can_download": can_download(request.user, kind="contract"),
                    **_edit_delete_context(self.object),
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

        # 開始のたび、前回の中断で残ったステージ内容（関連書類の一時ファイル含む）を掃除する。
        bulk_edit_services.discard_bulk_edit(request.session, BULK_EDIT_SESSION_KEY)
        bulk_edit_services.start_bulk_edit(request.session, BULK_EDIT_SESSION_KEY, ordered_pks)
        return redirect("contracts:bulk_edit")


# 一括編集で各ページの生POST値としてセッションへ退避するフォームフィールド名。
CONTRACT_BULK_FORM_FIELDS = (
    "department", "group", "category", "year",
    "contract_date", "contract_period_start", "contract_period_end",
    "renewal_date", "contract_amount", "contract_partner", "memo", "title_0",
)


class BulkEditView(RequiresContractEditMixin, View):
    """一括編集ウィザード本体（契約書側・ステージング型。2026-08-28ユーザー確定）。
    documents.views.BulkEditViewと同じ設計（入力値・削除マーク・関連書類の増減を「更新」まで
    セッション〈＋一時ファイル領域〉にステージし、「更新」で全ページ検証→変更のあったものだけを
    1トランザクションで確定）。関連書類の追加ファイルは MEDIA_ROOT/tmp_uploads/ に退避し、
    「キャンセル」で実体ごと破棄する。BulkEditStartViewと同じくRev1.2の「契約書-契約書-
    契約書情報変更」がOFFの職員はアクセス不可（RequiresContractEditMixin参照）。
    """

    template_name = "contracts/edit.html"
    form_id = "contracts_bulk_edit"

    def _state(self, request):
        state = bulk_edit_services.get_bulk_edit_state(request.session, BULK_EDIT_SESSION_KEY)
        if not state:
            messages.error(request, "編集対象が選択されていません。検索結果一覧からやり直してください。")
            return None
        return state

    def _current_object(self, request, state):
        # セキュリティレビューで発見：部署スコープ外の契約書へのセッション改ざん・URL直打ちを防ぐ。
        return scoped_get_object_or_404(
            Contract.objects.prefetch_related("related_files").filter(is_deleted=False),
            request.user,
            state["pks"][state["index"]],
        )

    def get(self, request):
        state = self._state(request)
        if state is None:
            return redirect("contracts:search")
        self.object = self._current_object(request, state)
        marked_delete = bulk_edit_services.is_marked_for_delete(state, self.object.pk)
        staged = bulk_edit_services.staged_page_data(state, self.object.pk)
        form = self._build_form(self.object, data=staged, marked_delete=marked_delete)
        token = issue_token(request.session, self.form_id)
        return render(
            request, self.template_name, self._context(request, form, token, state, marked_delete)
        )

    def post(self, request):
        if request.POST.get("bulk_action") == "cancel":
            bulk_edit_services.discard_bulk_edit(request.session, BULK_EDIT_SESSION_KEY)
            return redirect("contracts:search")

        state = self._state(request)
        if state is None:
            return redirect("contracts:search")
        self.object = self._current_object(request, state)

        submitted_token = request.POST.get("token", "")
        if not consume_token(request.session, self.form_id, submitted_token):
            messages.error(request, "二重に送信された可能性があるため処理を中断しました。もう一度やり直してください。")
            return redirect("contracts:bulk_edit")

        marked_delete = bulk_edit_services.is_marked_for_delete(state, self.object.pk)
        if not marked_delete:
            bulk_edit_services.stage_page(
                request.session,
                BULK_EDIT_SESSION_KEY,
                self.object.pk,
                {k: request.POST.get(k, "") for k in CONTRACT_BULK_FORM_FIELDS},
            )
            # 関連書類の増減も同時にステージ（アップロード分は一時領域へ退避）。
            new_files = request.FILES.getlist("related_files")
            add_refs = []
            if new_files:
                try:
                    add_refs = upload_services.stash_files_to_tmp(new_files)
                except PendingFileStorageError:
                    logger.exception(
                        "一括編集：関連書類の一時退避に失敗しました: employee_no=%s", request.user.employee_no
                    )
                    messages.error(request, "ファイルの保存に失敗しました。もう一度お試しください。")
                    return redirect("contracts:bulk_edit")
            remove_ids = parse_remove_related_ids(
                request.POST.get("remove_related_ids", ""), employee_no=request.user.employee_no
            )
            if add_refs or remove_ids:
                bulk_edit_services.stage_related(
                    request.session, BULK_EDIT_SESSION_KEY, self.object.pk,
                    add_refs=add_refs, remove_ids=remove_ids,
                )

        total = len(state["pks"])
        index = state["index"]
        action = request.POST.get("bulk_action")
        nav = request.POST.get("bulk_nav")

        if action == "toggle_delete":
            # セキュリティレビュー M-1: 削除マークを「付ける」操作は can_delete() をサーバー側で
            # 検証する（マーク解除は常に許可）。documents.views.BulkEditView と同じ扱い。
            if not marked_delete and not deletion_services.can_delete(self.object):
                logger.warning(
                    "一括編集で削除できない契約書への削除マークを拒否しました: employee_no=%s pk=%s",
                    request.user.employee_no,
                    self.object.pk,
                )
                messages.error(
                    request, deletion_services.deletion_denial_message(self.object, entity_name="契約書")
                )
                return redirect("contracts:bulk_edit")
            bulk_edit_services.toggle_delete_mark(request.session, BULK_EDIT_SESSION_KEY, self.object.pk)
            return redirect("contracts:bulk_edit")
        if nav == "prev":
            if index > 0:
                bulk_edit_services.set_bulk_edit_index(request.session, BULK_EDIT_SESSION_KEY, index - 1)
            return redirect("contracts:bulk_edit")
        if nav == "next":
            if index < total - 1:
                bulk_edit_services.set_bulk_edit_index(request.session, BULK_EDIT_SESSION_KEY, index + 1)
            return redirect("contracts:bulk_edit")

        return self._commit(request)

    def _commit(self, request):
        state = bulk_edit_services.get_bulk_edit_state(request.session, BULK_EDIT_SESSION_KEY)
        pks = state["pks"]
        to_delete = set(state.get("to_delete", []))
        staged = state.get("staged", {})
        objs_by_pk = {
            c.pk: c for c in Contract.objects.prefetch_related("related_files").filter(pk__in=pks)
        }

        # --- 検証パス ---
        forms_by_pk = {}
        invalid = []  # [(index, form)]
        for i, pk in enumerate(pks):
            if pk in to_delete or str(pk) not in staged or pk not in objs_by_pk:
                continue
            f = self._build_form(objs_by_pk[pk], data=staged[str(pk)])
            if f.is_valid():
                forms_by_pk[pk] = f
            else:
                invalid.append((i, f))

        if invalid:
            first_index, first_form = invalid[0]
            bulk_edit_services.set_bulk_edit_index(request.session, BULK_EDIT_SESSION_KEY, first_index)
            messages.error(request, f"{first_index + 1}件目に入力エラーがあります。修正してください。")
            self.object = objs_by_pk[pks[first_index]]
            token = issue_token(request.session, self.form_id)
            state = bulk_edit_services.get_bulk_edit_state(request.session, BULK_EDIT_SESSION_KEY)
            return render(
                request,
                self.template_name,
                self._context(request, first_form, token, state, marked_delete=False),
            )

        # --- 削除予定pkの can_delete() 検証パス（セキュリティレビュー M-1、documents 側と同じ扱い） ---
        undeletable = [
            i
            for i, pk in enumerate(pks)
            if pk in to_delete and pk in objs_by_pk and not deletion_services.can_delete(objs_by_pk[pk])
        ]
        if undeletable:
            first_index = undeletable[0]
            self.object = objs_by_pk[pks[first_index]]
            bulk_edit_services.set_bulk_edit_index(request.session, BULK_EDIT_SESSION_KEY, first_index)
            logger.warning(
                "一括編集で削除できない契約書への削除確定を拒否しました: employee_no=%s pk=%s is_deleted=%s",
                request.user.employee_no,
                self.object.pk,
                self.object.is_deleted,
            )
            messages.error(
                request,
                f"{first_index + 1}件目: "
                + deletion_services.deletion_denial_message(self.object, entity_name="契約書"),
            )
            token = issue_token(request.session, self.form_id)
            state = bulk_edit_services.get_bulk_edit_state(request.session, BULK_EDIT_SESSION_KEY)
            return render(
                request,
                self.template_name,
                self._context(
                    request, self._build_form(self.object, marked_delete=True), token, state, marked_delete=True
                ),
            )

        # --- 確定パス ---
        opened_files = []
        status_by_pk = {}
        try:
            with transaction.atomic():
                for pk in pks:
                    obj = objs_by_pk.get(pk)
                    if obj is None:
                        continue
                    if pk in to_delete:
                        obj.is_deleted = True
                        obj.deleted_at = timezone.now()
                        obj.save(update_fields=["is_deleted", "deleted_at"])
                        audit_services.log(
                            employee=request.user,
                            action="保管画面２ 削除",
                            event_message=f"契約書「{obj.title}」を削除しました。",
                        )
                        status_by_pk[pk] = "削除"
                    elif pk in forms_by_pk:
                        f = forms_by_pk[pk]
                        bucket = bulk_edit_services.staged_related_for(state, pk)
                        related_changed = bool(bucket["add"] or bucket["remove"])
                        if contract_edit_is_dirty(
                            obj, f.cleaned_data, request.user, related_changed=related_changed
                        ):
                            new_files = []
                            for ref in bucket["add"]:
                                fh = upload_services.open_pending_file(ref["temp_name"])
                                fh.name = ref["original_name"]
                                opened_files.append(fh)
                                new_files.append(fh)
                            apply_contract_edit(
                                obj, f.cleaned_data, request.user, bucket["remove"], new_files
                            )
                            audit_services.log(
                                employee=request.user,
                                action="保管画面２ 更新",
                                event_message=f"契約書「{obj.title}」を更新しました。",
                            )
                            status_by_pk[pk] = "更新"
                        else:
                            status_by_pk[pk] = "更新なし"
                    else:
                        status_by_pk[pk] = "更新なし"
        except (OSError, PendingFileStorageError, DBError):
            logger.exception(
                "契約書の一括編集確定中にエラーが発生しました: employee_no=%s", request.user.employee_no
            )
            messages.error(request, "更新に失敗しました。もう一度お試しください。")
            return redirect("contracts:bulk_edit")
        finally:
            for fh in opened_files:
                try:
                    fh.close()
                except OSError:
                    pass

        bulk_edit_services.discard_staged_related_files(state)
        bulk_edit_services.clear_bulk_edit_state(request.session, BULK_EDIT_SESSION_KEY)
        return self._render_complete(request, pks, status_by_pk)

    def _render_complete(self, request, pks, status_by_pk):
        rows_objs = {c.pk: c for c in Contract.objects.filter(pk__in=pks)}
        rows = [
            {"obj": rows_objs[pk], "status": status_by_pk.get(pk, "更新なし")}
            for pk in pks
            if pk in rows_objs
        ]
        counts = {
            "updated": sum(1 for r in rows if r["status"] == "更新"),
            "unchanged": sum(1 for r in rows if r["status"] == "更新なし"),
            "deleted": sum(1 for r in rows if r["status"] == "削除"),
        }
        if not rows:
            # 更新確定の直後に対象が全件物理削除された場合（日次purgeバッチとの競合）。完了モーダルの
            # 背後に敷くフォームを描画できないため検索画面へ戻す（コードレビューC-7、2026-08-28修正）。
            messages.error(request, "編集対象が見つかりませんでした。検索結果一覧からやり直してください。")
            return redirect("contracts:search")
        self.object = rows[0]["obj"]
        form = self._build_form(self.object)
        token = issue_token(request.session, self.form_id)
        return render(
            request,
            self.template_name,
            {
                "form": form,
                "contract": self.object,
                "token": token,
                "title_field": form["title_0"],
                "complete": {"mode": "bulk", "rows": rows, "counts": counts},
                "preview_kind": get_preview_kind(self.object.display_name),
                "can_download": can_download(request.user, kind="contract"),
            },
        )

    def _context(self, request, form, token, state, marked_delete):
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
            "marked_delete": marked_delete,
            "can_delete": deletion_services.can_delete(self.object),
            "related_rows": self._related_rows(state),
        }

    def _related_rows(self, state):
        """一括編集画面の[3]関連書類の表示行。既存（ステージ済みの削除を除外）＋ステージ済みの
        追加（「追加予定」）。追加分の個別取消は用意しない（キャンセルで一括破棄する。"""
        bucket = bulk_edit_services.staged_related_for(state, self.object.pk)
        removed = set(bucket["remove"])
        rows = [
            {"kind": "existing", "id": rf.pk, "name": rf.display_name}
            for rf in self.object.related_files.all()
            if rf.pk not in removed
        ]
        rows += [{"kind": "staged_add", "id": None, "name": ref["original_name"]} for ref in bucket["add"]]
        return rows

    def _build_form(self, obj, data=None, marked_delete=False):
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
                action="契約書検索 検索",
                event_message=search_services.build_search_audit_message(form),
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


class EditDeleteView(DeleteView):
    """単独編集画面（ContractEditView、edit.html）の[4]メモ欄直下「削除」ボタン。
    documents.views.EditDeleteViewと同じ（削除自体はDeleteView＝BaseDeleteViewと同一、監査ログの
    action名だけ違う。契約書側はDeleteView継承でextra_permission_check〈can_edit_contract〉を
    引き継ぐ）。一括編集画面の削除は「更新」ボタンでまとめて確定する別方式（ステージ型）のため
    このビューは通らない。2026-08-27ユーザー確定でメモ欄クリアからレコードの論理削除に変更。
    """

    audit_action = "保管画面２ 削除"


def _strip_ext(filename):
    return filename.rsplit(".", 1)[0] if "." in filename else filename


def _pending_preview_context(request, pending):
    return upload_views.build_pending_preview_context(
        request, pending, kind="contract", preview_url_name="contracts:upload_step2_preview"
    )


def _edit_delete_context(obj):
    """edit.htmlの[4]メモ欄直下「削除」ボタン（EditDeleteView）用。documents.views._edit_delete_context
    と同じ（can_delete=Falseならテンプレートでボタンごと非表示。xlsx 保管!B581「初回登録から
    1週間以上経過・削除済みはボタンを非表示」）。"""
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
