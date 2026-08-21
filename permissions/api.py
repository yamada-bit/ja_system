import logging

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.views import View

from masters.models import DocKbn, Group
from organizations.models import Department

logger = logging.getLogger(__name__)


class OptionListAPIView(LoginRequiredMixin, View):
    """screen-authority-editの分類選択・部門間閲覧設定ポップアップ用。
    文書向け分類と契約書向け分類のどちらを返すかは`doc_kbn`パラメータで切り替える
    （doc_visible_groups/contract_visible_groupsの2つのPopupSelectWidgetが同じAPIを共有するため、
    core.api.BaseOptionListAPIViewのように単一doc_kbn固定にはできない）。

    type=dept（contract_visible_departments、Rev1.1で追加）は、他職員に対して閲覧を許可する
    部署を選ぶための管理者・所属長向け設定であり、閲覧者自身の検索範囲を絞るものではないため
    （permissions.services.can_manage_targetで既にアクセス制御済み）、全部署を選択肢として返す。
    """

    def get(self, request):
        option_type = request.GET.get("type")
        if option_type == "group":
            doc_kbn = request.GET.get("doc_kbn", DocKbn.DOCUMENT)
            qs = Group.objects.filter(doc_kbn=doc_kbn, is_deleted=False).order_by("code")
            return JsonResponse({"items": [{"value": g.pk, "label": g.name} for g in qs]})
        if option_type == "dept":
            qs = Department.objects.order_by("branch_code", "section_code")
            return JsonResponse({"items": [{"value": d.pk, "label": str(d)} for d in qs]})
        return JsonResponse({"error": "invalid type"}, status=400)
