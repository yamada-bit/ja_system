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
from core.file_serving import apply_file_response_security_headers, resolve_as_attachment
from core.file_type_services import get_preview_kind
from core.upload_services import ChunkUploadError, PendingFileStorageError, combine_upload_chunks, save_upload_chunk
from core.upload_validation import blocked_upload_message
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

        # セキュリティレビュー H-3: 能動的コンテンツ（HTML/SVG/スクリプト）は保管対象外。
        # 通常アップロード（BaseUploadStep1View.post）と同じ拒否判定を分割アップロードにも適用する。
        blocked = blocked_upload_message([file_name])
        if blocked is not None:
            logger.warning(
                "チャンクアップロードで拒否対象の形式が送られました: employee_no=%s file=%r",
                request.user.employee_no,
                file_name,
            )
            return JsonResponse({"status": "error", "message": blocked}, status=400)

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
        # セキュリティレビュー H-3: HTML/SVG/スクリプト等の能動的コンテンツはアップロード時点で拒否する
        # （配信側の core.file_serving と二重の防御。core.upload_validation のモジュール docstring 参照）。
        blocked = blocked_upload_message([f.name for f in files])
        if blocked is not None:
            logger.warning(
                "保管画面１で拒否対象の形式がアップロードされました: employee_no=%s", request.user.employee_no
            )
            messages.error(request, blocked)
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
        # storage1.htmlのJSに渡す:
        #  - max_upload_size_bytes: このサイズを超えるファイル（または合計で超える組み合わせ）を
        #    チャンク分割アップロードへ振り分けるしきい値。
        #  - chunk_upload_chunk_size_bytes: 1チャンクあたりのバイト数（static/js/chunk_upload.js
        #    へ引数で渡す）。以前はJSにハードコードしていた値をsettingsへ集約したもの
        #    （推奨サイズ等の詳細は config/settings/base.py の CHUNK_UPLOAD_CHUNK_SIZE_BYTES 参照）。
        return {
            "max_upload_size_bytes": settings.MAX_UPLOAD_SIZE_BYTES,
            "chunk_upload_chunk_size_bytes": settings.CHUNK_UPLOAD_CHUNK_SIZE_BYTES,
        }


def file_rows(form, pending):
    """テンプレート側で`{{ item.original_name }}`と対応する`title_N`入力欄を並べて表示するための
    (pendingの要素, BoundField)組を作る。title_Nはファイル数に応じて動的に追加されるフィールドの
    ため、テンプレート内で名前を組み立てて引くことができず、ここでビューが束ねてから渡す。
    documents.views._file_rows/contracts.views._file_rowsが完全に同一実装のまま重複していたため
    集約した（品質レビューで発見、2026-08-25修正）。
    """
    return [(item, form[f"title_{i}"]) for i, item in enumerate(pending)]


def remap_step2_initial_after_remove(post_data, *, removed_index, new_count, per_file_fields):
    """保管画面２で「削除」（表示中ファイルのアップロード取り消し）を押したとき、残った
    ファイルに入力済みだった値を詰め直して `UploadStep2Form(initial=...)` に渡せる辞書にする
    （2026-08-31ユーザー要望：削除しても他ファイルの入力を保持する）。

    削除位置より後ろのファイルの値を1つ前の添字へずらす。空文字・未送信キーは入れず、
    フォーム側の既定値・プレースホルダ（部署＝自部署、年＝当年、タイトル＝ファイル名等）に任せる。
    単一値のフォーム欄のみ扱う。契約書の関連書類（`related_contract_ids_N`、複数値）は
    `contracts.views._remap_related_ids_after_remove` が別途詰め直す。
    """
    initial = {}
    src = 0
    for dst in range(new_count):
        if src == removed_index:
            src += 1
        for name in list(per_file_fields) + ["title"]:
            key_src = f"title_{src}" if name == "title" else f"{name}_{src}"
            key_dst = f"title_{dst}" if name == "title" else f"{name}_{dst}"
            value = post_data.get(key_src)
            if value not in (None, ""):
                initial[key_dst] = value
        src += 1
    return initial


def file_field_sets(form, pending, field_names):
    """保管画面２（新規保管）でメタデータをファイルごとに個別入力するための、ファイル単位の
    フィールド束をテンプレートへ渡す。`form.per_file_mode`（documents/contracts.forms.
    UploadStep2Form、2026-08-31ユーザー確定）なら`{name}_{i}`を、そうでなければ無添字を引く。

    各要素は `{"item": pendingの要素, "index": i, "fields": {name: BoundField, ..., "title": BoundField}}`。
    テンプレートは `{{ fs.fields.department }}` のようにドット参照する。
    """
    per_file = getattr(form, "per_file_mode", False)
    sets = []
    for i, item in enumerate(pending):
        suffix = f"_{i}" if per_file else ""
        fields = {name: form[f"{name}{suffix}"] for name in field_names}
        fields["title"] = form[f"title_{i}"]
        sets.append({"item": item, "index": i, "fields": fields})
    return sets


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
        # セキュリティレビュー H-3: PreviewView と同じく、PDF・ラスター画像以外はインライン
        # 配信させず、どの形式でも nosniff と実行禁止 CSP を付与する（core.file_serving 参照）。
        as_attachment = resolve_as_attachment(wants_inline=True, filename=item["original_name"])
        response = FileResponse(
            temp_file, as_attachment=as_attachment, filename=item["original_name"]
        )
        return apply_file_response_security_headers(response)
