import logging

from django.db import IntegrityError, transaction

logger = logging.getLogger(__name__)


def save_or_none(form, *, log_message, log_args=()):
    """「transaction.atomic()内でform.save() → IntegrityError捕捉 → logger.exception」という
    定型パターンの共通処理。organizations/masters系の登録・編集ビューで同一構造が8箇所
    重複していたため集約した（コード監査で発見、2026-08-25修正）。

    アプリ層のclean_code等は検証後・保存前のTOCTOU競合までは防げないため、最終的な一意性は
    モデルのUniqueConstraintに委ねる。IntegrityError発生時は本関数がNoneを返すので、呼び出し
    側は画面ごとに異なるエラー提示方法（form.add_error/messages.error）でユーザーに案内し、
    トークン再発行・フォーム再描画を行う。transaction.atomic()でsave()を囲むのは、
    IntegrityErrorをtry/exceptで捕捉するだけではDBコネクションが「ロールバック待ち」状態の
    まま残り、直後のクエリ（テンプレート内の関連オブジェクト参照等）がTransactionManagementError
    で失敗するため（atomic()がSAVEPOINTを張り、例外発生時はそこまでロールバックして後続処理を
    継続可能にする）。
    """
    try:
        with transaction.atomic():
            return form.save()
    except IntegrityError:
        logger.exception(log_message, *log_args)
        return None
