import io
import logging
import zipfile

logger = logging.getLogger(__name__)


def build_zip_archive(objects, *, entity_label: str) -> tuple[bytes, int]:
    """一括ダウンロード用のZIPアーカイブ構築。対象オブジェクトの`file`フィールドを1つのZIPに
    まとめる（documents.services.build_zip_archive/contracts.services.build_zip_archiveが
    メッセージ文言・ログ変数名以外は完全に同一実装のまま重複していたため集約した。CLAUDE.mdの
    「共通処理はcore相当の共通基底クラス・サービス関数に集約し、アプリ間で重複するロジックを
    増やさない」規約への準拠漏れとして品質レビューで発見、2026-08-25修正）。

    1件のファイル実体欠損（`FileNotFoundError`）でZIP全体を失敗させない設計判断
    （「本質的でない処理の失敗で本処理まで巻き込まない」）を維持し、欠損件数を返す。
    欠損自体はログに残した上で、利用者への案内（messages.warning）は呼び出し側の責務とする。
    `entity_label`はログメッセージの`document_id=`/`contract_id=`の出し分けにのみ使う。
    """
    missing_count = 0
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for obj in objects:
            try:
                with obj.file.open("rb") as fh:
                    zf.writestr(obj.file.name.rsplit("/", 1)[-1], fh.read())
            except FileNotFoundError:
                logger.exception(
                    "一括ダウンロード中にファイル実体が見つかりません: %s_id=%s", entity_label, obj.pk
                )
                missing_count += 1
    return buffer.getvalue(), missing_count
