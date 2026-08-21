import logging
import time

from django.contrib.auth import logout
from django.conf import settings

logger = logging.getLogger(__name__)

SESSION_LAST_ACTIVITY_KEY = "last_activity_ts"


class SessionIdleTimeoutMiddleware:
    """自動ログアウト（screen-other-logout-edit「自動ログアウト時間編集」、xlsx その他設定!B102-103
    「本設定値にて、ブラウザで何も操作していないアイドル時間経過後、自動ログアウト処理させること」）。

    request.userを利用するためAuthenticationMiddlewareより後段に置く（config/settings/base.py参照）。
    タイムアウト分数は`masters.SystemSetting.session_idle_timeout_minutes`を正とし、
    未設定・DB未接続時のみ`settings.SESSION_IDLE_TIMEOUT_MINUTES`にフォールバックする。
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            now = time.time()
            last_activity = request.session.get(SESSION_LAST_ACTIVITY_KEY)
            timeout_seconds = self._get_timeout_minutes() * 60
            if last_activity is not None and (now - last_activity) > timeout_seconds:
                logger.info("アイドルタイムアウトによる自動ログアウト: employee_no=%s", user.employee_no)
                logout(request)
            else:
                request.session[SESSION_LAST_ACTIVITY_KEY] = now
        return self.get_response(request)

    def _get_timeout_minutes(self):
        try:
            from masters.models import SystemSetting

            setting = SystemSetting.objects.first()
            if setting:
                return setting.session_idle_timeout_minutes
        except Exception:
            # マイグレーション未適用・DB未接続時等（アプリ起動直後等）でも致命的にしない。
            logger.exception("SystemSettingの取得に失敗したため既定値にフォールバックします。")
        return settings.SESSION_IDLE_TIMEOUT_MINUTES
