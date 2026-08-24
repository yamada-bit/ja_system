import logging

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.views import View

from core.forms import search_year_choices
from masters.models import Category, Group
from masters.services import scope_queryset_by_department
from organizations.models import Department
from organizations.services import visible_department_ids
from permissions.services import (
    PermissionRole,
    contract_searchable_department_ids,
    department_ids_for_group_scope,
    get_role,
    visible_groups,
)

logger = logging.getLogger(__name__)


class BaseOptionListAPIView(LoginRequiredMixin, View):
    """popup-select（部署/分類/年/カテゴリー選択ポップアップ）用の選択肢一覧を返すJSON API。

    HTML確定版のJSは`popupPopupMasterData`というハードコードされたモック配列から選択肢を
    描画していたが、実装では実データ（masters.Group/Category, organizations.Department）を返す。
    `doc_kbn`/`visible_groups_kind`はdocuments/contractsのサブクラスで指定する
    （documents/contracts間で共通のロジックはcoreに集約するという規約に沿う）。
    """

    doc_kbn = None
    visible_groups_kind = None
    # 部署選択ポップアップの許容範囲切替（"document"は管理者のみ無制限、"contract"はRev1.1の
    # 契約書-部門間閲覧設定を加味する）。documents/contracts双方のOptionListAPIViewで上書きする。
    department_kind = "document"

    def get(self, request):
        option_type = request.GET.get("type")
        if option_type == "dept":
            items = self._department_items(request)
        elif option_type == "group":
            items = self._group_items(request)
        elif option_type == "category":
            items = self._category_items(request)
        elif option_type == "year":
            items = self._year_items()
        else:
            # popup-select共通API側で想定しているtype以外の値。原本のpopup-select呼び出しは
            # 常にJS側で固定文字列を渡すため、ここに来るのは主にAPI直叩き・パラメータ改ざんの
            # 兆候であり、想定外の分岐としてlogger.warningに残す。
            logger.warning(
                "BaseOptionListAPIViewに未知のtypeが指定されました: type=%s, user=%s",
                option_type, request.user,
            )
            return JsonResponse({"error": "invalid type"}, status=400)
        return JsonResponse({"items": items})

    def _department_items(self, request):
        # xlsx 保管!B79-82: 部署選択は権限が"管理者"のユーザのみ。フォーム/ウィジェット側では
        # 選択欄自体を非表示・disabled化しているが、このAPI自体は独立したエンドポイントのため、
        # 直叩きされた場合に備えて同じ制限をここでも適用する（監査で発見：以前は権限に関わらず
        # 全部署を返しており、_group_items()のvisible_groups適用と非対称だった）。
        # 非管理者でも自部署＋閲覧部署範囲テーブル（部署統合・分割）分は選択肢に含める
        # （search_services.build_queryset()の絞り込み範囲と一致させる、documents/contracts共通）。
        # kind="contract"の場合は権限管理「契約書-部門間閲覧設定」で追加された部署も含める
        # （permissions.services.contract_searchable_department_ids、Rev1.1で追加）。
        qs = Department.objects.all().order_by("branch_code", "section_code")
        if self.department_kind == "contract":
            allowed = contract_searchable_department_ids(request.user)
        elif get_role(request.user) == PermissionRole.ADMIN:
            allowed = None
        else:
            allowed = set(visible_department_ids(request.user))
        if allowed is not None:
            qs = qs.filter(pk__in=allowed)
        return [{"value": d.pk, "label": str(d)} for d in qs]

    def _group_items(self, request):
        qs = Group.objects.filter(doc_kbn=self.doc_kbn, is_deleted=False)
        allowed = visible_groups(request.user, kind=self.visible_groups_kind)
        if allowed is not None:
            qs = qs.filter(pk__in=allowed.values_list("pk", flat=True))
        # xlsx 検索・閲覧・変更/保管シート(Rev1.2)「分類選択は…自部署の内容を表示」。
        # documents/forms.py・contracts/forms.pyのフォーム初期表示と同じ絞り込みを、
        # ポップアップ本体のAPIでも適用する（フォーム側のqueryset差し替えだけでは
        # popup-selectがこのAPIを直接叩くため効かない）。
        dept_ids = department_ids_for_group_scope(request.user, kind=self.visible_groups_kind)
        qs = scope_queryset_by_department(qs, dept_ids)
        return [{"value": g.pk, "label": g.name} for g in qs.order_by("code")]

    def _category_items(self, request):
        qs = Category.objects.filter(doc_kbn=self.doc_kbn, is_deleted=False)
        dept_ids = department_ids_for_group_scope(request.user, kind=self.visible_groups_kind)
        qs = scope_queryset_by_department(qs, dept_ids)
        return [{"value": c.pk, "label": c.name} for c in qs.order_by("code")]

    def _year_items(self):
        # xlsx 検索・閲覧・変更!B137-140「対象年選択は…今年～文書が保存されている最古の年」
        # （B499「※文書管理と同じ」で契約書も同じ規則）。documents.forms.SearchForm/
        # contracts.forms.SearchFormのyear選択肢と実装を共有する（core.forms.search_year_choices）。
        return [{"value": y, "label": label} for y, label in search_year_choices(self.doc_kbn)]
