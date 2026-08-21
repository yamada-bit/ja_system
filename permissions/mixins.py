import logging

from django.core.exceptions import PermissionDenied

from permissions.services import can_access_settings_menu_item

logger = logging.getLogger(__name__)


class SettingsMenuAccessMixin:
    """設定メニュー配下の画面をSETTINGS_MENU_VISIBLE_ROLES（permissions.services）で
    ビュー単位アクセス制御するmixin。core.views.SettingsMenuViewでのボタン非表示は
    UI上の誘導に過ぎず、URLを直接開けば従来はLoginRequiredMixin止まりで到達できてしまっていた
    （例: 一般ロールが/accounts/staff/を直叩き）。このmixinをdispatch()チェーンに挟むことで
    同じロール判定をサーバー側の実アクセス制御としても強制する。

    使い方: `class FooView(LoginRequiredMixin, SettingsMenuAccessMixin, View)` のように
    LoginRequiredMixinの後（MRO上はLoginRequiredMixin.dispatch内のsuper()呼び出しで
    後から実行される位置）に置き、`settings_menu_key = "foo"` を指定する
    （request.userが認証済みである前提のため、LoginRequiredMixinより先に実行されると
    未ログイン時にget_role()がAnonymousUserを渡されて意図しない挙動になる）。

    権限管理(permissions)アプリのAuthorityEditViewのようにcan_manage_target等で
    対象データ単位のより詳細なアクセス制御を既に自前で行っている画面には適用しない
    （二重管理を避けるため、既存チェックがSETTINGS_MENU_VISIBLE_ROLES相当の制限を包含している
    ことを確認した上で使い分ける）。
    """

    settings_menu_key = None

    def dispatch(self, request, *args, **kwargs):
        if not can_access_settings_menu_item(request.user, self.settings_menu_key):
            logger.warning(
                "設定メニュー「%s」への権限外アクセスを試行: employee_no=%s",
                self.settings_menu_key,
                request.user.employee_no,
            )
            raise PermissionDenied("この画面を利用する権限がありません。")
        return super().dispatch(request, *args, **kwargs)
