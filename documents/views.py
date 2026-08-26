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
from core import bulk_edit_services, record_views, search_services, upload_services, upload_views
from core.double_submit import consume_token, issue_token
from core.file_type_services import get_preview_kind
from core.text_extraction_services import try_immediate_text_layer_extraction
from documents.forms import SearchForm, UploadStep2Form
from documents.models import Document
from documents.search_services import build_queryset
from documents.services import (
    apply_document_edit,
    build_zip_archive,
    calculate_expiry_date,
    document_searchable_department_ids,
    expiry_date_previews,
    scoped_get_object_or_404,
)
from permissions.services import can_download, can_select_department

logger = logging.getLogger(__name__)

PENDING_SESSION_KEY = "documents_pending_upload"
BULK_EDIT_SESSION_KEY = "documents_bulk_edit"


class UploadStep1View(LoginRequiredMixin, upload_views.BaseUploadStep1View):
    """screen-storage1（文書選択）。実体はcore.upload_views.BaseUploadStep1Viewに集約済み
    （contracts.views.UploadStep1Viewとの重複をコード監査で発見、2026-08-25修正）。"""

    template_name = "documents/storage1.html"
    pending_session_key = PENDING_SESSION_KEY
    next_url_name = "documents:upload_step2"


class UploadStep2View(LoginRequiredMixin, View):
    """screen-storage2（保管・登録）。複数ファイルを1回の入力（部署・分類・年・カテゴリー・
    保存期間・個人情報・メモ）でまとめて登録する。HTML確定版はPDFプレビュー+ページャーで
    1ファイルずつタイトルを編集する構成だが、本実装ではファイル一覧を並べてタイトルを個別入力
    する形に簡略化している（機能的には同等。フェーズ7の画面突き合わせ検証で見た目の再現度を
    再検討する）。
    """

    template_name = "documents/storage2.html"
    form_id = "documents_upload_step2"

    def get(self, request):
        pending = upload_services.get_pending_files(request.session, PENDING_SESSION_KEY)
        if not pending:
            messages.error(request, "保管する文書が選択されていません。")
            return redirect("documents:upload_step1")
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
                **_expiry_preview_context(form),
            },
        )

    def post(self, request):
        pending = upload_services.get_pending_files(request.session, PENDING_SESSION_KEY)
        if not pending:
            messages.error(request, "保管する文書が選択されていません。")
            return redirect("documents:upload_step1")

        submitted_token = request.POST.get("token", "")
        if not consume_token(request.session, self.form_id, submitted_token):
            messages.error(request, "二重に送信された可能性があるため処理を中断しました。もう一度やり直してください。")
            return redirect("documents:upload_step1")

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
                    **_expiry_preview_context(form),
                },
            )

        department = form.cleaned_data["department"]
        if not can_select_department(request.user):
            # disabledフィールドはブラウザから改ざんされてもクリーンデータには反映されない想定だが、
            # サーバー側でも権限の無いユーザーの部署指定は無視し必ず自部署にする（IDOR対策）。
            department = request.user.department

        titles = form.titles(len(pending))
        save_date = timezone.now()
        created = []
        try:
            # 複数文書を1回のリクエストでまとめて登録するため、途中の1件でファイルI/O例外が
            # 起きた場合に一部だけDBへコミット済みという中途半端な状態を残さないよう、
            # ループ全体を1トランザクションにする（原本フィデリティ監査で発見：以前はループ内で
            # document.save()の都度コミットされ、途中失敗時に一部だけ登録される恐れがあった）。
            with transaction.atomic():
                for pending_item, title in zip(pending, titles):
                    document = Document(
                        title=title,
                        department=department,
                        group=form.cleaned_data["group"],
                        category=form.cleaned_data["category"],
                        year=form.cleaned_data["year"],
                        retention_period=form.cleaned_data["retention_period"],
                        privacy_flag=form.cleaned_data["privacy_flag"],
                        memo=form.cleaned_data["memo"],
                        uploader=request.user,
                        expiry_date=calculate_expiry_date(
                            save_date.date(), form.cleaned_data["retention_period"]
                        ),
                    )
                    temp_file = upload_services.open_pending_file(pending_item["temp_name"])
                    try:
                        document.file.save(pending_item["original_name"], temp_file, save=False)
                    finally:
                        temp_file.close()
                    document.save()
                    # イベントメッセージは原本index.html:3320の操作履歴ログサンプル
                    # 「文書　アップロード｜ファイル名：契約書_100」に合わせ、タイトルではなく
                    # 実ファイル名(display_name)を「ファイル名：」形式で記録する
                    # （原本フィデリティ監査で発見：以前は原本に無い独自形式だった）。
                    audit_services.log(
                        employee=request.user,
                        action="保管画面２ 登録",
                        event_message=f"ファイル名：{document.display_name}",
                        personal_info_flag=document.privacy_flag,
                    )
                    created.append(document)
        except (OSError, DBError):
            # open_pending_file()／file.save()でのファイルI/O失敗（一時ファイル欠損・ディスク
            # 容量不足等）に加え、document.save()でのDB制約違反等（IntegrityError/
            # OperationalError等のDBError）も対象にする（品質レビューで発見：以前はOSErrorしか
            # 捕捉しておらずDBErrorは未捕捉のまま生の500エラーになっていた）。
            # transaction.atomic()によりDBへの登録はロールバックされ、DBには一部だけ登録された
            # 不整合な状態は残らないが、ロールバック対象の文書について既にストレージへ書き込み
            # 済みだったファイル実体はDBトランザクションの対象外のため孤児化する（品質レビューで
            # 発見：DB側の不整合のみ解決されておりファイル実体側は未解決だった）。createdに
            # 積まれた（=document.save()まで成功していた）文書のファイル実体をここで明示的に
            # 削除して孤児ファイルを防ぐ。tmp_uploads側の一時ファイルとセッションのpendingは
            # あえてクリアせず、利用者が保管画面２からやり直せるようにする。
            for document in created:
                document.file.delete(save=False)
            logger.exception(
                "文書の保管処理中にエラーが発生しました: employee_no=%s", request.user.employee_no
            )
            messages.error(request, "ファイルの保存に失敗しました。もう一度お試しください。")
            return redirect("documents:upload_step2")

        # 全文検索：テキスト層のあるPDFはここで同期抽出し、登録と同時に全文検索の対象にする
        # （外部通信を伴わずローカルで完結するpdfplumberのみのため応答遅延は小さい）。
        # transaction.atomic()のコミット後に行うことで、DBロック保持期間に本文抽出の所要時間を
        # 含めない。スキャン文書・解析失敗時は何もせず、後続のバッチ
        # （core.management.commands.extract_pending_pdf_text）に処理を委ねる。
        for document in created:
            try_immediate_text_layer_extraction(document, label="document")

        upload_services.clear_pending_files(request.session, PENDING_SESSION_KEY)
        # 原本index.html:1603-1645のstartRegisterMock()はscreen-storage2から画面遷移せず、
        # overlay-modalを重ねて表示するだけ（原本フィデリティ監査で発見：以前はstorage_complete.html
        # という別テンプレートに丸ごと差し替えており、モーダルの背後に保管画面が残らなかった）。
        # そのためここでも同じstorage2.htmlをGET時と同じcontextで再描画し、completeキーで
        # 完了モーダルを重ねる。pending/formはこの時点でまだローカル変数に残っているため
        # 再利用できる（sessionのpendingは既にクリア済みだが、file_rows表示には影響しない）。
        # ただしプレビュー画像URLは、上のclear_pending_filesで一時ファイル実体・セッション双方が
        # 既に消えているためPendingPreviewView（保留ファイルindex参照）は使えない。登録済みの
        # createdはDBのpkを持つため、代わりにPreviewView（pkベース）を指す点がGET/バリデーション
        # エラー時（_pending_preview_context）と異なる。
        if can_download(request.user, kind="document"):
            preview_urls = [reverse("documents:preview", args=[d.pk]) for d in created]
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
                "preview_kinds": [get_preview_kind(d.display_name) or "" for d in created],
                "preview_urls": preview_urls,
                **_expiry_preview_context(form),
            },
        )


class DocumentEditView(LoginRequiredMixin, UpdateView):
    """screen-storage2（変更モード、検索・閲覧画面の詳細ポップアップ「変更」ボタンから遷移）。"""

    model = Document
    template_name = "documents/edit.html"
    context_object_name = "document"
    form_id = "documents_edit"

    def get_object(self, queryset=None):
        # セキュリティレビューで発見：部署スコープ外の文書へのURL直打ちを防ぐ
        # （documents.services.scoped_get_object_or_404 docstring参照。2026-08-25修正）。
        return scoped_get_object_or_404(
            Document.objects.filter(is_deleted=False), self.request.user, self.kwargs["pk"]
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
                "document": self.object,
                "token": token,
                "title_field": form["title_0"],
                "preview_kind": get_preview_kind(self.object.display_name),
                "can_download": can_download(request.user, kind="document"),
                **_expiry_preview_context(form),
            },
        )

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        submitted_token = request.POST.get("token", "")
        if not consume_token(request.session, self.form_id, submitted_token):
            messages.error(request, "二重に送信された可能性があるため処理を中断しました。もう一度やり直してください。")
            return redirect("documents:edit", pk=self.object.pk)

        form = self._build_form(data=request.POST)
        if not form.is_valid():
            token = issue_token(request.session, self.form_id)
            return render(
                request,
                self.template_name,
                {
                    "form": form,
                    "document": self.object,
                    "token": token,
                    "title_field": form["title_0"],
                    "preview_kind": get_preview_kind(self.object.display_name),
                    "can_download": can_download(request.user, kind="document"),
                    **_expiry_preview_context(form),
                },
            )

        try:
            doc = apply_document_edit(self.object, form.cleaned_data, request.user)
        except DBError:
            # contracts.views.ContractEditView.postと同じ理由（品質レビューで発見：documents側は
            # apply_document_edit()を裸で呼んでおり、DB制約違反等が未捕捉のまま生の500になって
            # いた。2026-08-25修正）。
            logger.exception(
                "文書の更新処理中にDBエラーが発生しました: document_id=%s, employee_no=%s",
                self.object.pk,
                request.user.employee_no,
            )
            messages.error(request, "更新に失敗しました。もう一度お試しください。")
            return redirect("documents:edit", pk=self.object.pk)
        audit_services.log(
            employee=request.user,
            action="保管画面２ 更新",
            event_message=f"文書「{doc.title}」を更新しました。",
            personal_info_flag=doc.privacy_flag,
        )
        # UploadStep2View.postと同じ理由（別テンプレートへの丸ごと差し替えをやめ、edit.htmlを
        # 再描画した上でcomplete経由で完了モーダルを重ねる）。
        token = issue_token(request.session, self.form_id)
        return render(
            request,
            self.template_name,
            {
                "form": form,
                "document": self.object,
                "token": token,
                "title_field": form["title_0"],
                "complete": {"created": [doc], "mode": "update"},
                "preview_kind": get_preview_kind(self.object.display_name),
                "can_download": can_download(request.user, kind="document"),
                **_expiry_preview_context(form),
            },
        )

    def _build_form(self, data=None):
        return UploadStep2Form(
            data,
            employee=self.request.user,
            file_count=1,
            edit_mode=True,
            initial_titles=[self.object.title],
            initial={
                "department": self.object.department_id,
                "group": self.object.group_id,
                "category": self.object.category_id,
                "year": self.object.year,
                "retention_period": self.object.retention_period_id,
                "privacy_flag": self.object.privacy_flag,
                "memo": self.object.memo,
            },
        )


class BulkEditStartView(LoginRequiredMixin, View):
    """screen-search「一括編集」ボタン（html4差分で初めて仕様が提示された機能、
    HTML_REIMPL_CHECKLIST_ARCHIVE.md「検索結果一覧 一括編集の実装」参照）。BulkDownloadViewと同じpks検証パターンで選択された
    文書を確認し、以後のウィザード進行に必要な最小限の状態（pkの並び順と現在位置）だけを
    セッションに積んでBulkEditViewへ渡す。編集権限自体はDocumentEditView・検索詳細ポップアップの
    「変更」ボタン（static/js/common.js、!data.is_deleted && data.edit_urlのみが条件）と同じく
    ログイン済み・未削除であれば誰でも編集できる前提のため、can_downloadのような追加の権限判定は
    行わない。
    """

    def post(self, request):
        pks = request.POST.getlist("pks")
        if not pks:
            messages.error(request, "編集する文書を選択してください。")
            return redirect("documents:search")

        # pks検証・部署スコープ絞り込みの実体はcore.bulk_edit_services.resolve_ordered_pksに
        # 集約済み（contracts.views.BulkEditStartViewとの重複をコード監査で発見、2026-08-25修正）。
        ordered_pks = bulk_edit_services.resolve_ordered_pks(
            pks, model=Document, dept_ids_resolver=document_searchable_department_ids, employee=request.user
        )
        if not ordered_pks:
            messages.error(request, "編集する文書を選択してください。")
            return redirect("documents:search")

        bulk_edit_services.start_bulk_edit(request.session, BULK_EDIT_SESSION_KEY, ordered_pks)
        return redirect("documents:bulk_edit")


class BulkEditView(LoginRequiredMixin, View):
    """一括編集ウィザード本体。DocumentEditView（screen-storage2の変更モード）のテンプレート
    （edit.html）をそのまま再利用しつつ、BulkEditStartViewがセッションに積んだpk一覧を
    ページャー（＜ N/M ＞）で1件ずつ巡回する。原本html4差分のモックJSは全件をブラウザ内の
    配列に溜めて最後に一括保存する作りだったが、ModelChoiceFieldの値はセッションへの
    JSONシリアライズに向かないため、本実装では「どのボタン（＜／次へ／更新）を押しても、
    まず今表示している内容を検証・保存してから移動する」save-as-you-go方式にしている
    （詳細な設計判断はHTML_REIMPL_CHECKLIST_ARCHIVE.md参照）。単体編集用のトークン名
    （"documents_edit"）とは別の"documents_bulk_edit"を使い、別タブで単体編集中でも
    干渉しないようにする。
    """

    template_name = "documents/edit.html"
    form_id = "documents_bulk_edit"

    def _state(self, request):
        state = bulk_edit_services.get_bulk_edit_state(request.session, BULK_EDIT_SESSION_KEY)
        if not state:
            messages.error(request, "編集対象が選択されていません。検索結果一覧からやり直してください。")
            return None
        return state

    def get(self, request):
        state = self._state(request)
        if state is None:
            return redirect("documents:search")

        # セキュリティレビューで発見：部署スコープ外の文書へのセッション改ざん・URL直打ちを
        # 防ぐ（documents.services.scoped_get_object_or_404 docstring参照。2026-08-25修正）。
        self.object = scoped_get_object_or_404(
            Document.objects.filter(is_deleted=False), request.user, state["pks"][state["index"]]
        )
        form = self._build_form()
        token = issue_token(request.session, self.form_id)
        return render(request, self.template_name, self._context(request, form, token, state))

    def post(self, request):
        state = self._state(request)
        if state is None:
            return redirect("documents:search")

        # セキュリティレビューで発見：部署スコープ外の文書へのセッション改ざん・URL直打ちを
        # 防ぐ（documents.services.scoped_get_object_or_404 docstring参照。2026-08-25修正）。
        self.object = scoped_get_object_or_404(
            Document.objects.filter(is_deleted=False), request.user, state["pks"][state["index"]]
        )
        submitted_token = request.POST.get("token", "")
        if not consume_token(request.session, self.form_id, submitted_token):
            messages.error(request, "二重に送信された可能性があるため処理を中断しました。もう一度やり直してください。")
            return redirect("documents:bulk_edit")

        form = self._build_form(data=request.POST)
        if not form.is_valid():
            token = issue_token(request.session, self.form_id)
            return render(request, self.template_name, self._context(request, form, token, state))

        try:
            doc = apply_document_edit(self.object, form.cleaned_data, request.user)
        except DBError:
            # contracts.views.BulkEditView.postと同じ理由（documents.views.DocumentEditView.post
            # と同様、以前はDBErrorが未捕捉のまま生の500になっていた。2026-08-25修正）。
            logger.exception(
                "文書の一括編集処理中にDBエラーが発生しました: document_id=%s, employee_no=%s",
                self.object.pk,
                request.user.employee_no,
            )
            messages.error(request, "更新に失敗しました。もう一度お試しください。")
            token = issue_token(request.session, self.form_id)
            return render(request, self.template_name, self._context(request, form, token, state))
        audit_services.log(
            employee=request.user,
            action="保管画面２ 更新",
            event_message=f"文書「{doc.title}」を更新しました。",
            personal_info_flag=doc.privacy_flag,
        )

        total = len(state["pks"])
        index = state["index"]
        if request.POST.get("bulk_nav") == "prev" and index > 0:
            bulk_edit_services.set_bulk_edit_index(request.session, BULK_EDIT_SESSION_KEY, index - 1)
            return redirect("documents:bulk_edit")
        if index < total - 1:
            bulk_edit_services.set_bulk_edit_index(request.session, BULK_EDIT_SESSION_KEY, index + 1)
            return redirect("documents:bulk_edit")

        # 最終ステップ完了。DocumentEditView.postと同じ理由でリダイレクトせず、
        # completeを付けてedit.htmlを再描画し完了モーダルを重ねる。
        edited_docs_by_pk = {d.pk: d for d in Document.objects.filter(pk__in=state["pks"])}
        edited_docs = [edited_docs_by_pk[pk] for pk in state["pks"] if pk in edited_docs_by_pk]
        bulk_edit_services.clear_bulk_edit_state(request.session, BULK_EDIT_SESSION_KEY)
        token = issue_token(request.session, self.form_id)
        return render(
            request,
            self.template_name,
            {
                "form": form,
                "document": self.object,
                "token": token,
                "title_field": form["title_0"],
                "complete": {"created": edited_docs, "mode": "update"},
                "preview_kind": get_preview_kind(self.object.display_name),
                "can_download": can_download(request.user, kind="document"),
                **_expiry_preview_context(form),
            },
        )

    def _context(self, request, form, token, state):
        total = len(state["pks"])
        index = state["index"]
        return {
            "form": form,
            "document": self.object,
            "token": token,
            "title_field": form["title_0"],
            "preview_kind": get_preview_kind(self.object.display_name),
            "can_download": can_download(request.user, kind="document"),
            "bulk": {
                "index": index + 1,
                "total": total,
                "has_prev": index > 0,
                "has_next": index < total - 1,
            },
            **_expiry_preview_context(form),
        }

    def _build_form(self, data=None):
        return UploadStep2Form(
            data,
            employee=self.request.user,
            file_count=1,
            edit_mode=True,
            initial_titles=[self.object.title],
            initial={
                "department": self.object.department_id,
                "group": self.object.group_id,
                "category": self.object.category_id,
                "year": self.object.year,
                "retention_period": self.object.retention_period_id,
                "privacy_flag": self.object.privacy_flag,
                "memo": self.object.memo,
            },
        )


def _strip_ext(filename):
    return filename.rsplit(".", 1)[0] if "." in filename else filename


def _expiry_preview_context(form):
    """storage2.html・edit.htmlの保存満了日プレビュー用。formの`retention_period`選択肢に
    対する{pk: ISO日付文字列}を渡し、JS側はこれを引くだけで済むようにする（documents.services.
    expiry_date_previews docstring参照）。
    """
    return {"expiry_previews": expiry_date_previews(form.fields["retention_period"].queryset)}


def _pending_preview_context(request, pending):
    return upload_views.build_pending_preview_context(
        request, pending, kind="document", preview_url_name="documents:upload_step2_preview"
    )


class PendingPreviewView(LoginRequiredMixin, upload_views.BasePendingPreviewView):
    """実体はcore.upload_views.BasePendingPreviewViewに集約済み（contracts.views.
    PendingPreviewViewとの重複をコード監査で発見、2026-08-25修正）。"""

    pending_session_key = PENDING_SESSION_KEY
    kind = "document"


class SearchView(LoginRequiredMixin, View):
    """screen-search（文書モード）。一覧・検索。1ページ100件（コーディング規約のPaginator方針、Rev1.1で50→100件）。"""

    template_name = "documents/search.html"
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
        # 原本index.html:3315の操作履歴ログサンプル「契約書　検索」に対応する文書側の実装
        # （未実装改善候補の棚卸しで発見：検索操作自体が一度も監査ログに記録されていなかった）。
        # ページャー/ソートの再アクセスは新たな検索操作ではないため対象外にする
        # （core.search_services.is_search_form_submission docstring参照）。
        if form.is_valid() and search_services.is_search_form_submission(request.GET, form.fields.keys()):
            audit_services.log(
                employee=request.user,
                action="文書検索 検索",
                event_message=search_services.build_search_audit_message(form),
            )
        return render(
            request,
            self.template_name,
            {
                "form": form,
                "page_obj": page_obj,
                "can_download": can_download(request.user, kind="document"),
                "sort_key": sort_key,
                "sort_dir": sort_dir,
                "notice": notice,
            },
        )


class DownloadView(LoginRequiredMixin, record_views.BaseFileServeView):
    """詳細ポップアップ「ダウンロード」ボタン。要再確認No.20〜22（権限管理「文書-ダウンロード」フラグ）
    に対応し、`permissions.services.can_download`で一元判定する。実体はcore.record_views.
    BaseFileServeViewに集約済み（contracts.views.DownloadViewとの重複をコード監査で発見、
    2026-08-25修正）。
    """

    model = Document
    kind = "document"
    scoped_lookup = staticmethod(scoped_get_object_or_404)
    as_attachment = True
    audit_action = "文書検索 ダウンロード"
    entity_label = "文書"

    def audit_extra_kwargs(self, obj):
        return {"personal_info_flag": obj.privacy_flag}


class PreviewView(LoginRequiredMixin, record_views.BaseFileServeView):
    """screen-search「文書イメージ」欄。原本index.htmlには実データ連携が無く固定のシミュレーション
    文言のみだったが、ユーザー要望で実ファイルのプレビュー表示に対応する。DownloadViewと同じ
    `can_download`権限で保護した上でContent-Disposition: inlineで返し、ブラウザ内蔵のPDF/画像
    ビューアで一覧画面の<iframe>に埋め込み表示できるようにする（ダウンロード可否＝プレビュー可否
    として扱う。閲覧のみ許可し保存は禁止、という粒度の権限は権限管理側に無いため区別しない）。
    実体はcore.record_views.BaseFileServeViewに集約済み（contracts.views.PreviewViewとの重複を
    コード監査で発見、2026-08-25修正）。
    """

    model = Document
    kind = "document"
    scoped_lookup = staticmethod(scoped_get_object_or_404)
    as_attachment = False
    audit_action = "文書検索 プレビュー"
    entity_label = "文書"

    def audit_extra_kwargs(self, obj):
        return {"personal_info_flag": obj.privacy_flag}


class BulkDownloadView(LoginRequiredMixin, record_views.BaseBulkDownloadView):
    """screen-search「一括ダウンロード」（xlsx 検索・閲覧・変更!B264-265、要再確認No.20）。
    原本はonclick未設定のモックだったが、権限判定(`can_download`)自体は単体ダウンロードと
    同じ要再確認No.20〜22フラグで既に解決済みのため、選択された複数文書をZIPにまとめて
    ダウンロードする機能として実装する（ZIP圧縮という技術的な実現方法自体はxlsxに明記は
    無いが、「複数ファイルの一括ダウンロード」という要求から一意に導ける一般的な実装）。
    実体はcore.record_views.BaseBulkDownloadViewに集約済み（contracts.views.BulkDownloadViewとの
    重複をコード監査で発見、2026-08-25修正）。
    """

    model = Document
    kind = "document"
    dept_ids_resolver = staticmethod(document_searchable_department_ids)
    zip_builder = staticmethod(build_zip_archive)
    audit_action = "文書検索 一括ダウンロード"
    entity_label = "文書"
    search_url_name = "documents:search"
    zip_filename = "documents.zip"

    def audit_extra_kwargs(self, objects):
        # 個人情報書類が1件でも含まれていればフラグを立てる。
        return {"personal_info_flag": any(document.privacy_flag for document in objects)}


class DeleteView(LoginRequiredMixin, record_views.BaseDeleteView):
    """詳細ポップアップ「削除」ボタン。論理削除（is_deleted=True）のみを行う。

    2026-08-12にユーザー依頼で「ゴミ箱保管中（is_deleted=True）の文書は削除ボタンで完全削除できる」
    機能を追加していたが、Rev1.2改訂（xlsx 検索・閲覧・変更!B331,B337「削除されている文書は、
    ボタンを非表示とする」）でユーザー判断によりxlsx優先とし、2026-08-24に完全削除機能は廃止した
    （documents.services.can_delete docstring参照。完全削除自体は自動物理削除バッチ
    〈core.management.commands.purge_expired_deleted_records〉に一本化）。実体はcore.record_views.
    BaseDeleteViewに集約済み（contracts.views.DeleteViewとの重複をコード監査で発見、2026-08-25修正）。
    """

    model = Document
    scoped_lookup = staticmethod(scoped_get_object_or_404)
    entity_label = "文書"
    search_url_name = "documents:search"

    def audit_extra_kwargs(self, obj):
        return {"personal_info_flag": obj.privacy_flag}
