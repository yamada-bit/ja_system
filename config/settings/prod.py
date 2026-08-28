from .base import *  # noqa: F401,F403

DEBUG = False

# セキュリティレビュー M-2: base.py の SECRET_KEY は開発用の安全でないフォールバック値
# （"django-insecure-..."）を持つため、本番では .env に SECRET_KEY を設定し忘れると既知の
# リポジトリ公開値でそのまま起動してしまい、セッションクッキー・signing.dumps 系トークンの
# 署名偽造が可能になる。CONTRACT_RETENTION_YEARS 等の他の設定値と違い、鍵は「未設定なら
# 起動失敗」でなければならないため、ここでデフォルト無しの env() で読み直し、未設定なら
# django-environ が ImproperlyConfigured を送出してデプロイを止める。
SECRET_KEY = env("SECRET_KEY")

SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# HTTPヘッダー越しのCookie窃取・MIMEスニッフィング対策。原本フィデリティとは無関係の
# 本番運用上の追加対応（未実装改善候補の棚卸しで発見、2026-08-12）。SECURE_SSL_REDIRECTと
# 異なりdev環境では意味を持たない（HTTPS前提の設定）ため、base.pyではなくここに置く。
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=60 * 60 * 24 * 30)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", default=True)
SECURE_HSTS_PRELOAD = env.bool("SECURE_HSTS_PRELOAD", default=False)
SECURE_CONTENT_TYPE_NOSNIFF = True
# リバースプロキシ配下でのCSRF検証用。空リストのままだとADMIN_EMAILS等と違って「未設定なら
# 機能しない」だけでなく本番の正規オリジンからのPOSTがCSRF検証エラーになるため、.envで
# 必ず実際のホスト名（例: https://ja-doc.example.jp）を設定すること。
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

# 500エラー（未処理例外）発生時に管理者へメール通知する。base.py末尾のコメントに記載していた
# 「将来的には望ましい」対応（未実装改善候補の棚卸しで発見、2026-08-12実装）。
# ADMIN_EMAILSが未設定の場合、django.utils.log.AdminEmailHandlerはADMINSが空なら何もせず
# 早期returnする（Django本体の実装）ため、SMTP未設定環境でも安全にハンドラを組み込める。
ADMINS = [("システム管理者", email) for email in env.list("ADMIN_EMAILS", default=[])]
MANAGERS = ADMINS

SERVER_EMAIL = env("SERVER_EMAIL", default="root@localhost")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default=SERVER_EMAIL)
EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", default="")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)

# base.pyのLOGGINGは辞書オブジェクトとして`from .base import *`でそのまま束縛されるため、
# ここでの変更はprod.py配下でのみ有効（dev.pyは別途base.pyをimportし別インスタンスを持つ）。
# "django.request"は元々console/fileのみでERROR以上を記録していたが、能動的にログファイルを
# 見に行かない限り障害に気付けない状態だった。mail_adminsハンドラを追加してメール通知も行う。
LOGGING["handlers"]["mail_admins"] = {
    "class": "django.utils.log.AdminEmailHandler",
    "level": "ERROR",
}
LOGGING["loggers"]["django.request"]["handlers"] = ["console", "file", "mail_admins"]
