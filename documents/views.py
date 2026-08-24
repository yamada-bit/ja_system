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
from core import bulk_edit_services, upload_services
from core.double_submit import consume_token, issue_token
from core.file_type_services import get_preview_kind
from core.text_extraction_services import try_immediate_text_layer_extraction
from documents.forms import SearchForm, UploadStep2Form
from documents.models import Document
from documents.search_services import build_queryset
from documents.services import apply_document_edit, calculate_expiry_date, can_delete, expiry_date_previews
from permissions.services import can_download, can_select_department

logger = logging.getLogger(__name__)

PENDING_SESSION_KEY = "documents_pending_upload"
BULK_EDIT_SESSION_KEY = "documents_bulk_edit"


class UploadStep1View(LoginRequiredMixin, View):
    """screen-storage1（文書選択）。"""

    template_name = "documents/storage1.html"

    def get(self, request):
        # 表示のたび保留プールをクリアする（チャンク分割だけしてフォーム未送信のまま離脱した
        # 残骸を次回に持ち越さないため。core.upload_services docstring参照）。
        upload_services.clear_pending_files(request.session, PENDING_SESSION_KEY)
        return render(request, self.template_name, self._context())

    def post(self, request):
        files = request.FILES.getlist("files")
        # settings.MAX_UPLOAD_SIZE_BYTESを超える大容量ファイルはstorage1.htmlのJSが送信前に
        # upload/chunk/へチャンク分割送信し、combine_upload_chunksが完了ごとにこのセッションキー
        # へ直接追記する（core.upload_views.BaseChunkUploadAPIView）。そのため、通常のfile input
        # 経由のファイルが0件でも、既にチャンク経由で登録済みのファイルがあれば処理を続行してよい。
        existing_pending = upload_services.get_pending_files(request.session, PENDING_SESSION_KEY)
        if not files and not existing_pending:
            messages.error(request, "ファイルが選択されていません。")
            return render(request, self.template_name, self._context())
        if files:
            try:
                upload_services.save_pending_files(request.session, PENDING_SESSION_KEY, files)
            except upload_services.PendingFileStorageError:
                # MEDIA_ROOT/tmp_uploads への一時保存に失敗（ディスク容量不足・権限エラー等）。
                # save_pending_filesはOSErrorをPendingFileStorageErrorにラップして送出するため、
                # ここでは後者を捕捉する必要がある（原本フィデリティ監査で発見：以前は
                # 素のOSErrorを捕捉していたため実際には一度もこのexcept節に到達しなかった）。
                logger.exception(
                    "アップロードファイルの一時保存に失敗しました: employee_no=%s", request.user.employee_no
                )
                messages.error(request, "ファイルの保存に失敗しました。もう一度お試しください。")
                return render(request, self.template_name, self._context())
        return redirect("documents:upload_step2")

    def _context(self):
        # storage1.htmlのJSがMAX_UPLOAD_SIZE_BYTES基準でチャンク分割の要否を判定するため渡す。
        return {"max_upload_size_bytes": settings.MAX_UPLOAD_SIZE_BYTES}


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
                "file_rows": _file_rows(form, pending),
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
                    "file_rows": _file_rows(form, pending),
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
                    audit_services.log(
                        employee=request.user,
                        action="保管画面２ 登録",
                        event_message=f"文書「{document.title}」を保管しました。",
                        personal_info_flag=document.privacy_flag,
                    )
                    created.append(document)
        except OSError:
            # open_pending_file()／file.save()でのファイルI/O失敗（一時ファイル欠損・ディスク
            # 容量不足等）。transaction.atomic()によりここまでの登録はロールバックされるため、
            # DBには一部だけ登録された不整合な状態は残らない。tmp_uploads側の一時ファイルと
            # セッションのpendingはあえてクリアせず、利用者が保管画面２からやり直せるようにする。
            logger.exception(
                "文書の保管処理中にファイルI/Oエラーが発生しました: employee_no=%s", request.user.employee_no
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
                "file_rows": _file_rows(form, pending),
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
        return get_object_or_404(Document, pk=self.kwargs["pk"], is_deleted=False)

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

        doc = apply_document_edit(self.object, form.cleaned_data, request.user)
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
    """screen-search「一括編集」ボタン（html4差分で初めて仕様が提示された機能、HTML_REIMPL_CHECKLIST.md
    「検索結果一覧 一括編集の実装」参照）。BulkDownloadViewと同じpks検証パターンで選択された
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

        # BulkDownloadViewと同じ理由（改ざんや誤ったリンク等で数値以外が混入し得るため、
        # 無効な値は除外しつつ不正アクセス試行の兆候として警告ログに残す）。
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

        # 検索結果に表示されていた順序（=POSTされたpksの順序）をそのままウィザードの
        # 巡回順にする。存在しない・削除済みのpkはここで静かに除外する（BulkDownloadViewが
        # ZIPから静かに除外するのと同じ方針）。
        existing_pks = set(
            Document.objects.filter(pk__in=valid_pks, is_deleted=False).values_list("pk", flat=True)
        )
        ordered_pks = [pk for pk in valid_pks if pk in existing_pks]
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
    （詳細な設計判断はHTML_REIMPL_CHECKLIST.md参照）。単体編集用のトークン名
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

        self.object = get_object_or_404(Document, pk=state["pks"][state["index"]], is_deleted=False)
        form = self._build_form()
        token = issue_token(request.session, self.form_id)
        return render(request, self.template_name, self._context(request, form, token, state))

    def post(self, request):
        state = self._state(request)
        if state is None:
            return redirect("documents:search")

        self.object = get_object_or_404(Document, pk=state["pks"][state["index"]], is_deleted=False)
        submitted_token = request.POST.get("token", "")
        if not consume_token(request.session, self.form_id, submitted_token):
            messages.error(request, "二重に送信された可能性があるため処理を中断しました。もう一度やり直してください。")
            return redirect("documents:bulk_edit")

        form = self._build_form(data=request.POST)
        if not form.is_valid():
            token = issue_token(request.session, self.form_id)
            return render(request, self.template_name, self._context(request, form, token, state))

        doc = apply_document_edit(self.object, form.cleaned_data, request.user)
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


def _file_rows(form, pending):
    """テンプレート側で `{{ item.original_name }}` と対応する `title_N` 入力欄を並べて表示するための
    (pendingの要素, BoundField)組を作る。title_Nはファイル数に応じて動的に追加されるフィールドのため
    テンプレート内で名前を組み立てて引くことができず、ここでビューが束ねてから渡す。
    """
    return [(item, form[f"title_{i}"]) for i, item in enumerate(pending)]


def _expiry_preview_context(form):
    """storage2.html・edit.htmlの保存満了日プレビュー用。formの`retention_period`選択肢に
    対する{pk: ISO日付文字列}を渡し、JS側はこれを引くだけで済むようにする（documents.services.
    expiry_date_previews docstring参照）。
    """
    return {"expiry_previews": expiry_date_previews(form.fields["retention_period"].queryset)}


def _pending_preview_context(request, pending):
    """保管画面２のPDFモックプレビュー（storage2.html）を、対象が画像／PDFの場合のみ
    PendingPreviewView経由の実データ<img>/<iframe>表示に切り替えるための追加コンテキスト。
    ダウンロード権限が無いユーザーにはpreview_urlsを空にし、テンプレート側は従来の
    モック表示のまま変わらないようにする（search.htmlのcan_download gatingと同じ方針）。
    preview_kindsの各要素は"image"/"pdf"/""（該当無し、JS側の文字列比較のためNoneではなく
    空文字にする）。
    """
    preview_kinds = [get_preview_kind(item["original_name"]) or "" for item in pending]
    if can_download(request.user, kind="document"):
        preview_urls = [
            reverse("documents:upload_step2_preview", args=[i]) for i in range(len(pending))
        ]
    else:
        preview_urls = []
    return {"preview_kinds": preview_kinds, "preview_urls": preview_urls}


class PendingPreviewView(LoginRequiredMixin, View):
    """保管画面２（登録前）のPDFモックプレビューを、選択中の保留ファイルの実データで表示する。
    対象の文書はまだDBに保存されておりpkが存在しないため、PreviewView（pkベース）は使えず、
    セッションの保留ファイル一覧をindexで参照する。他人がtemp_name（tmp_uploads/配下の実パスの
    一部）を直接推測しても、保留ファイル一覧自体がリクエスト元のセッションに紐付くため
    参照できない。
    """

    def get(self, request, index):
        if not can_download(request.user, kind="document"):
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


class DownloadView(LoginRequiredMixin, View):
    """詳細ポップアップ「ダウンロード」ボタン。要再確認No.20〜22（権限管理「文書-ダウンロード」フラグ）
    に対応し、`permissions.services.can_download`で一元判定する。

    xlsx 検索・閲覧・変更!B331(Rev1.2)「削除されている(削除フラグがTrue)文書は、ボタンを非表示と
    する」に対応し、DocumentEditView.get_object()と同じくis_deleted=Falseでしか対象を取得できない
    ようにする（監査で発見：documents.api.DetailAPIViewのdownload_urlはcan_download権限のみを
    見ておりis_deleted判定が漏れていたため、削除済み文書でもダウンロードボタンが表示され続けて
    いた）。
    """

    def get(self, request, pk):
        document = get_object_or_404(Document, pk=pk, is_deleted=False)
        if not can_download(request.user, kind="document"):
            logger.warning(
                "ダウンロード権限の無いユーザーによる試行: employee_no=%s document_id=%s",
                request.user.employee_no,
                pk,
            )
            raise PermissionDenied("ダウンロード権限がありません。")
        try:
            response = FileResponse(
                document.file.open("rb"), as_attachment=True, filename=document.display_name
            )
        except OSError:
            # FileNotFoundError（実体欠損）だけでなくPermissionError（ロック・権限エラー等）も
            # OSErrorのサブクラスのため、ストレージI/O境界で起こりうるOSError全般をここで
            # 利用者向けのHttp404に変換する（監査で指摘：以前はFileNotFoundErrorのみ捕捉していた）。
            logger.exception("ファイル実体の取得に失敗しました: document_id=%s", pk)
            raise Http404("ファイルが見つかりません。")
        # 原本にはない追加対応（2026-08-12）。登録・更新・削除は元々audit_services.log()で
        # 記録されるのに、文書管理システムの核心操作である「誰がいつ閲覧・持ち出したか」の
        # ダウンロードだけ監査ログに一切残っていなかった（未実装改善候補の棚卸しで発見）。
        # ファイルI/O成功後（ユーザーが実際にダウンロードを受け取れる状態になった後）に記録する。
        audit_services.log(
            employee=request.user,
            action="文書検索 ダウンロード",
            event_message=f"文書「{document.title}」をダウンロードしました。",
            personal_info_flag=document.privacy_flag,
        )
        return response


class PreviewView(LoginRequiredMixin, View):
    """screen-search「文書イメージ」欄。原本index.htmlには実データ連携が無く固定のシミュレーション
    文言のみだったが、ユーザー要望で実ファイルのプレビュー表示に対応する。DownloadViewと同じ
    `can_download`権限で保護した上で`as_attachment=False`（Content-Disposition: inline）で返し、
    ブラウザ内蔵のPDF/画像ビューアで一覧画面の<iframe>に埋め込み表示できるようにする
    （ダウンロード可否＝プレビュー可否として扱う。閲覧のみ許可し保存は禁止、という粒度の権限は
    権限管理側に無いため区別しない）。
    """

    def get(self, request, pk):
        document = get_object_or_404(Document, pk=pk)
        if not can_download(request.user, kind="document"):
            logger.warning(
                "プレビュー権限の無いユーザーによる試行: employee_no=%s document_id=%s",
                request.user.employee_no,
                pk,
            )
            raise PermissionDenied("プレビュー権限がありません。")
        try:
            response = FileResponse(
                document.file.open("rb"), as_attachment=False, filename=document.display_name
            )
        except OSError:
            logger.exception("ファイル実体の取得に失敗しました: document_id=%s", pk)
            raise Http404("ファイルが見つかりません。")
        # DownloadViewと同様の追加対応（2026-08-12）。プレビュー表示もダウンロードと同じく
        # ファイル実体の中身に利用者がアクセスできた操作のため、同じ粒度で監査ログに残す。
        audit_services.log(
            employee=request.user,
            action="文書検索 プレビュー",
            event_message=f"文書「{document.title}」をプレビュー表示しました。",
            personal_info_flag=document.privacy_flag,
        )
        return response


class BulkDownloadView(LoginRequiredMixin, View):
    """screen-search「一括ダウンロード」（xlsx 検索・閲覧・変更!B264-265、要再確認No.20）。
    原本はonclick未設定のモックだったが、権限判定(`can_download`)自体は単体ダウンロードと
    同じ要再確認No.20〜22フラグで既に解決済みのため、選択された複数文書をZIPにまとめて
    ダウンロードする機能として実装する（ZIP圧縮という技術的な実現方法自体はxlsxに明記は
    無いが、「複数ファイルの一括ダウンロード」という要求から一意に導ける一般的な実装）。
    """

    def post(self, request):
        pks = request.POST.getlist("pks")
        if not pks:
            messages.error(request, "ダウンロードする文書を選択してください。")
            return redirect("documents:search")
        if not can_download(request.user, kind="document"):
            logger.warning(
                "ダウンロード権限の無いユーザーによる一括ダウンロード試行: employee_no=%s",
                request.user.employee_no,
            )
            raise PermissionDenied("ダウンロード権限がありません。")

        # pksはURLパスコンバータを経由しない生のPOST値のため、改ざんや誤ったリンク等で
        # 数値以外が混入し得る（documents.search_services.build_queryset参照）。無効な値は
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

        documents = Document.objects.filter(pk__in=valid_pks, is_deleted=False)
        total_count = documents.count()
        missing_count = 0
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for document in documents:
                try:
                    with document.file.open("rb") as fh:
                        zf.writestr(document.file.name.rsplit("/", 1)[-1], fh.read())
                except FileNotFoundError:
                    # 1件のファイル実体欠損でZIP全体のダウンロードを失敗させると、欠損と無関係な
                    # 他の正常なファイルまで利用者が受け取れなくなってしまう（「本質的でない処理の
                    # 失敗で本処理まで巻き込まない」という設計判断）。欠損はログに残した上でスキップし、
                    # 件数の不一致は下のmessages.warningで利用者にも案内する（監査で指摘：以前は
                    # ログにしか残らず、利用者はZIPの中身が欠けていることに気づけなかった）。
                    logger.exception("一括ダウンロード中にファイル実体が見つかりません: document_id=%s", document.pk)
                    missing_count += 1

        logger.info(
            "一括ダウンロードを実行しました: employee_no=%s 件数=%s", request.user.employee_no, total_count
        )
        # DownloadView/PreviewViewと同様の追加対応（2026-08-12）。個々のファイル単位ではなく
        # 一括ダウンロード1回の操作として1件だけ記録する（ZIPに含まれる文書数だけログが増殖する
        # と操作履歴ログ本来の「画面操作の履歴」という粒度から外れるため）。個人情報書類が
        # 1件でも含まれていればフラグを立てる。
        audit_services.log(
            employee=request.user,
            action="文書検索 一括ダウンロード",
            event_message=f"文書{total_count}件を一括ダウンロードしました。",
            personal_info_flag=any(document.privacy_flag for document in documents),
        )
        if missing_count:
            messages.warning(
                request,
                f"選択した{total_count}件中{missing_count}件のファイルが見つからなかったため、"
                "ダウンロードされたZIPに含まれていません。",
            )
        response = HttpResponse(buffer.getvalue(), content_type="application/zip")
        response["Content-Disposition"] = 'attachment; filename="documents.zip"'
        return response


class DeleteView(LoginRequiredMixin, View):
    """詳細ポップアップ「削除」ボタン。論理削除（is_deleted=True）のみを行う。

    2026-08-12にユーザー依頼で「ゴミ箱保管中（is_deleted=True）の文書は削除ボタンで完全削除できる」
    機能を追加していたが、Rev1.2改訂（xlsx 検索・閲覧・変更!B331,B337「削除されている文書は、
    ボタンを非表示とする」）でユーザー判断によりxlsx優先とし、2026-08-24に完全削除機能は廃止した
    （documents.services.can_delete docstring参照。完全削除自体は自動物理削除バッチ
    〈core.management.commands.purge_expired_deleted_records〉に一本化）。

    原本index.html:1125-1131のtriggerDeleteFromDetail()はfetch()の完了を待って
    ポップアップを閉じる・完了アラート・一覧再描画を行う設計だが、本ビューは元々常に
    redirect()（302→200 HTML）を返しており、common.js側は`X-Requested-With`ヘッダーを
    付けてAJAX呼び出ししているにもかかわらずJSONとしてパースしようとして例外になり、
    削除自体は成功してもUI側のフィードバックが一切動作しないバグがあった（原本フィデリティ
    監査で発見）。AJAXリクエストを検知した場合はJsonResponseを返すことで解消する。
    """

    def post(self, request, pk):
        is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

        try:
            document = get_object_or_404(Document, pk=pk)
        except Http404:
            # common.js側はfetch().then(r=>r.json())で応答をJSONとしてparseするため、
            # AJAX呼び出し時にDjango標準の404 HTMLページを返すとクラスdocstring記載のバグが
            # 別経路（対象未存在）で再発する。AJAX判定時はJSONで404を返す。
            if is_ajax:
                return JsonResponse({"success": False, "message": "対象の文書が見つかりません。"}, status=404)
            raise

        if not can_delete(document):
            # xlsx 検索・閲覧・変更!B331,B337,B339-340「削除済みの文書、および初回登録から1週間
            # 以上経過しているものは削除不可。ボタンを非表示にする」。UI側
            # （common.jsのrenderDetailPopup()）はdelete_urlがNoneの間ボタン自体を隠すが、
            # API直叩き等に備えサーバー側でも拒否する。
            logger.warning(
                "削除できない文書への削除操作を拒否しました: employee_no=%s document_id=%s is_deleted=%s",
                request.user.employee_no,
                pk,
                document.is_deleted,
            )
            message = "この文書は既に削除されています。" if document.is_deleted else "保存から1週間以上経過した文書は削除できません。"
            if is_ajax:
                return JsonResponse({"success": False, "message": message}, status=403)
            raise PermissionDenied(message)

        try:
            document.is_deleted = True
            document.deleted_at = timezone.now()
            document.save(update_fields=["is_deleted", "deleted_at"])
        except DBError:
            # DB接続断・制約違反等で削除が失敗した場合も、上記と同じ理由でAJAX時はJSONを返す
            # 必要がある（このexcept節が無いと非AJAX時と同じ生の500応答になりfetch側が壊れる）。
            logger.exception("文書の削除処理に失敗しました: document_id=%s", pk)
            if is_ajax:
                return JsonResponse(
                    {"success": False, "message": "削除に失敗しました。もう一度お試しください。"}, status=500
                )
            messages.error(request, "削除に失敗しました。もう一度お試しください。")
            return redirect("documents:search")

        audit_services.log(
            employee=request.user,
            action="検索・閲覧画面 削除",
            event_message=f"文書「{document.title}」を削除しました。",
            personal_info_flag=document.privacy_flag,
        )
        success_message = "文書を削除しました。"

        if is_ajax:
            return JsonResponse({"success": True, "message": success_message})
        messages.success(request, success_message)
        return redirect("documents:search")
