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

    [優先度: 低・見送り、コード監査 2026-08-25] LoginRequiredMixinのみでSettingsMenuAccessMixin
    等のロール制御を持たないため、権限管理画面自体へのアクセス権が無い一般ロールでも
    `?type=dept`（全部署一覧）や`?type=group&doc_kbn=contract`（契約書向け分類一覧）を直接
    叩いて取得できる。ただしこのAPI自体はPermissionProfileの中身を変更できず、返す情報も
    部署名・分類名という他画面（検索・保管のpopup-select等）でも同種ロールに露出しうる情報
    のため実害は限定的と判断し、見送った。他のpopup-select系オプションAPI
    （core.api.BaseOptionListAPIView等）のゲーティング方針と揃えるかどうかは別途要検討。
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
