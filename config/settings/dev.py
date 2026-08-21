from .base import *  # noqa: F401,F403

DEBUG = env.bool("DEBUG", default=True)

STORAGES["staticfiles"]["BACKEND"] = "django.contrib.staticfiles.storage.StaticFilesStorage"

# WhiteNoiseは既定でSTATIC_ROOT（collectstaticの出力先）を配信するため、static/配下を
# 直接編集してもcollectstaticを実行するまでブラウザに反映されなかった。開発中はfinders
# （STATICFILES_DIRS等）から直接配信させ、collectstatic不要でファイル変更を即座に反映する。
WHITENOISE_USE_FINDERS = True

LOGGING["handlers"]["console"]["level"] = "DEBUG"
LOGGING["root"]["level"] = "DEBUG"
