import datetime

from django.utils import timezone

# xlsx 保管!B300,B581・検索・閲覧・変更!B339-340,B664-665「初回登録から1週間以上経過している
# ものは削除不可。ボタンを非表示にする」（documents.services.DELETE_WINDOW_DAYS/
# contracts.services.DELETE_WINDOW_DAYSが同じ値のまま重複定義されていたため集約
# 〈品質レビューで発見、2026-08-25修正〉）。
DELETE_WINDOW_DAYS = 7


def can_delete(obj, *, window_days: int = DELETE_WINDOW_DAYS) -> bool:
    """検索・閲覧画面の削除ボタン表示可否（xlsx 検索・閲覧・変更!B331,B337,B659,B663(Rev1.2)
    「削除されている(削除フラグがTrue)文書/契約書は、ボタンを非表示とする」）。
    documents.services.can_delete/contracts.services.can_deleteがDELETE_WINDOW_DAYS定数ごと
    完全に同一実装のまま重複していたため集約した（deletion_denial_messageと同じ経緯。
    品質レビューで発見、2026-08-25修正）。`window_days`は将来アプリごとに日数を変える必要が
    生じた場合の拡張点として残すが、既定値は両アプリ共通のDELETE_WINDOW_DAYS。
    """
    if obj.is_deleted:
        return False
    return timezone.now() - obj.save_date < datetime.timedelta(days=window_days)


def deletion_denial_message(obj, *, entity_name: str) -> str:
    """`can_delete(obj)`がFalseの場合に利用者へ提示する拒否理由メッセージ。
    documents.services.deletion_denial_message/contracts.services.deletion_denial_messageが
    「文書」/「契約書」の文言以外は完全に同一実装のまま重複していたため集約した
    （build_zip_archiveと同じ経緯。品質レビューで発見、2026-08-25修正）。
    `entity_name`は「文書」「契約書」の出し分けにのみ使う。
    """
    if obj.is_deleted:
        return f"この{entity_name}は既に削除されています。"
    return f"保存から1週間以上経過した{entity_name}は削除できません。"
