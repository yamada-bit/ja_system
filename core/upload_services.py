import logging
import shutil
import uuid
from pathlib import Path

from django.conf import settings
from django.core.files import File

logger = logging.getLogger(__name__)

TMP_UPLOAD_SUBDIR = "tmp_uploads"
CHUNK_UPLOAD_SUBDIR = "chunks"
CHUNK_NAME_FORMAT = "chunk_{:04d}"


class PendingFileStorageError(Exception):
    """一時アップロード領域（`MEDIA_ROOT/tmp_uploads/`）へのファイルI/Oが失敗したことを表す例外。

    ディスクフル・権限エラー・パス長超過・一時ファイル消失等の`OSError`系はここで捕捉し、
    `logger.exception`で原因を記録した上でこの専用例外にラップして送出する。呼び出し側
    （documents/contracts のview）は`OSError`の具体的なサブクラスを個別に把握しなくても
    この例外だけを捕捉すればよく、「例外を握りつぶさず意味のある形で伝播させる」設計方針
    （利用者向けのエラーメッセージ表示自体は呼び出し側の責務）。
    """


def save_pending_files(session, session_key, files):
    """screen-storage1「ファイルを選択」→「実行」の複数ファイル選択を、実際にサーバー側の一時領域へ
    保存する。HTML確定版のJSは`mockFiles`という配列名にブラウザメモリ上でファイル名だけを保持する
    モックだが、実サーバーでは複数リクエストにまたがるウィザード（保管画面１→２）の間、ファイル
    実体をどこかに保持する必要があるため、`MEDIA_ROOT/tmp_uploads/`に一時保存しセッションには
    パスと元ファイル名だけを記録する。保管画面２の「登録」で正式なstorage_pathsへ移動する。

    ファイルI/O（ディレクトリ作成・書き込み）は`PendingFileStorageError`にラップして送出する。
    複数ファイル選択時、ループ途中の1件で書き込みが失敗した場合はセッションへの登録前のため
    セッション状態自体は変化しないが、それより前にディスクへ書き込み済みの一時ファイルは
    セッションに未登録のまま`tmp_uploads/`に孤児として残ってしまう。それを防ぐため、失敗時は
    このループ内で新規に書き込んだ一時ファイルだけを巻き戻してから例外を送出する。
    """
    tmp_dir = Path(settings.MEDIA_ROOT) / TMP_UPLOAD_SUBDIR
    try:
        tmp_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.exception("一時アップロード領域の作成に失敗しました: %s", tmp_dir)
        raise PendingFileStorageError("一時アップロード領域を作成できませんでした。") from exc

    # list()でコピーする: session[session_key]が既に存在する場合、session.get()は
    # SessionBase内部dictが保持する同一のlistオブジェクトをそのまま返す。コピーせずに
    # pending.append()するとその場でセッション内部dictも書き換わってしまい、ループ途中の
    # 失敗時（下記のロールバック）でも既にセッションへ反映済みのエントリを取り消せなくなる
    # （実体ファイルは削除されるがpendingのエントリだけ残る、という不整合の原因だった）。
    pending = list(session.get(session_key, []))
    # このループで新規に書き込んだ一時ファイルのパス（失敗時のロールバック用）。
    # session[session_key]への反映はループ完了後にまとめて行うため、失敗時にここまでの
    # 書き込みをディスクから消せばセッション・ディスクとも失敗前の状態に戻る。
    newly_saved_paths = []
    for uploaded_file in files:
        temp_name = f"{uuid.uuid4().hex}_{uploaded_file.name}"
        temp_path = tmp_dir / temp_name
        try:
            with open(temp_path, "wb") as dest:
                for chunk in uploaded_file.chunks():
                    dest.write(chunk)
        except OSError as exc:
            logger.exception("一時アップロードファイルの書き込みに失敗しました: %s", temp_path)
            for saved_path in newly_saved_paths:
                try:
                    saved_path.unlink(missing_ok=True)
                except OSError:
                    # ロールバック自体の失敗はここで握りつぶす（既に本処理は失敗が確定しており、
                    # ロールバック失敗で例外の種類を上書きしても呼び出し側の対処は変わらないため）。
                    # ただし孤児ファイルが残る可能性があるので必ずログに残す。
                    logger.exception("失敗ロールバック中の一時ファイル削除にも失敗しました: %s", saved_path)
            raise PendingFileStorageError("ファイルの保存に失敗しました。") from exc
        newly_saved_paths.append(temp_path)
        pending.append({"temp_name": temp_name, "original_name": uploaded_file.name})
    session[session_key] = pending
    session.modified = True
    return pending


def get_pending_files(session, session_key):
    return session.get(session_key, [])


def clear_pending_files(session, session_key):
    """一時ファイルの実体を削除し、セッションからも消す。保管画面１の再表示時（フォーム未送信の
    まま離脱した残骸を残さないため）、および保管画面２での登録完了後に呼ぶ。

    削除に失敗した項目（`OSError`）も`logger.exception`で記録した上で処理を止めずに続行し、
    最終的にはセッションから無条件に消す（52行目）。これは意図的な設計判断: ここで例外を
    再送出して処理を止めると、他の正常に削除できた項目まで巻き込んで保管画面の遷移自体が
    止まってしまい、利用者から見た実害（画面が進まない）の方が大きい。一方、削除に失敗した
    実体ファイルはセッションから参照が切れた時点でどこからも追跡できなくなる（＝
    `tmp_uploads/`配下に孤児として残り続ける）ため、自動での回収手段は無くログのみが手がかりになる。
    現状は定期クリーンアップの仕組みが無いため、運用上はログを見て手動で掃除するか、将来的に
    `tmp_uploads/`配下の古いファイルを一括削除するバッチ処理を別途用意する必要がある。
    """
    pending = session.get(session_key, [])
    tmp_dir = Path(settings.MEDIA_ROOT) / TMP_UPLOAD_SUBDIR
    for item in pending:
        temp_path = tmp_dir / item["temp_name"]
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            logger.exception("一時アップロードファイルの削除に失敗しました: %s", temp_path)
    session.pop(session_key, None)
    session.modified = True


def open_pending_file(temp_name):
    """一時保存されたファイルをDjangoのFileオブジェクトとして開く（モデルのFileFieldへ割り当てる用）。
    呼び出し側でクローズすること。

    保管画面１→２はセッションをまたぐ複数リクエストのウィザードであり、その間に一時ファイルが
    外部要因（手動でのディスク掃除、運用側のクリーンアップジョブ、まれにAV隔離等）で消える
    ことが現実的にありうる。`FileNotFoundError`を含む`OSError`はここで捕捉し
    `logger.exception`で記録した上で`PendingFileStorageError`にラップして送出する
    （呼び出し側のview〈documents/contracts〉で捕捉し、「最初からやり直してください」等の
    利用者にわかるエラー応答を返す想定）。
    """
    tmp_dir = Path(settings.MEDIA_ROOT) / TMP_UPLOAD_SUBDIR
    temp_path = tmp_dir / temp_name
    try:
        return File(open(temp_path, "rb"), name=temp_name)
    except OSError as exc:
        logger.exception("一時アップロードファイルを開けませんでした: %s", temp_path)
        raise PendingFileStorageError("保管対象のファイルが見つからないか、読み込めませんでした。") from exc


# ==========================================
# チャンク分割アップロード（screen-storage1が、選択されたファイルのサイズが
# settings.MAX_UPLOAD_SIZE_BYTESを超える場合にstatic/js/chunk_upload.jsから自動的に使う）。
# 大容量PDFはDjangoの1リクエストボディ上限（settings.MAX_UPLOAD_SIZE_BYTES/
# DATA_UPLOAD_MAX_MEMORY_SIZE）に引っかかるため、ブラウザ側で5MBずつのチャンクに分割して
# 順次送信し、ここで結合する（core.upload_views.BaseChunkUploadAPIView参照）。
#
# ja_pj_old（core/upload_services.py）の同名機能とは異なり、結合完了ファイルを別の
# 「保留プール」に貯めてから通常アップロードのPOST側で合流させる、という中間層は置いていない。
# 本実装のsave_pending_files/get_pending_filesは（ja_pj_oldと違い）呼ばれるたびに既存の
# セッション内容へ追記する設計のため、combine_upload_chunksから直接同じセッションキーへ
# 追記するだけで、documents/contracts.UploadStep1View.postの通常アップロード分と
# 自然に合流できる。
# ==========================================


class ChunkUploadError(Exception):
    """チャンク分割アップロードの結合処理で、チャンク欠落・サイズ超過等の理由により
    最終ファイルを生成できなかった場合に送出する。呼び出し元（core.upload_views.
    BaseChunkUploadAPIView）がメッセージをそのまま利用者向けエラー表示に使う。
    """


def save_upload_chunk(upload_id, chunk_index, chunk_file):
    """分割アップロードの1チャンクを tmp_uploads/chunks/<upload_id>/chunk_XXXX に保存する。

    upload_idはブラウザ側で生成されファイルパスの一部としてそのまま使うため、呼び出し側
    （core.upload_views.BaseChunkUploadAPIView）で英数字とハイフンのみに制限済みという前提。
    """
    chunk_dir = Path(settings.MEDIA_ROOT) / TMP_UPLOAD_SUBDIR / CHUNK_UPLOAD_SUBDIR / upload_id
    try:
        chunk_dir.mkdir(parents=True, exist_ok=True)
        chunk_path = chunk_dir / CHUNK_NAME_FORMAT.format(chunk_index)
        with open(chunk_path, "wb") as dest:
            for piece in chunk_file.chunks():
                dest.write(piece)
    except OSError as exc:
        logger.exception(
            "チャンクアップロードの保存に失敗しました: upload_id=%s chunk_index=%s", upload_id, chunk_index
        )
        raise PendingFileStorageError("チャンクの保存に失敗しました（通信エラーの可能性があります）。") from exc


def combine_upload_chunks(session, session_key, upload_id, total_chunks, original_filename):
    """全チャンクを結合し、save_pending_filesと同じ形式（tmp_uploads/<uuid>_<元ファイル名>）で
    一時保存した上で、session[session_key]の保留ファイル一覧に追記する。結合後、チャンク断片は
    削除する。

    チャンク欠落・settings.CHUNK_UPLOAD_MAX_SIZE_BYTES超過はChunkUploadErrorを送出する。
    いずれの場合も、既に保存済みのチャンク断片はここで削除してから送出する（失敗時にゴミを
    残さない設計。ja_pj_old combine_upload_chunksと同じ方針）。
    """
    # original_filenameはブラウザ側File.nameをそのまま送ってくる値（save_pending_filesの
    # uploaded_file.nameと同じ信頼度）だが、ここではPath区切り文字を含んでいてもファイル名部分
    # だけを使うようPath(...).nameで正規化する（結合後ファイルの保存パスの一部に使うため）。
    original_filename = Path(original_filename).name

    chunk_dir = Path(settings.MEDIA_ROOT) / TMP_UPLOAD_SUBDIR / CHUNK_UPLOAD_SUBDIR / upload_id
    chunk_paths = [chunk_dir / CHUNK_NAME_FORMAT.format(i) for i in range(total_chunks)]

    total_size = 0
    for i, chunk_path in enumerate(chunk_paths):
        if not chunk_path.exists():
            _delete_chunk_dir(chunk_dir)
            raise ChunkUploadError(f"チャンク {i} が見つかりません。最初からアップロードし直してください。")
        total_size += chunk_path.stat().st_size
        if total_size > settings.CHUNK_UPLOAD_MAX_SIZE_BYTES:
            _delete_chunk_dir(chunk_dir)
            raise ChunkUploadError(
                f"ファイルサイズが上限（{settings.CHUNK_UPLOAD_MAX_SIZE_BYTES // (1024 * 1024)}MB）を超えています。"
            )

    tmp_dir = Path(settings.MEDIA_ROOT) / TMP_UPLOAD_SUBDIR
    temp_name = f"{uuid.uuid4().hex}_{original_filename}"
    temp_path = tmp_dir / temp_name
    try:
        with open(temp_path, "wb") as dest:
            for chunk_path in chunk_paths:
                with open(chunk_path, "rb") as src:
                    shutil.copyfileobj(src, dest)
    except OSError as exc:
        logger.exception("チャンクアップロードの結合に失敗しました: upload_id=%s", upload_id)
        _delete_chunk_dir(chunk_dir)
        raise PendingFileStorageError("ファイルの結合に失敗しました。") from exc

    _delete_chunk_dir(chunk_dir)

    pending = session.get(session_key, [])
    pending.append({"temp_name": temp_name, "original_name": original_filename})
    session[session_key] = pending
    session.modified = True


def _delete_chunk_dir(chunk_dir):
    """結合成功・失敗いずれの場合も呼ばれる、チャンク断片の後片付け。1件の削除失敗で
    後続のチャンクの削除まで諦めると孤児ファイルが増えるだけなので、個別にログを残して続行する
    （clear_pending_filesと同じ設計判断）。"""
    if not chunk_dir.exists():
        return
    for child in chunk_dir.iterdir():
        try:
            child.unlink(missing_ok=True)
        except OSError:
            logger.exception("チャンク断片の削除に失敗しました: %s", child)
    try:
        chunk_dir.rmdir()
    except OSError:
        # 上の削除が一部失敗しディレクトリが空でない場合、または他プロセスのロック等で
        # rmdir自体が失敗した場合。孤児ディレクトリが残るがcleanup対象は将来の課題とし
        # （tmp_uploads全体に定期クリーンアップの仕組みが無いのは既存の制約、
        # core/upload_services.py clear_pending_filesのdocstring参照）、ここでは
        # ログのみに留めて後続処理（利用者への応答）を止めない。
        logger.exception("チャンクディレクトリの削除に失敗しました: %s", chunk_dir)
