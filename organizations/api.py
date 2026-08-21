import logging

from core.api import BaseOptionListAPIView
from masters.models import DocKbn
from organizations.models import Department

logger = logging.getLogger(__name__)


class OptionListAPIView(BaseOptionListAPIView):
    """screen-dept-editの部署統合・分割ポップアップ（type=deptのみ使用）用。
    分類(group)/カテゴリーは本画面では使わないが、BaseOptionListAPIViewが要求するため
    文書向けをデフォルトにしておく。

    統合・分割の対象部署はログインユーザー自身の検索閲覧範囲とは無関係（部署マスタ管理という
    別の業務）なため、BaseOptionListAPIView._department_items()の自部署絞り込みは適用せず、
    全部署を選択肢として返す。
    """

    doc_kbn = DocKbn.DOCUMENT
    visible_groups_kind = "document"

    def _department_items(self, request):
        qs = Department.objects.order_by("branch_code", "section_code")
        return [{"value": d.pk, "label": str(d)} for d in qs]
