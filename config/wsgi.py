"""
WSGI config for config project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.prod')

# Webプロセスだけにstatement_timeoutを掛ける（settings.WEB_DB_STATEMENT_TIMEOUT_MS参照）。
# 接続が最初に作られる前（get_wsgi_application()の前）にDATABASESのOPTIONSへ足す必要がある。
# base.pyのDATABASESに直接書くと、バッチ・マイグレーションまで同じタイムアウトになってしまう。
from django.conf import settings  # noqa: E402

if settings.WEB_DB_STATEMENT_TIMEOUT_MS > 0:
    _db_options = settings.DATABASES["default"].setdefault("OPTIONS", {})
    _db_options["options"] = (
        f"{_db_options.get('options', '')} -c statement_timeout={settings.WEB_DB_STATEMENT_TIMEOUT_MS}"
    ).strip()

application = get_wsgi_application()
