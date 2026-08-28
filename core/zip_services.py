import io
import logging
import zipfile

logger = logging.getLogger(__name__)


def _dedupe_entry_name(name: str, used: set[str]) -> str:
    """ZIPエントリ名の同名衝突を避ける。`display_name`は重複防止UUIDを除いた元ファイル名なので
    文書間で普通に重複し得る（以前はUUID付き内部名をそのまま使っていたため偶然一意になって
    いただけ。レビュー指摘C-4）。衝突時は拡張子の手前に" (2)", " (3)"…を付ける
    （OSのファイルマネージャの慣習に合わせる）。
    """
    if name not in used:
        used.add(name)
        return name
    stem, dot, ext = name.rpartition(".")
    base, suffix = (stem, "." + ext) if dot else (name, "")
    i = 2
    while f"{base} ({i}){suffix}" in used:
        i += 1
    result = f"{base} ({i}){suffix}"
    used.add(result)
    return result


def build_zip_archive(objects, *, entity_label: str) -> tuple[bytes, int]:
    """一括ダウンロード用のZIPアーカイブ構築。対象オブジェクトの`file`フィールドを1つのZIPに
    まとめる（documents.services.build_zip_archive/contracts.services.build_zip_archiveが
    メッセージ文言・ログ変数名以外は完全に同一実装のまま重複していたため集約した。CLAUDE.mdの
    「共通処理はcore相当の共通基底クラス・サービス関数に集約し、アプリ間で重複するロジックを
    増やさない」規約への準拠漏れとして品質レビューで発見、2026-08-25修正）。

    1件のファイル実体の読み取り失敗でZIP全体を失敗させない設計判断
    （「本質的でない処理の失敗で本処理まで巻き込まない」）を維持し、失敗件数を返す。
    失敗自体はログに残した上で、利用者への案内（messages.warning）は呼び出し側の責務とする。
    `entity_label`はログメッセージの`document_id=`/`contract_id=`の出し分けにのみ使う。

    捕捉範囲は`FileNotFoundError`だけでなく`OSError`全般（`PermissionError`・
    `IsADirectoryError`・ストレージ側のI/Oエラー等）とする。単体ダウンロード
    （core.record_views.BaseFileServeView）が既にOSError全般をHttp404へ変換しているのに対し、
    以前ここは`FileNotFoundError`しか見ておらず、選択100件のうち1件がディレクトリ化／権限不整合
    しているだけで正常な99件ごと500になっていた（レビュー指摘C-3）。
    """
    missing_count = 0
    used_names: set[str] = set()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for obj in objects:
            try:
                with obj.file.open("rb") as fh:
                    # 単体ダウンロード（core.record_views.BaseFileServeView）がContent-Dispositionに
                    # display_name（UUID接頭辞を除いた元名）を使うのに合わせ、ZIPエントリ名も
                    # display_nameにする（レビュー指摘C-4）。
                    entry_name = _dedupe_entry_name(obj.display_name, used_names)
                    zf.writestr(entry_name, fh.read())
            except OSError:
                logger.exception(
                    "一括ダウンロード中にファイル実体を読み取れませんでした: %s_id=%s", entity_label, obj.pk
                )
                missing_count += 1
    return buffer.getvalue(), missing_count
