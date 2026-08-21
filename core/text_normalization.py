import unicodedata

from django.db.models import F, Value
from django.db.models.functions import Replace


def strip_name_spaces(text):
    """氏名検索用に、姓・名の間の区切り（全角/半角スペース）を除去する。

    xlsx 職員マスタ!B44・権限管理!B39(Rev1.1)「氏名を入力。姓と名を全角スペース区切りで
    フルネーム検索可能とする。」に対応。DB側の氏名にスペースが入っているかどうか
    （"農協　太郎"/"農協太郎"どちらの表記でも保存され得る）に関わらず一致させるため、
    検索キーワード・比較対象の双方からスペースを除去した上で部分一致させる方針にする。
    """
    return (text or "").replace("　", "").replace(" ", "")


def filter_by_full_name(qs, name, *, field_name="name"):
    """氏名フィールドを`strip_name_spaces`と同じ規則でスペース除去した上でicontains検索する。

    `filter_staff_queryset`（accounts）・`filter_authority_queryset`（permissions）の
    双方で使う共通ロジックのため、coreに集約する（コーディング規約）。
    """
    stripped = strip_name_spaces(name)
    if not stripped:
        return qs
    return qs.annotate(
        _name_no_space=Replace(
            Replace(F(field_name), Value("　"), Value("")), Value(" "), Value("")
        )
    ).filter(_name_no_space__icontains=stripped)


def normalize_for_search(text):
    """検索用に半角全角の表記ゆれを吸収する正規化。

    文書管理システム_簡易設計指示書_Rev1_0の「各検索条件に入力された文字は、数字の半角全角、
    カタカナの半角全角、アルファベットの半角全角を問わず、検索できるようにする。」という要件に
    対応するため、NFKC正規化を使う（全角英数字は半角に、半角カタカナ〈濁点・半濁点含む〉は
    全角カタカナに統一される）。検索キーワード側だけを正規化しても、DB側の値が逆の表記
    （全角/半角）だとLIKE比較が一致しないため、documents.Document/contracts.Contractの
    title_normalized等のシャドウカラム（保存時にこの関数で生成）と検索キーワードの双方に
    同じ正規化を適用して比較する前提の関数。
    """
    return unicodedata.normalize("NFKC", text or "")
