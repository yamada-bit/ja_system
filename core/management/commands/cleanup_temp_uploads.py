"""放置された一時アップロード領域（tmp_uploads/）の掃除バッチコマンド。

保管画面１→２（documents/contracts共通のUploadStep1View/UploadStep2View）はセッションを
またぐウィザードのため、確定（保管画面２の「登録」）までファイル実体を`MEDIA_ROOT/tmp_uploads/`
に一時保存する（core.upload_services.save_pending_files）。ブラウザを閉じる・タブを切る等で
ウィザードを完走しなかった場合、この一時ファイルはセッションと紐づいたまま孤児として残り続ける
（同モジュールのclear_pending_filesのdocstring参照）。チャンク分割アップロード
（tmp_uploads/chunks/<upload_id>/）についても、結合前に通信が切れた場合は同様に断片が残る。

いずれも「一定時間より古ければ、進行中のウィザードではなく放置されたものとみなして削除してよい」
という判断が成り立つため、settings.STALE_TMP_UPLOAD_THRESHOLD_HOURS（既定24時間）より
更新日時が古いものを削除する。Windowsタスクスケジューラ等から日次実行する想定
（core.management.commands.extract_pending_pdf_textと同様の運用）。

コマンド名は`ja_system/bat/cleanup_temp_uploads.bat`が既に前提としている名前に合わせている
（2026-08-13、ストレージ調査で判明：同.batはPhase1（ja_pj_old）時代のtmp_uploads配下レイアウト
〈`tmp_uploads/<uuid>/`という1アップロード1フォルダ構成〉を前提にした同名コマンドを呼ぶ想定で
先に用意されていたが、現行実装（`tmp_uploads/<uuid>_<元ファイル名>`の平置き＋
`tmp_uploads/chunks/<upload_id>/`のチャンク断片という別レイアウト）向けのコマンド本体が
移植されないまま残っていた。ここでは現行のレイアウトに合わせて中身を新規に書き、
.bat側の呼び出し名だけを踏襲した）。
"""
import logging
import shutil
import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from core.upload_services import CHUNK_UPLOAD_SUBDIR, TMP_UPLOAD_SUBDIR

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "tmp_uploads/配下の放置された一時アップロードファイル・チャンク断片を削除する。"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="実際には削除せず、削除対象になるファイル・ディレクトリを一覧表示するだけにする",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        tmp_dir = Path(settings.MEDIA_ROOT) / TMP_UPLOAD_SUBDIR
        if not tmp_dir.exists():
            self.stdout.write("tmp_uploads/が存在しないため何もしません。")
            return

        threshold_seconds = settings.STALE_TMP_UPLOAD_THRESHOLD_HOURS * 3600
        cutoff = time.time() - threshold_seconds
        chunk_dir = tmp_dir / CHUNK_UPLOAD_SUBDIR

        removed_files = 0
        removed_dirs = 0
        failed = 0

        # 通常アップロード分：tmp_dir直下の孤児ファイル（chunks/ディレクトリ自体は対象外、後段で扱う）。
        for path in tmp_dir.iterdir():
            if path == chunk_dir:
                continue
            if path.is_dir():
                # 想定外のディレクトリ（手動作成物等）は誤削除を避けるためスキップし、ログのみ残す。
                logger.warning("tmp_uploads直下に想定外のディレクトリがあります（スキップ）: %s", path)
                continue
            try:
                if path.stat().st_mtime < cutoff:
                    if dry_run:
                        self.stdout.write(f"[dry-run] 削除対象: {path}")
                    else:
                        path.unlink()
                    removed_files += 1
            except OSError:
                logger.exception("放置一時ファイルの削除に失敗しました: %s", path)
                failed += 1

        # チャンク分割アップロード分：upload_idごとのディレクトリを丸ごと削除する。
        if chunk_dir.exists():
            for upload_dir in chunk_dir.iterdir():
                if not upload_dir.is_dir():
                    continue
                try:
                    # ディレクトリ自体のmtimeはmkdir後にファイルを追加しても更新されない場合がある
                    # （OS依存）ため、配下ファイルの最新更新時刻で判定する。空ディレクトリは
                    # ディレクトリ自体のmtimeを使う。
                    mtimes = [f.stat().st_mtime for f in upload_dir.iterdir() if f.is_file()]
                    latest = max(mtimes) if mtimes else upload_dir.stat().st_mtime
                    if latest < cutoff:
                        if dry_run:
                            self.stdout.write(f"[dry-run] 削除対象: {upload_dir}")
                        else:
                            shutil.rmtree(upload_dir)
                        removed_dirs += 1
                except OSError:
                    logger.exception("放置チャンクディレクトリの削除に失敗しました: %s", upload_dir)
                    failed += 1

        verb = "削除対象" if dry_run else "削除完了"
        self.stdout.write(
            f"{verb}: 一時ファイル{removed_files}件 / チャンクディレクトリ{removed_dirs}件 / 失敗{failed}件"
        )
