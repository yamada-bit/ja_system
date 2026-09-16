"""
Django settings for config project (base / common settings).
JAふくおか八女向け クラウド文書管理システム（HTML確定版 Rev1.0 に基づく作り直し）。
"""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    DEBUG=(bool, False),
)
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY", default="django-insecure-dev-key-change-me")
DEBUG = env.bool("DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["*"])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "organizations",
    "masters",
    "documents",
    "contracts",
    "core",
    "permissions",
    "audit",
    # documents/contracts.extracted_text_normalized 等のGinIndex(gin_trgm_ops)・将来の
    # TrigramSimilarity検索用（フリーワード全文検索は正規化シャドウ列に対して行う。監査B-IDX-1）。
    # 拡張(pg_trgm)自体の有効化はcore.migrations.0001_enable_pg_trgmで行う。
    "django.contrib.postgres",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # request.userを利用するためAuthenticationMiddlewareより後段に置く（screen-other-logout-edit
    # 「自動ログアウト時間編集」に対応。core/middleware.py参照、フェーズ4以降で実装）。
    "core.middleware.SessionIdleTimeoutMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                # base.html の検索結果詳細ポップアップが PDF.js プレビューの要否を知る必要が
                # あり、当ポップアップは全画面共通のため各ビューの get_context_data ではなく
                # コンテキストプロセッサで pdf_js_preview_enabled を全テンプレートへ渡す。
                "core.context_processors.preview_settings",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    # DATABASE_URL未設定時のフォールバック値もja_app（最小権限ロール）に揃える。
    # postgres（スーパーユーザー）をデフォルトにすると、.envの設定漏れ時に気付かず
    # スーパーユーザーで接続してしまうため。
    "default": env.db(
        "DATABASE_URL",
        default="postgres://ja_app:change-me@localhost:5432/ja_db",
    )
}

# screen-login/screen-menu（HTML職員番号ログイン）に対応するカスタムユーザーモデル。
AUTH_USER_MODEL = "accounts.Employee"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# 先頭のハッシュ関数が新規パスワード保存時に使われる（Argon2、PBKDF2よりメモリ消費型で
# 並列総当たりに強い）。2番目以降はArgon2導入前データとの後方互換用の保険。
# 動作にはargon2-cffiパッケージが必須。並び順は変更しないこと。
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
]

LANGUAGE_CODE = "ja"
TIME_ZONE = "Asia/Tokyo"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

MEDIA_URL = "media/"
# 保存データ（アップロードファイル）はアプリコード(ja_pj)と分離し、ja_system/storage/media に格納する。
# コード再配置・再デプロイの影響を受けないようにするための構成。.envのMEDIA_ROOTで上書き可能。
MEDIA_ROOT = Path(env("MEDIA_ROOT", default=str(BASE_DIR.parent / "storage" / "media")))

# manage.py test実行時のみ、MEDIA_ROOTを一時ディレクトリへ差し替えて本番相当ストレージを
# 汚さないようにする（core/test_runner.IsolatedMediaTestRunner参照）。
TEST_RUNNER = "core.test_runner.IsolatedMediaTestRunner"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# PDFプレビュー（保管画面２/検索詳細ポップアップ、screen-storage2・popup-detail）を
# 同一オリジンのiframe/objectで表示するために必要。
X_FRAME_OPTIONS = "SAMEORIGIN"

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "core:menu"
LOGOUT_REDIRECT_URL = "accounts:login"

# アップロードファイルサイズ上限。screen-storage1のドラッグ&ドロップ/複数選択アップロードに対応。
MAX_UPLOAD_SIZE_BYTES = env.int("MAX_UPLOAD_SIZE_BYTES", default=50 * 1024 * 1024)
DATA_UPLOAD_MAX_MEMORY_SIZE = MAX_UPLOAD_SIZE_BYTES

# MAX_UPLOAD_SIZE_BYTESを超えるファイルは、storage1.htmlのJSがチャンクに分割して
# 順次POSTする（core.upload_views.BaseChunkUploadAPIView）。これは結合後の最終ファイルサイズの
# 上限で、DATA_UPLOAD_MAX_MEMORY_SIZE（1リクエストボディの上限）とは独立した値。
CHUNK_UPLOAD_MAX_SIZE_BYTES = env.int("CHUNK_UPLOAD_MAX_SIZE_BYTES", default=500 * 1024 * 1024)

# チャンク1個あたりのバイト数。static/js/chunk_upload.jsが1チャンク=1 POSTで直列送信し、
# core.upload_services.combine_upload_chunksがサーバー側で連結する。サーバーはこの値を
# 参照せず（連結はchunk_index順に並べるだけ）、クライアント側のスループット／障害耐性の
# トレードオフを決める値。以前はJSにハードコードしていたが、テスト用に書き換えたまま戻し
# 忘れる事故があったため（HTML_REIMPL_CHECKLIST_ARCHIVE2.md参照）、settingsへ集約して
# storage1.htmlのテンプレートコンテキスト経由でJSへ渡す。
#
# 推奨: 既定の5MB（5 * 1024 * 1024）のままで問題ない。大容量ファイル主体で往復回数を
#       減らしたい場合は10MB程度まで上げてよい（500MBで100→50往復）。
#   下限の目安: 5MB未満にはしない（往復数とリクエスト処理オーバーヘッドが増えるだけ。
#              リトライ／レジューム機構は無いため小さくしても障害耐性はほぼ改善しない）。
#   上限の制約: 必ず MAX_UPLOAD_SIZE_BYTES（= DATA_UPLOAD_MAX_MEMORY_SIZE、1リクエスト
#              ボディ上限）より十分小さくすること。multipartのオーバーヘッド分の余裕も
#              見て 20〜25MB を超えないのが安全。さらに本番リバースプロキシの
#              ボディサイズ上限（nginx client_max_body_size、既定1MB）がこの値＋αを
#              許可している必要がある（実運用ではこれが最も効く制約）。
CHUNK_UPLOAD_CHUNK_SIZE_BYTES = env.int("CHUNK_UPLOAD_CHUNK_SIZE_BYTES", default=5 * 1024 * 1024)

# tmp_uploads/配下（保管画面１→２のウィザード間の一時保存、チャンクアップロードの断片）は、
# ブラウザを閉じる等でウィザードを完走しなかった場合に孤児として残り続ける
# （core.upload_services.clear_pending_filesのdocstring参照）。この時間（時間単位）より古い
# ファイル・チャンクディレクトリを孤児とみなして削除する
# （core.management.commands.cleanup_temp_uploads、定期バッチ想定。コマンド名は
# ja_system/bat/cleanup_temp_uploads.batが既に前提としている名前に合わせている）。
STALE_TMP_UPLOAD_THRESHOLD_HOURS = env.int("STALE_TMP_UPLOAD_THRESHOLD_HOURS", default=24)

# 自動ログアウト時間（分）の既定値。screen-other-logout-editではmasters.SystemSetting（DB）を
# 正とし管理者が随時変更する。ここでの値はSystemSetting読み込みに失敗した場合のみ使うフォールバック。
SESSION_IDLE_TIMEOUT_MINUTES = env.int("SESSION_IDLE_TIMEOUT_MINUTES", default=60)

# メイン画面「お知らせ」有効期限切れまでXヵ月以内、のXヵ月しきい値（xlsx メイン画面!B36）。既定1ヵ月。
NOTICE_EXPIRING_THRESHOLD_MONTHS = env.int("NOTICE_EXPIRING_THRESHOLD_MONTHS", default=1)
# メイン画面「お知らせ」直近Xヵ月内で削除された、のXヵ月しきい値（xlsx メイン画面!B38）。既定1ヵ月。
# xlsxは上記としきい値を別々の設定値として定義しているため、独立して変更できるよう分離している
# （2026-08-13ユーザー指示。以前は両方とも`masters.SystemSetting.notice_threshold_months`(DB)
# 1つを共有していた）。
NOTICE_DELETED_THRESHOLD_MONTHS = env.int("NOTICE_DELETED_THRESHOLD_MONTHS", default=1)
# 契約書の保存期限（年）固定値（xlsx メイン画面!B48「契約書の保存期限は固定で10年」）。既定10年。
# 以前は`masters.SystemSetting.contract_retention_years`(DB)で保持していたが、値を編集できる
# 管理画面・Django管理サイトが無く、変更依頼を受けた際に「設定ファイル等で容易に変更できる」という
# xlsx要件を実質満たせていなかったため.env経由の設定値に移行した（2026-08-13ユーザー指示）。
CONTRACT_RETENTION_YEARS = env.int("CONTRACT_RETENTION_YEARS", default=10)

# 保存期間設定マスタで「永年」を選択した場合の実年数（xlsx 保存期間設定!B74「「永年」設定値は
# 初期値を50年とし、設定ファイル等で定義し、先方より変更依頼を受けた際に容易に変更できること」）。
# 既定50年。CONTRACT_RETENTION_YEARSと同じ理由（masters.SystemSettingにDB編集用の管理画面・
# Django管理サイトが無く、変更経路が実質DB直接操作しかなかった）で.env経由の設定値に移行した
# （2026-08-27フィデリティ監査で発見・修正）。
RETENTION_PERMANENT_YEARS = env.int("RETENTION_PERMANENT_YEARS", default=50)

# 操作履歴ログ(audit.AuditLog)の最大保存期間(ヵ月)。既定3ヵ月。
# xlsx 操作履歴ログ!B51-52「操作履歴ログの最大保存件数(=CSV出力最大件数)設定値は、初期値を
# 3ヵ月分とし、設定ファイル等で定義し、先方より変更依頼を受けた際に容易に変更できること」。
# 「3ヵ月分」を月数で表現する。この期間より古いログは core.management.commands.
# purge_expired_audit_logs（日次バッチ想定）で物理削除し、一覧表示・CSV出力の対象からも外す
# （audit.services.retention_cutoff_date）。CONTRACT_RETENTION_YEARS/RETENTION_PERMANENT_YEARS
# と同じ理由でDB(masters.SystemSetting)ではなく.env経由の設定値にしている（値を変更する経路が
# 実質DB直接操作しか無く「設定ファイル等で容易に変更できる」要件を満たせていなかったため）。
AUDIT_LOG_RETENTION_MONTHS = env.int("AUDIT_LOG_RETENTION_MONTHS", default=3)

# スキャンPDF（画像PDF）のOCR（Google Cloud Vision）を有効化するかどうか。コンプライアンス部門の
# 承認済みの前提で既定True（2026-08-10ユーザー指示）。Falseにすると、テキスト層の無いPDFはextracted_textが
# 空のまま据え置かれ全文検索の対象外になる（core.ocr_layout_services.OcrDisabledError参照）。
OCR_ENABLED = env.bool("OCR_ENABLED", default=True)
# google-cloud-vision SDKはGOOGLE_APPLICATION_CREDENTIALS環境変数からサービスアカウント鍵
# （JSONファイルのパス）を自動的に読み込む。django-environのEnv.read_env()は.envの内容を
# os.environへ反映済みのため、.envにこの変数を書くだけでSDK側の追加設定は不要。
GOOGLE_APPLICATION_CREDENTIALS = env("GOOGLE_APPLICATION_CREDENTIALS", default="")
# OCRはPDFをpdf2imageでページごとに画像化し、各画像をVisionのdocument_text_detectionへ
# 1ページずつ個別に投入する方式で固定する（PDFバイト列を直接同期APIに渡す方式〈1リクエスト
# 最大5ページの制約あり〉との切替は設けない。全ページ確実にOCRできる本方式のみを採用する
# 2026-08-10ユーザー指示）。pdf2imageが依存するpopplerバイナリの
# ディレクトリパス。OSのPATHにpopplerが通っている環境では設定不要（空文字のままでよい）。
POPPLER_PATH = env("POPPLER_PATH", default="")

# スキャン文書の OCR 行レイアウト（core.ocr_layout_services、座標＋テキスト）を
# documents.Document/contracts.Contract.ocr_textdata（JSONField）へ保存するかどうか。保存した
# 座標データは、検索可能なPDF（OCRテキスト埋め込み版）を core.searchable_pdf_services が
# 必要時に生成するための元データになる（監査 案3、2026-09-11：以前は埋め込み済みPDFを
# searchable_file へ恒久保存する OCR_EMBED_TEXT_TO_PDF だったが、桁違いに小さい座標データの
# 保存＋遅延生成に置き換えた。旧設定名からのリネーム）。既定False：OCR自体はコンプライアンス
# 承認済みの前提で有効化したが（OCR_ENABLED参照）、本文由来のデータ（座標＋テキスト）を原本とは
# 別に DB へ恒久保存する運用の承認は別途必要なため、既定は無効のまま。OCR自体は常に
# core.ocr_layout_services.extract_text_and_layout_via_ocr（座標付き抽出）を使うため、このフラグを
# 切り替えても Vision API 呼び出し方法自体は変わらない（Trueの間は取得済みの座標データを
# ocr_textdata へ保存するだけで、Vision API を二重に呼ぶことはない）。当初実装は privacy_flag の
# 影響なし（Document/Contract とも設定のみに従う。将来 privacy_flag=True を除外したくなった場合の
# 切替点は core.management.commands.extract_pending_pdf_text.Command._should_store_textdata、
# 2026-09-11ユーザー方針）。
OCR_STORE_TEXTDATA = env.bool("OCR_STORE_TEXTDATA", default=False)

# 保管画面２・編集画面・検索結果詳細ポップアップ・検索/閲覧画面「文書イメージ」欄の
# PDF プレビュー描画方式。
# True（既定）: PDF.js（static/vendor/pdfjs）で各ページを「プレビュー枠の幅ぴったり」の
#   <canvas> に自前描画する（static/js/pdf-preview.js）。縦長・横長を問わず枠にフィットし、
#   IntersectionObserver による遅延描画で数百ページの PDF でも同時描画は数ページに留まる。
# False: 従来どおりブラウザ内蔵 PDF ビューアの <iframe>。狭い枠（実質約340px）ではツールバーが
#   見切れて水平スクロールバーが出る／横長ページが小さく右が欠ける、という既知の問題がある。
# 2026-08-31 ユーザー依頼で PDF.js 化。PDF.js 側に問題が出た場合は .env で
# PDF_JS_PREVIEW_ENABLED=False にすれば即座に旧 <iframe> 方式へ戻せる（テンプレート・JS とも
# この値で分岐しており、pdfjs のアセットが読み込まれることも無くなる）。
# 画像ファイル（<img> プレビュー）とモック文言表示はこのフラグの影響を受けない。
PDF_JS_PREVIEW_ENABLED = env.bool("PDF_JS_PREVIEW_ENABLED", default=True)

# ログ出力先。MEDIA_ROOTと同様にコード（ja_pj）と分離し、ja_system/storage/logs に格納する。
LOG_DIR = Path(env("LOG_DIR", default=str(BASE_DIR.parent / "storage" / "logs")))
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
            "level": "INFO",
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(LOG_DIR / "ja_pj.log"),
            "maxBytes": 10 * 1024 * 1024,
            "backupCount": 5,
            "encoding": "utf-8",
            "formatter": "verbose",
            "level": "INFO",
        },
    },
    # rootにhandlersを設定することで、各アプリが `logging.getLogger(__name__)` を呼ぶだけで
    # 個別のlogger登録なしにconsole/fileへ出力される。
    "root": {
        "handlers": ["console", "file"],
        "level": "INFO",
    },
    "loggers": {
        "django.request": {
            "handlers": ["console", "file"],
            "level": "ERROR",
            "propagate": False,
        },
        "django.security": {
            "handlers": ["console", "file"],
            "level": "WARNING",
            "propagate": False,
        },
        # pdfminer（pdfplumber経由、core.text_extraction_servicesの登録時同期テキスト抽出）と
        # urllib3（google-cloud-vision等が内部で使うHTTP接続、core.ocr_layout_servicesの
        # 5分間隔OCRバッチ）は、自前のloggerレベルを設定しておらず
        # rootのlevelをそのまま継承する。dev.py（LOGGING["root"]["level"]="DEBUG"）の環境では
        # これらライブラリ内部のトークン解析・HTTP接続確立等の大量のDEBUGログがコンソールへ
        # 素通しされてしまう（アプリ自身のlogger.debug()呼び出しとは無関係）ため、
        # WARNING以上のみ通すよう個別に引き上げる（propagate=Trueのままなので、実際に
        # WARNING以上が出た場合はroot経由でconsole/fileに記録される）。同様の理由で
        # NOTSETのままroot(DEBUG)を継承するライブラリが他に無いか確認済みだが
        # （psycopgは自前でWARNING設定済み、google.*はクライアント初期化時に自己抑制する
        # ため対象外）、新たにPDF/HTTP系ライブラリを追加した際は同じ観点の確認が必要。
        "pdfminer": {
            "level": "WARNING",
        },
        "urllib3": {
            "level": "WARNING",
        },
    },
}
# 本番運用時の障害検知について: 2026-08-12、`prod.py`に`ADMINS`／本番用SMTP設定と
# `AdminEmailHandler`（"django.request"ロガーへの追加）を実装した。実際にメール通知を
# 受け取るには.envの`ADMIN_EMAILS`（宛先）・`EMAIL_HOST`等（送信経路）の設定が必要
# （未設定の間はDjango本体の仕様でAdminEmailHandlerが早期returnし何もしない、安全側）。
