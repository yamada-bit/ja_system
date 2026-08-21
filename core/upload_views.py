import logging
import re

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.views import View

from core.upload_services import ChunkUploadError, PendingFileStorageError, combine_upload_chunks, save_upload_chunk

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
