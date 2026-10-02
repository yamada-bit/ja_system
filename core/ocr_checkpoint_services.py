"""OCRのチェックポイント（ページ単位の途中経過）と、失敗時のバックオフ（再試行間隔）の管理。

スキャン文書のOCR（core.ocr_layout_services）は1ページずつVision APIへ投入するが、文書の途中で
失敗（割当量超過・タイムアウト・バッチの実行時間切れ等）すると、従来は次回バッチで1ページ目から
全ページをやり直しており、成功済みのページまで再び課金・割当量を消費していた。ここでは

- OCR済みページの結果（本文・座標データ）をファイルへ1ページずつ追記し、次回は済んだページを
  Visionへ再送せず失敗したページから再開する（チェックポイント）。
- 失敗した文書の試行回数と「次に試してよい時刻」を記録し、同じ文書を5分間隔で叩き続けない
  （指数バックオフ。割当量超過・障害中にVisionへ無駄な呼び出しを重ねないため）。

を担う。DBのスキーマは変えず、`MEDIA_ROOT/ocr_checkpoints/` 配下の2ファイルで持つ：

- `<label>_<pk>.state.json` … 小さな状態（PDFのSHA-256・試行回数・次回時刻）。バックオフ判定は
  対象文書が多くてもこの小さいファイルだけを読めば済む。
- `<label>_<pk>.pages.jsonl` … 1ページ1行の追記専用。1ページ完了するたびに1行足すだけなので、
  数百ページでも全体を書き直さない。クラッシュで最終行が途中までしか書かれていなくても、
  読み込み時にその行だけ捨てれば他ページは使える。

チェックポイントはあくまで最適化であり、読み書きの失敗（OSError・壊れたJSON）でOCR本体を
止めない（ログに残して、チェックポイント無しとして続行する）。PDFのSHA-256が一致しない場合
（ファイルが差し替わった等）は、古い途中経過を使うと別文書の本文が混ざるため破棄する。
OCR完了後（DB保存まで成功したあと）に`clear`で消す。放置された古いファイルは`purge_stale`が
更新日時で回収する（バッチ起動時に呼ぶ）。
"""
import hashlib
import json
import logging
import os
import time
from pathlib import Path

from django.conf import settings

from core import ocr_layout_services

logger = logging.getLogger(__name__)

CHECKPOINT_SUBDIR = "ocr_checkpoints"
_STATE_VERSION = 1


def _checkpoint_dir():
    return Path(settings.MEDIA_ROOT) / CHECKPOINT_SUBDIR


def _paths(label, pk):
    base = _checkpoint_dir() / f"{label}_{pk}"
    return base.with_name(base.name + ".state.json"), base.with_name(base.name + ".pages.jsonl")


def _read_state(state_path):
    """状態ファイルを読む。無い・壊れている場合は None。"""
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            state = json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        logger.exception("OCRチェックポイントの状態ファイルを読めませんでした（無視します）: %s", state_path)
        return None
    if not isinstance(state, dict) or state.get("version") != _STATE_VERSION:
        return None
    return state


def is_in_backoff(label, pk, now=None):
    """この文書がバックオフ中（前回の失敗から再試行間隔が経っていない）ならTrue。
    PDFを読まずに判定できるよう、小さい状態ファイルだけを見る。"""
    state_path, _pages_path = _paths(label, pk)
    state = _read_state(state_path)
    if not state:
        return False
    return float(state.get("next_retry_at", 0)) > (time.time() if now is None else now)


def backoff_seconds(attempts):
    """試行回数（失敗の通算回数、1始まり）に対する待ち時間（秒）。基準値から2倍ずつ延ばし、上限で頭打ち。"""
    base = max(settings.OCR_FAILURE_BACKOFF_MINUTES, 0) * 60
    # 上限が基準値より小さい（0を含む）場合は、基準値まで切り上げる＝待ち時間を延ばさず一定にする。
    # 「0＝上限なし」と解釈すると、失敗のたびに待ちが倍々になり事実上再試行されなくなるため。
    cap = max(settings.OCR_FAILURE_BACKOFF_MAX_MINUTES * 60, base)
    wait = base * (2 ** max(attempts - 1, 0))
    return min(wait, cap)


def clear(label, pk):
    """この文書のチェックポイントを削除する（OCR完了・DB保存成功後、冪等）。"""
    for path in _paths(label, pk):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        except OSError:
            logger.exception("OCRチェックポイントの削除に失敗しました: %s", path)


def purge_stale(retention_days=None, now=None):
    """更新日時が保持期間より古いチェックポイントを削除し、削除したファイル数を返す。
    文書がその後削除された・OCR設定が無効化された等で、誰も続きを処理しなくなった残骸の回収用。
    処理中の文書はページ完了のたびに更新日時が進むので対象にならない。"""
    days = settings.OCR_CHECKPOINT_RETENTION_DAYS if retention_days is None else retention_days
    directory = _checkpoint_dir()
    if days <= 0 or not directory.is_dir():
        return 0
    threshold = (time.time() if now is None else now) - days * 86400
    removed = 0
    try:
        for path in directory.iterdir():
            try:
                if path.is_file() and path.stat().st_mtime < threshold:
                    path.unlink()
                    removed += 1
            except OSError:
                logger.exception("古いOCRチェックポイントの削除に失敗しました: %s", path)
    except OSError:
        # ディレクトリの走査自体の失敗（権限・共有の切断等）。残骸の回収はあくまで後片付けなので、
        # 呼び出し元の本文抽出バッチを巻き込まず、ログに残して次回に回す。
        logger.exception("OCRチェックポイントの掃除に失敗しました（スキップします）: %s", directory)
    return removed


class OcrCheckpoint:
    """1文書分のチェックポイント。`load`で作り、`completed_pages`と`save_page`をOCR関数へ渡す。"""

    def __init__(self, label, pk, pdf_sha256, state, completed_pages):
        self.label = label
        self.pk = pk
        self.pdf_sha256 = pdf_sha256
        self.attempts = int(state.get("attempts", 0)) if state else 0
        # {page_no: (本文, [TextDatas])}。OCR関数がこのページのVision呼び出しを省くために使う。
        self.completed_pages = completed_pages
        self._state_path, self._pages_path = _paths(label, pk)

    @classmethod
    def load(cls, label, pk, pdf_bytes):
        """途中経過を読み込む。SHA-256が合わない（別ファイル）・読めない場合は破棄して空から始める。"""
        sha = hashlib.sha256(pdf_bytes).hexdigest()
        state_path, pages_path = _paths(label, pk)
        state = _read_state(state_path)
        completed = {}
        if state and state.get("pdf_sha256") != sha:
            logger.warning("OCRチェックポイントのPDFが現在のファイルと一致しないため破棄します: %s_%s", label, pk)
            clear(label, pk)
            state = None
        if state:
            completed = cls._read_pages(pages_path)
        elif pages_path.exists():
            # 状態ファイルが無いのにページ結果だけ残っている（書き込み途中の中断等）。出所が確かでない
            # ので使わず、消して空から始める。
            clear(label, pk)
        return cls(label, pk, sha, state, completed)

    @staticmethod
    def _read_pages(pages_path):
        completed = {}
        try:
            with open(pages_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                        completed[int(row["p"])] = (
                            row["text"], ocr_layout_services.textdatas_from_json(row["td"]),
                        )
                    except (ValueError, KeyError, TypeError):
                        # クラッシュで途中までしか書かれていない行など。その1ページだけ捨てて再OCRする。
                        logger.warning("OCRチェックポイントの壊れた行を無視します: %s", pages_path)
        except FileNotFoundError:
            pass
        except OSError:
            logger.exception("OCRチェックポイントのページ結果を読めませんでした（空から始めます）: %s", pages_path)
            return {}
        return completed

    def _write_state(self, **fields):
        state = {
            "version": _STATE_VERSION,
            "pdf_sha256": self.pdf_sha256,
            "attempts": self.attempts,
            "next_retry_at": 0,
        }
        state.update(fields)
        tmp_path = self._state_path.with_name(self._state_path.name + ".tmp")
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(state, f)
        os.replace(tmp_path, self._state_path)  # 書き込み途中の状態ファイルを読ませないため、置き換えで確定する

    def save_page(self, page_no, text, textdatas):
        """1ページ分のOCR結果を追記する。失敗してもOCR本体は続行する（最適化にすぎないため）。"""
        try:
            if not self._state_path.exists():
                self._write_state()
            row = {"p": page_no, "text": text, "td": ocr_layout_services.textdatas_to_json(textdatas)}
            with open(self._pages_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            os.utime(self._state_path)  # 処理中の文書をpurge_staleの対象にしない
        except OSError:
            logger.exception(
                "OCRチェックポイントへのページ保存に失敗しました（続行します）: %s_%s page=%s",
                self.label, self.pk, page_no,
            )

    def record_failure(self, now=None):
        """OCRの失敗を記録し、次に試してよい時刻を決める。(試行回数, 待ち秒数)を返す。"""
        self.attempts += 1
        wait = backoff_seconds(self.attempts)
        current = time.time() if now is None else now
        try:
            self._write_state(next_retry_at=current + wait)
        except OSError:
            logger.exception(
                "OCR失敗のバックオフ記録に失敗しました（次回も即再試行されます）: %s_%s", self.label, self.pk,
            )
        return self.attempts, wait
