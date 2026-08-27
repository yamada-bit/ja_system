import logging
import re

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views import View

from core import upload_services
from core.file_type_services import get_preview_kind
from core.upload_services import ChunkUploadError, PendingFileStorageError, combine_upload_chunks, save_upload_chunk
from permissions.services import can_download

logger = logging.getLogger(__name__)

# upload_idはブラウザ側（static/js/chunk_upload.js generateUploadId）で生成され、
# save_upload_chunk/combine_upload_chunksでファイルパスの一部としてそのまま使われる。
# crypto.randomUUID()のフォールバックも含めUUID風の文字列のみを想定しているため、
# パス区切り文字混入によるディレクトリトラバーサルを避けるためここで形式を制限する。
UPLOAD_ID_PATTERN = re.compile(r"^[0-9a-zA-Z-]{1,64}$")


class BaseChunkUploadAPIView(LoginRequiredMixin, View):
    """screen-storage1のチャンク分割アップロードAPI。選択されたファイルのサイズが
    settings.MAX_UPLOAD_SIZE_BYTESを超える場合にstatic/js/chunk_upload.jsが自動的に使用する
    （ja_pj_old core/upload_views.py BaseChunkUploadAPIViewの移植・簡略化）。

    結合が完了したファイルはcore.upload_services.combine_upload_chunksの中で
    `pending_session_key`のセッション保留ファイル一覧へ直接追記される。documents/contractsの
    UploadStep1View.get/postが読み書きしているのと同じキー・同じ形式（{temp_name, original_name}）
    のため、通常アップロード分（request.FILES）と合流させるための中間的な「保留プール」は
    不要（core.upload_services.pyのモジュールdocstring参照）。

    documents/contractsは`pending_session_key`をクラス変数で指定して継承する。
    """

    pending_session_key = None

    def post(self, request, *args, **kwargs):
        try:
            upload_id = request.POST["upload_id"]
            file_name = request.POST["file_name"]
            chunk_index = int(request.POST["chunk_index"])
            total_chunks = int(request.POST["total_chunks"])
            chunk_file = request.FILES["file"]
        except (KeyError, ValueError):
            logger.warning(
                "チャンクアップロードAPIへの不正なリクエスト: employee_no=%s", request.user.employee_no
            )
            return JsonResponse({"status": "error", "message": "不正なリクエストです。"}, status=400)

        if not UPLOAD_ID_PATTERN.match(upload_id):
            logger.warning(
                "チャンクアップロードAPIに不正なupload_idが送られました: employee_no=%s upload_id=%r",
                request.user.employee_no,
                upload_id,
            )
            return JsonResponse({"status": "error", "message": "不正なリクエストです。"}, status=400)

        try:
            save_upload_chunk(upload_id, chunk_index, chunk_file)
        except PendingFileStorageError as e:
            return JsonResponse({"status": "error", "message": str(e)})

        if chunk_index + 1 != total_chunks:
            return JsonResponse({"status": "chunk_received"})

        try:
            combine_upload_chunks(request.session, self.pending_session_key, upload_id, total_chunks, file_name)
        except ChunkUploadError as e:
            # チャンク欠落（クライアント側の実装不具合・ネットワーク不調の兆候）・サイズ上限超過
            # （利用者が意図的に上限を試している可能性）はいずれも「想定外の分岐」に該当するため、
            # CLAUDE.mdの規約通りlogger.warningで記録する。
            logger.warning(
                "チャンクアップロードの結合に失敗しました: upload_id=%s employee_no=%s reason=%s",
                upload_id,
                request.user.employee_no,
                e,
            )
            return JsonResponse({"status": "error", "message": str(e)})
        except PendingFileStorageError as e:
            return JsonResponse({"status": "error", "message": str(e)})

        return JsonResponse({"status": "completed", "message": f"「{file_name}」をアップロードしました。"})


class BaseUploadStep1View(View):
    """screen-storage1（文書/契約書選択）。documents.views.UploadStep1View/contracts.views.
    UploadStep1Viewがtemplate_name・pending_session_key・遷移先URL名以外完全に同一実装のまま
    重複していたため集約した（品質レビューで発見、2026-08-25修正）。documents側は
    LoginRequiredMixin、contracts側はRequiresContractEditMixinと、要求する認可が異なるため、
    BasePendingPreviewViewと同じく認証・認可ミックスインはベースクラスに含めず継承側で
    組み合わせる。`template_name`/`pending_session_key`/`next_url_name`をクラス変数で指定して
    継承する。
    """

    template_name = None
    pending_session_key = None
    next_url_name = None

    def get(self, request):
        # 表示のたび保留プールをクリアする（チャンク分割だけしてフォーム未送信のまま離脱した
        # 残骸を次回に持ち越さないため。core.upload_services docstring参照）。
        upload_services.clear_pending_files(request.session, self.pending_session_key)
        return render(request, self.template_name, self._context())

    def post(self, request):
        files = request.FILES.getlist("files")
        # settings.MAX_UPLOAD_SIZE_BYTESを超える大容量ファイルはstorage1.htmlのJSが送信前に
        # upload/chunk/へチャンク分割送信し、combine_upload_chunksが完了ごとにこのセッションキー
        # へ直接追記する（BaseChunkUploadAPIView）。そのため、通常のfile input経由のファイルが
        # 0件でも、既にチャンク経由で登録済みのファイルがあれば処理を続行してよい。
        existing_pending = upload_services.get_pending_files(request.session, self.pending_session_key)
        if not files and not existing_pending:
            messages.error(request, "ファイルが選択されていません。")
            return render(request, self.template_name, self._context())
        if files:
            try:
                upload_services.save_pending_files(request.session, self.pending_session_key, files)
            except PendingFileStorageError:
                # MEDIA_ROOT/tmp_uploads への一時保存に失敗（ディスク容量不足・権限エラー等）。
                # save_pending_filesはOSErrorをPendingFileStorageErrorにラップして送出するため、
                # ここでは後者を捕捉する必要がある。
                logger.exception(
                    "アップロードファイルの一時保存に失敗しました: employee_no=%s", request.user.employee_no
                )
                messages.error(request, "ファイルの保存に失敗しました。もう一度お試しください。")
                return render(request, self.template_name, self._context())
        return redirect(self.next_url_name)

    def _context(self):
        # storage1.htmlのJSがMAX_UPLOAD_SIZE_BYTES基準でチャンク分割の要否を判定するため渡す。
        return {"max_upload_size_bytes": settings.MAX_UPLOAD_SIZE_BYTES}


class BaseUploadStep2RemoveView(View):
    """保管画面２（登録）の「削除」ボタン共通実装。ページャーで表示中の1ファイルだけを
    セッションの保留一覧から外し（実体も削除）、他のファイルはそのまま登録フローを続行させる
    （2026-08-27ユーザー確定。xlsx 保管!B197-198「誤ってアップロードした文書、不要な文書を
    削除する。(本登録から除外する)」に対応）。まだDBレコードは生成されていないため論理削除
    （EditDeleteView）とは別物で、監査ログの対象にもしない（logger.infoのみ）。

    documents側はLoginRequiredMixin、contracts側はRequiresContractEditMixinと要求する認可が
    異なるため、認証・認可ミックスインはベースに含めず継承側で組み合わせる
    （BaseUploadStep1Viewと同じ方針）。`pending_session_key`/`step1_url_name`/`step2_url_name`/
    `entity_label`をクラス変数で指定して継承する。
    """

    pending_session_key = None
    step1_url_name = None
    step2_url_name = None
    entity_label = None

    def post(self, request):
        try:
            index = int(request.POST.get("index", ""))
        except (TypeError, ValueError):
            # indexはstorage2.htmlのJS（activeDocIndex）が埋めるhidden値で通常は正しい整数。
            # 壊れたリクエスト・改ざんの兆候としてログに残し、そのまま保管画面２へ戻す。
            logger.warning(
                "アップロード取り消しに不正なindexが送られました: employee_no=%s value=%r",
                request.user.employee_no,
                request.POST.get("index"),
            )
            return redirect(self.step2_url_name)

        removed = upload_services.remove_pending_file(
            request.session, self.pending_session_key, index
        )
        if removed is None:
            # 範囲外（多重送信等で既に件数が変わっている）。エラー表示はせず現状の一覧を再表示する。
            return redirect(self.step2_url_name)

        logger.info(
            "保管画面２ アップロード取り消し: employee_no=%s file=%s",
            request.user.employee_no,
            removed["original_name"],
        )

        remaining = upload_services.get_pending_files(request.session, self.pending_session_key)
        if not remaining:
            messages.info(
                request,
                f"アップロードを取り消しました。{self.entity_label}を選択し直してください。",
            )
            return redirect(self.step1_url_name)
        messages.info(request, f"「{removed['original_name']}」のアップロードを取り消しました。")
        return redirect(self.step2_url_name)


def file_rows(form, pending):
    """テンプレート側で`{{ item.original_name }}`と対応する`title_N`入力欄を並べて表示するための
    (pendingの要素, BoundField)組を作る。title_Nはファイル数に応じて動的に追加されるフィールドの
    ため、テンプレート内で名前を組み立てて引くことができず、ここでビューが束ねてから渡す。
    documents.views._file_rows/contracts.views._file_rowsが完全に同一実装のまま重複していたため
    集約した（品質レビューで発見、2026-08-25修正）。
    """
    return [(item, form[f"title_{i}"]) for i, item in enumerate(pending)]


def build_pending_preview_context(request, pending, *, kind, preview_url_name):
    """保管画面２のPDFモックプレビューを、対象が画像／PDFの場合のみBasePendingPreviewView経由の
    実データ<img>/<iframe>表示に切り替えるための追加コンテキスト。ダウンロード権限が無い
    ユーザーにはpreview_urlsを空にし、テンプレート側は従来のモック表示のまま変わらないようにする
    （search.htmlのcan_download gatingと同じ方針）。preview_kindsの各要素は"image"/"pdf"/""
    （該当無し、JS側の文字列比較のためNoneではなく空文字にする）。documents.views.
    _pending_preview_context/contracts.views._pending_preview_contextが完全に同一実装のまま
    重複していたため集約した（品質レビューで発見、2026-08-25修正）。

    `kind`はpermissions.services.can_downloadの"document"/"contract"、`preview_url_name`は
    reverse()に渡すURL名前空間（"documents:upload_step2_preview"等）。
    """
    preview_kinds = [get_preview_kind(item["original_name"]) or "" for item in pending]
    if can_download(request.user, kind=kind):
        preview_urls = [reverse(preview_url_name, args=[i]) for i in range(len(pending))]
    else:
        preview_urls = []
    return {"preview_kinds": preview_kinds, "preview_urls": preview_urls}


class BasePendingPreviewView(View):
    """保管画面２（登録前）のPDFモックプレビューを、選択中の保留ファイルの実データで表示する。
    対象の文書/契約書はまだDBに保存されておりpkが存在しないため、pkベースのPreviewViewは使えず、
    セッションの保留ファイル一覧をindexで参照する。他人がtemp_name（tmp_uploads/配下の実パスの
    一部）を直接推測しても、保留ファイル一覧自体がリクエスト元のセッションに紐付くため参照
    できない。documents.views.PendingPreviewView/contracts.views.PendingPreviewViewが
    pending_session_key・kind・エラーメッセージ文言以外完全に同一実装のまま重複していたため
    集約した（品質レビューで発見、2026-08-25修正）。

    documents側はLoginRequiredMixin、contracts側はRequiresContractEditMixin（保管フロー全体で
    共通のcontract_edit権限チェック）と、要求する認可が異なるため、認証・認可ミックスインは
    ベースクラスに含めず継承側で組み合わせる（`class PendingPreviewView(RequiresContractEditMixin,
    BasePendingPreviewView)`のように）。`pending_session_key`/`kind`をクラス変数で指定して
    継承する。
    """

    pending_session_key = None
    kind = None

    def get(self, request, index):
        if not can_download(request.user, kind=self.kind):
            logger.warning(
                "プレビュー権限の無いユーザーによる試行: employee_no=%s", request.user.employee_no
            )
            raise PermissionDenied("プレビュー権限がありません。")
        pending = upload_services.get_pending_files(request.session, self.pending_session_key)
        if index >= len(pending):
            raise Http404("プレビュー対象のファイルが見つかりません。")
        item = pending[index]
        try:
            temp_file = upload_services.open_pending_file(item["temp_name"])
        except PendingFileStorageError:
            logger.exception(
                "保留ファイルのプレビュー取得に失敗しました: employee_no=%s index=%s",
                request.user.employee_no,
                index,
            )
            raise Http404("プレビュー対象のファイルが見つかりません。")
        return FileResponse(temp_file, as_attachment=False, filename=item["original_name"])
