import logging

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.views import View

from masters.models import DocKbn, Group
from organizations.models import Department
from permissions.services import can_access_settings_menu_item

logger = logging.getLogger(__name__)


class OptionListAPIView(LoginRequiredMixin, View):
    """screen-authority-editの分類選択・部門間閲覧設定ポップアップ用。
    文書向け分類と契約書向け分類のどちらを返すかは`doc_kbn`パラメータで切り替える
    （doc_visible_groups/contract_visible_groupsの2つのPopupSelectWidgetが同じAPIを共有するため、
    core.api.BaseOptionListAPIViewのように単一doc_kbn固定にはできない）。

    type=dept（contract_visible_departments、Rev1.1で追加）は、他職員に対して閲覧を許可する
    部署を選ぶための管理者・所属長向け設定であり、閲覧者自身の検索範囲を絞るものではないため
    （permissions.services.can_manage_targetで既にアクセス制御済み）、全部署を選択肢として返す。

    アクセス制御：この画面（screen-authority-edit）自体が設定メニュー「権限管理」
    （authority_management＝管理者・所属長限定）でゲートされているため、本APIも同じ制限を
    サーバー側で課す（review_security.txt 追補 No.2／S2(a)、本ファイル冒頭 U-2。以前は
    LoginRequiredMixinのみで、権限管理画面にアクセスできない一般ロールでも`?type=dept`や
    `?type=group&doc_kbn=contract`を直叩きして部署名・分類名を取得できた）。
    organizations/api.py OptionListAPIViewと同じくdispatch()を明示オーバーライドして
    認証チェック→権限チェックの順序を保証する（SettingsMenuAccessMixin多重継承だと
    未ログイン時にget_role()がAnonymousUserで落ちて500になる問題を避ける）。
    """

    settings_menu_key = "authority_management"

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not can_access_settings_menu_item(request.user, self.settings_menu_key):
            logger.warning(
                "設定メニュー「%s」への権限外アクセスを試行: employee_no=%s",
                self.settings_menu_key, request.user.employee_no,
            )
            raise PermissionDenied("この画面を利用する権限がありません。")
        return super().dispatch(request, *args, **kwargs)

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
