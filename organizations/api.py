import logging

from django.core.exceptions import PermissionDenied

from core.api import BaseOptionListAPIView
from masters.models import DocKbn
from organizations.models import Department
from permissions.services import can_access_settings_menu_item

logger = logging.getLogger(__name__)


class OptionListAPIView(BaseOptionListAPIView):
    """screen-dept-editの部署統合・分割ポップアップ（type=deptのみ使用）用。
    分類(group)/カテゴリーは本画面では使わないが、BaseOptionListAPIViewが要求するため
    文書向けをデフォルトにしておく。

    統合・分割の対象部署はログインユーザー自身の検索閲覧範囲とは無関係（部署マスタ管理という
    別の業務）なため、BaseOptionListAPIView._department_items()の自部署絞り込みは適用せず、
    全部署を選択肢として返す。この画面（screen-dept-edit）自体がdept_management（管理者限定）で
    ゲートされているため、本APIも同じ制限をサーバー側で課す必要がある
    （以前はLoginRequiredMixinのみで、管理者以外でもこのURLを直叩きすれば全部署一覧を取得できて
    しまっていた。コード監査で発見、2026-08-24修正）。

    permissions.mixins.SettingsMenuAccessMixinを多重継承で挟み込まない理由：
    BaseOptionListAPIView(LoginRequiredMixin, View)がLoginRequiredMixinとViewを隣接した基底
    クラスとして固定しているため、SettingsMenuAccessMixinを間に挟もうとするとMRO順序が崩れ、
    LoginRequiredMixinの認証チェックより先に権限チェックが走ってしまう
    （permissions.services.get_role()はAnonymousUserを渡すとAttributeErrorで落ちるため、
    未ログイン時に500になる）。そのためdispatch()を明示的にオーバーライドし、認証チェック→
    権限チェックの順序を保証する。
    """

    doc_kbn = DocKbn.DOCUMENT
    visible_groups_kind = "document"
    settings_menu_key = "dept_management"

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

    def _department_items(self, request):
        qs = Department.objects.order_by("branch_code", "section_code")
        return [{"value": d.pk, "label": str(d)} for d in qs]
