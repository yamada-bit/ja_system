# 本番リリース前の作業・注意点

外部の「文書管理システム_残項目_本番リリース手順書.xlsx」を補完する、コード側で対応が必要な
リリース前作業のメモ。原本HTML/xlsxには現れない運用・ビルド面の項目を集約する（`/healthz/`
エンドポイントなどと同種の、原本一次情報源の外側の話）。

新たにリリース前対応が必要な項目が出たら、実装是非にかかわらずここに1件ずつ追記する。

**デプロイ手順・フォルダ構成・定期バックアップ運用・定期実行バッチ運用の本体は
`doc/文書管理システム_環境構築・実装手順書.xlsx`（シート1〜10）が正**。旧実装
`../ja_pj_old/deploy.md` の内容はそちらへ移管済みで、かつ現行より新しい
（本番方式が Waitress+NSSM → IIS+httpPlatformHandler+Waitress に変わっている 等）。
このファイルはその xlsx が扱わない「コード側の未整備・要検討項目」だけを持つ。

（2026-09-16注記：本文中の過去エントリで`review_*.txt`等を「プロジェクトルート直下」と
記述している箇所は実行当時の状態の記録であり、そのまま残している。2026-09-16以降の
置き場所は`reviews/`（review_*.txt・release_baseline.txt・xlsx_audit_*.txt）と
`docs/`（*.mdの文書類）。今後の追記もこの新しい置き場所を前提に書くこと。）

---

## 1. static/js の minify（未実装・リリース時に対応）

**方針**：`static/js/*.js` はリリース時に minify を実行し、`static/js/*.min.js` を生成する。
本番のテンプレートは `.min.js` をリンクする。

### 現状（2026-09-08 時点）

- `static/js/` に3ファイル：`common.js` / `chunk_upload.js` / `pdf-preview.js`（いずれも
  minify前のソースを直接リンク）。
  - `templates/base.html`：`js/common.js`、`js/pdf-preview.js`
  - `templates/documents/storage1.html`、`templates/contracts/storage1.html`：`js/chunk_upload.js`
  - `static/vendor/pdfjs/pdf.min.js` / `pdf.worker.min.js` は配布元が minify 済みのため対象外。
- `config/settings/base.py` は WhiteNoise `CompressedManifestStaticFilesStorage`。
  `collectstatic` 時に **gzip/brotli 圧縮とハッシュ付きファイル名は付与されるが、minify はされない**。
- `config/settings/dev.py` は `STATICFILES_DIRS` から直接配信（`collectstatic` 不要、
  ファイル変更を即反映）。＝開発時にビルドステップを挟まない前提。

### リリース時に必要な手順（実装時に確定させる）

1. **minifier の選定**
   - `rjsmin`（pure-Python、Node 不要）が「フレームワーク不使用・素のJS」方針に最も合う。
   - `terser`（Node 依存）は圧縮率・デッドコード除去で上だが、庁内ビルド環境に Node を要求する。
   - → Node 前提を持ち込まない `rjsmin` を第一候補とする。
2. **生成タイミング**：`collectstatic` の **前** に `static/js/*.js` → `static/js/*.min.js` を生成。
   ManifestStaticFilesStorage はソースに実在するファイルにしかハッシュ名を付けないため、
   `.min.js` が物理的に存在している必要がある。
3. **テンプレートの参照切替**：DEBUG 時（`dev.py`／ソース直配信）は `js/common.js`、
   本番は `js/common.min.js` を参照。切替方法は実装時に決める（`settings.DEBUG` を
   context processor でテンプレートへ渡す／専用テンプレートタグを1つ用意する 等）。
   対象は `base.html`・`documents/storage1.html`・`contracts/storage1.html` の3テンプレート。
4. **`.min.js` の git 扱い**：生成物のため `.gitignore` に追加するのが素直（`staticfiles/` は
   既に ignore 済み）。コミットする場合はソース変更時の再生成漏れに注意。
5. **リリース手順書への反映**：確定後、`環境構築・実装手順書.xlsx` シート5「本番サーバー構築手順」
   手順8（collectstatic）にも「minify 実行 → `collectstatic`」の順序を明記する
   （同シート D 列は既に本節を参照している）。

### 補足

- 転送量の削減効果は WhiteNoise の gzip/brotli で大部分がすでにカバーされている。
  minify の主目的は **パース時間の短縮とソースの秘匿**であり、転送量の追加改善幅は小さい。
- 3ファイルとも規模が小さいため、優先度は「リリース前に対応すれば十分」（恒常的な
  ビルドパイプライン整備までは不要）。

### 対応済み（2026-09-16）

上記方針通り`rjsmin`を採用し実装した。

- **minifier**：`requirements.txt`に`rjsmin==1.2.5`を追加。
- **生成コマンド**：`core/management/commands/minify_static_js.py`（`python manage.py
  minify_static_js`）。`settings.BASE_DIR/static/js/*.js`（`*.min.js`自体は対象外）を走査し、
  同名の`*.min.js`を生成する。対象0件・I/O失敗は`CommandError`で明示的に落とす
  （CLAUDE.mdの例外処理規約に沿い、具体的な例外型を捕捉して`logger.exception`後に再送出）。
- **テンプレート切替**：`core/templatetags/js_static.py`の`{% js_static %}`タグ
  （`{% static %}`のラッパー）。`settings.DEBUG`を見て、`True`ならソース、`False`なら`.min.js`を
  参照するURLを返す。`base.html`（`common.js`・`pdf-preview.js`）・
  `documents/contracts/storage1.html`（`chunk_upload.js`）の3テンプレートを`{% static %}`から
  `{% js_static %}`へ切替（PDF.js本体`vendor/pdfjs/*.min.js`・CSS3ファイルは対象外、従来通り
  `{% static %}`のまま）。
- **`.min.js`のgit扱い**：`.gitignore`に`/static/js/*.min.js`を追加（生成物、コミットしない）。
- **検証**：`python manage.py minify_static_js`実行→3ファイルとも約50%のサイズ縮小を確認
  （例：`common.js` 51,305→24,382バイト）。Browser paneで`DEBUG=True`のdev環境を確認し、
  `js/common.js`・`js/pdf-preview.js`（非minify版）が200で読み込まれ表示・コンソールとも
  問題ないことを確認。`python manage.py collectstatic --settings=config.settings.prod`も
  正常終了し、`staticfiles/staticfiles.json`に`js/common.min.js`等がハッシュ付きで登録される
  ことを確認（`DEBUG=False`側の動作確認）。ユニットテスト
  （`core.tests.JsStaticTagTests`・`core.tests.MinifyStaticJsCommandTests`）を追加、
  core 158件PASS。
- **手順書反映**：`環境構築・実装手順書.xlsx`（`doc/文書管理システム_環境構築・実装手順書.xlsx`）
  シート5手順8（C10/D10）に「minify_static_js実行→collectstatic」の順序を追記
  （編集前に`doc/backup_20260916/`へバックアップ済み）。

---

## 2. 本番の初期マスタデータ投入手段が未確定（最優先）

`環境構築・実装手順書.xlsx` シート2（開発PC）手順9〜11・シート5（本番サーバー）手順7〜9 とも、
`migrate` → `createsuperuser` までしか定義していない。`seed_test_data` は
「一覧・検索・保管画面の表示確認用のダミーデータ」で **本番実行しない**と明記されている
（同シート2 手順11、`core/management/commands/seed_test_data.py` 冒頭）。データ投入用の
マイグレーション（`RunPython`）も無い。

そのため、本番で以下の初期データを何で入れるかが未定：

- 保存期間マスタ（1ヵ月／1年／3年／5年／10年／永年）… `masters.RetentionPeriod`
- システム権限プロファイル（管理者／所属長／一般）… `permissions.PermissionProfile`
- 部署・職位・職階の初期データ … `organizations.Department` / `accounts.Position` / `accounts.Rank`

**選択肢**：(a) 既存台帳からのデータ移行スクリプト、(b) 管理画面 `/admin/` ＋各マスタ画面での
手入力、(c) 本番用シードコマンド新設（`seed_initial_masters` 等、`seed_test_data` と別物として
文書・契約書のダミーは作らない）。どれで行くか決めてから本番構築手順を確定する。旧実装 README の
`seed_demo` は現行に存在しない。

### 対応済み（2026-09-16）

ユーザー判断：(c) 専用シードコマンドを新設。実装中に、この項目の範囲を超える**本番構築手順
そのものを止めるバグ**を発見したため、あわせて対応した。

**新規発見：`createsuperuser`が本番手順として実行不能**——`accounts.Employee.department`は
`null=False`・デフォルト無しの必須外部キーだが、`EmployeeManager.create_superuser`
（`accounts/models.py`）は`department`・`rank`・`position`のいずれも設定しない。これらは
`USERNAME_FIELD`/`REQUIRED_FIELDS`（`employee_no`/`name`のみ）に含まれないため、Django標準の
`createsuperuser`は対話プロンプトで`department`を聞かず、`department_id=NULL`のままINSERTしようと
して**NOT NULL制約違反で失敗する**。部署が1件も無いフレッシュDBでは、部署管理・権限管理画面への
アクセス自体に管理者権限が必要という循環依存があり、`organizations.Department`のDjango管理サイト
登録も閲覧専用（`ReadOnlyModelAdmin`）、`accounts.Employee`は管理サイト未登録のため、他の経路でも
回避できない。旧`環境構築・実装手順書.xlsx`のシート2手順10・シート5手順7が案内していた
「`migrate` → `createsuperuser`」は、この2手順の通りには実行できなかった。

**対応**：
- `accounts/management/commands/bootstrap_admin.py`を新設。`createsuperuser`の代わりに、
  部署・最初の管理者職員（`is_staff`/`is_superuser=True`）・権限プロファイル
  （`PermissionProfile(role=ADMIN)`）を1回のトランザクションでまとめて対話作成する。
  職員が1件でも既に存在する場合は`CommandError`で中断（2人目以降は通常の職員マスタ画面
  `/accounts/staff/regist/`を使う）。パスワードは`django.contrib.auth.password_validation.
  validate_password`（`AUTH_PASSWORD_VALIDATORS`）で検証し、不一致・弱いパスワードは再入力を促す。
- `core/management/commands/seed_initial_masters.py`を新設。保存期間設定マスタ
  （文書用：1ヵ月/1年/3年/5年/10年/永年、`kbn=DOCUMENT`のみ）を`get_or_create`でべき等に投入する。
  契約書は選択式ではなく`settings.CONTRACT_RETENTION_YEARS`で固定年数、電子決裁は恒久的に
  スコープ外のため、いずれも投入対象に含めない。`accounts.Rank`/`Position`はDjangoの
  `TextChoices`としてコードに保持するのみでDBマスタではないため、投入対象そのものが存在しない
  （item2原文の「部署・職位・職階の初期データ」のうち、DBシードが実際に必要なのは部署のみで、
  それは`bootstrap_admin`が最初の1件を、以降は通常の部署管理画面が担う）。
- `環境構築・実装手順書.xlsx`（`doc/文書管理システム_環境構築・実装手順書.xlsx`）シート2手順10
  （開発PC）・シート5手順7（本番）とも`createsuperuser`を`seed_initial_masters`＋
  `bootstrap_admin`の実行に置き換えた（編集前に`doc/backup_20260916/`へバックアップ済み）。
- テスト：`accounts.tests.BootstrapAdminCommandTests`（部署・職員・権限プロファイルの作成、
  既存職員がいる場合の拒否、パスワード不一致・弱いパスワードでの再入力、既存部署の再利用）・
  `core.tests.SeedInitialMastersCommandTests`（投入内容・べき等性・契約書/電子決裁を触らないこと）
  を追加。実DB（開発環境、既存職員5件）で`bootstrap_admin`実行時に想定通り`CommandError`で
  拒否されることも確認。全体1031件PASS。

---

## 3. 定期実行バッチ4本が dev settings で実行される

`ja_system/bat/` の4本（`cleanup_temp_uploads` / `extract_pending_pdf_text` /
`purge_expired_audit_logs` / `purge_expired_deleted_records`）は `DJANGO_SETTINGS_MODULE` を
設定しておらず、`manage.py` 既定の `config.settings.prod` ではなく **`config.settings.dev`** で
動く（`manage.py:9`）。DATABASE_URL は `.env` 共通なので DB 操作自体は正しく行われるが、

- `DEBUG=True` 相当（`dev.py`）で動く
- `prod.py` の 500 エラーメール通知（`mail_admins` ハンドラ）が効かない
- 静的ファイル関連の storage 設定が dev 版になる（バッチ処理には影響薄）

**対応**：各 `.bat` の `pushd` 前に `set DJANGO_SETTINGS_MODULE=config.settings.prod` を1行追加する。
`環境構築・実装手順書.xlsx` シート10「定期実行バッチ運用」の登録手順にも同様の注記を入れる。
（Web プロセス側は web.config の `environmentVariables` で prod 指定済み＝シート6。バッチだけ漏れている。）

### 対応済み（2026-09-16）

`ja_system/bat/` の4本（`cleanup_temp_uploads.bat` / `extract_pending_pdf_text.bat` /
`purge_expired_audit_logs.bat` / `purge_expired_deleted_records.bat`。いずれも`ja_pj`のgit管理外）
の `pushd %TARGET_DIR%` 直前に `set DJANGO_SETTINGS_MODULE=config.settings.prod` を追加した。
`cleanup_temp_uploads.bat` を実際に実行し、prod設定下でも正常終了（一時ファイル削除ログが
想定通り出力される）ことを確認済み。`環境構築・実装手順書.xlsx`
（`doc/文書管理システム_環境構築・実装手順書.xlsx`）シート10にも「11. 実行時の設定
（DJANGO_SETTINGS_MODULE）」を追記した（編集前に`doc/backup_20260916/`へバックアップ済み）。

---

## 4. リバースプロキシ配下の HTTPS 判定（`SECURE_PROXY_SSL_HEADER` 未設定）

本番は IIS + httpPlatformHandler が TLS を終端し、内部の Waitress へは **平文 HTTP** で転送する
（`環境構築・実装手順書.xlsx` シート1 A11・シート6）。この構成では Django が全リクエストを
非セキュアと判定するため、

- `config/settings/prod.py` の `SECURE_SSL_REDIRECT=True`（既定）が **HTTPS→HTTPS の無限リダイレクト**を起こす
- `request.is_secure()` が常に False → `SESSION_COOKIE_SECURE` 等と組み合わせて不整合

`config/settings/prod.py` に `SECURE_PROXY_SSL_HEADER` が無いのが原因。

**対応**：IIS 側が転送するプロトコルヘッダ（httpPlatformHandler／ARR の構成に依存。一般には
`X-Forwarded-Proto`）を確認し、`prod.py` に
`SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")` 相当を追加する。ヘッダを
信頼してよいのは「外部から直接その名前のヘッダを送れない」ネットワーク構成が前提なので、
`.env` 経由で切替可能にしておく（プロキシを挟まない構成では無効化）。
`環境構築・実装手順書.xlsx` シート5 手順13（TLS 終端後のセキュリティ設定）に手順を追記する。

### 対応済み（2026-09-15）

`config/settings/prod.py` に `.env` の `TRUST_X_FORWARDED_PROTO`（既定 False）で切替可能な形で
`SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")` を追加した。`SECURE_SSL_REDIRECT`
は元の `env.bool(..., default=True)` のまま変更していない（ヘッダを正しく信頼できれば
`request.is_secure()` が正しく判定されるため、無限リダイレクトは`SECURE_SSL_REDIRECT`を
Falseにせずとも解消する。Falseにすると、パケットフィルタ設定漏れで直接HTTPアクセスされた際の
HTTPS強制という保護が失われるため採用しなかった）。`.env.example` にも追記済み。

### シート5手順13への追記（2026-09-16）

`環境構築・実装手順書.xlsx`（`doc/文書管理システム_環境構築・実装手順書.xlsx`）を確認したところ、
シート5「12-4：エンハンスドLB使用時」には既にTRUST_X_FORWARDED_PROTOの案内があったが、**LBを使わず
証明書をIISへ直接バインドする基本構成（手順12・12-2/12-3、本番の主経路）には同じ注記が無かった**。
基本構成でもIIS→httpPlatformHandler→Waitressの内部転送は平文HTTPであり、構造上はLB経由と同じ
「TLS終端後に平文で転送」の状態にあるが、httpPlatformHandlerがX-Forwarded-Protoを自動転送するかは
IISのバージョン・構成に依存し机上では断定できないため、ユーザー確認の上、**「要現地確認」として**
手順13（D18）に注記を追加した：本番稼働前に無限リダイレクトが発生しないか実機確認し、発生する場合は
LBケースと同様にネットワーク構成（Waitress待受ポートへの外部直接アクセス遮断）を確認した上で
TRUST_X_FORWARDED_PROTO=Trueを設定する、という手順。編集前に`doc/backup_20260916/`へバックアップ済み。

---

## 5. CSV 取込で新規登録される職員の初期パスワード（初回強制変更が無い）

出典: review_security.txt 参考 I-1／S3、review_pending.txt U-31。

accounts/csv_import_services.py の新規職員は初期パスワード `ja` ＋ 職員番号下4桁で作成される
（簡易設計指示書 職員マスタ B117-119 が明示する仕様。本ブランチの新規事項ではない）。
パスワードは Argon2 ハッシュで保存されるが、**初回ログイン時のパスワード変更を強制する仕組みが
無い**ため、初期パスワードが変更されないまま運用されうる（規則性があり第三者に推測可能）。

**対応（リリース時に業務側と確認）**：以下のいずれかを決める。
- (a) リリース直後に「初期パスワードの一括変更依頼」を全職員へ通知する運用にする
- (b) 初回ログイン時のパスワード変更強制を実装する（要件・画面フローの確定が必要。原本 HTML/
  xlsx にこの画面は無いため、追加機能としてユーザー承認を得てから着手）

簡易設計指示書の当該箇所（職員マスタ B117-119）が「要再確認（赤字）」でないか、
業務要件の最終確認とあわせてチェックする。

### 対応方針確定（2026-09-16）

ユーザー判断：(a) 運用で対応。初回ログイン強制変更機能は実装せず、**リリース直後に全職員へ
「初期パスワードの一括変更依頼」を通知する運用ルール**とする。原本HTML/xlsxに存在しない画面を
追加しない、という原本フィデリティ方針とも整合する。運用手順書（リリース手順書側）への
通知タスク追記は本ファイルのスコープ外（xlsx側で管理）。

---

## 6. 監査 action 文言の半角→全角スペース統一による既存 AuditLog の表記ゆれ

出典: review_code_permissions_accounts.txt No.4／C13、review_pending.txt U-32。

監査ログの action（「画面名　＋　全角スペース　＋　ボタン名」形式、xlsx 操作履歴ログ B63）を
半角スペース→全角スペースへ統一した経緯があり、統一前に記録された AuditLog レコードには
旧表記（半角スペース）が残っている。action 列は操作履歴ログ画面・CSV 出力の**検索対象では
ない**（絞り込みは職員番号・氏名・イベントメッセージ・個人情報フラグ・操作日のみ）ため、
実害は一覧・CSV の表示上の表記ゆれだけ。

**対応（リリース時に判断）**：
- 本番リリース前（初回投入）なら、統一済みの表記だけが入るため作業不要。
- 既にリリース済みの環境へ後追い適用する場合のみ、既存 AuditLog の action を一括 UPDATE で
  旧表記→新表記へ揃えるか、表記ゆれを許容するかを決める（RunPython マイグレーション or
  管理コマンドを用意）。

### 対応方針確定（2026-09-16）

ユーザー確認：本システムは新規リリース（既存本番のAuditLogを引き継がない）。統一済みの表記だけが
入るため**対応不要で確定**。既存本番環境からの移行が発生するケースが将来出た場合のみ、上記の
一括UPDATE要否を改めて判断する。

---

## 7. P9 最終ゲート実行結果（2026-09-11）

RELEASE_QUALITY_WORKFLOW.md ⑦の最終ゲート（P9）を実行した結果。対象は `main...HEAD`
（HEAD=28d1ce9、ブランチ `feat/storage2-per-file-metadata`）。環境: Python 3.13.11 /
Django 5.2.9 / venv `C:\Users\yamad\Claude\JA\ja_system\venv`。

**結論：ブロッカーなし。リリース可。**（本ゲートで検出した「高」2件・「中」1件は全て本ゲート内で
修正・回帰テスト追加・全体テスト確認まで完了済み。以下1〜6は詳細）。

### 1. 全体テスト × ベースライン照合

`release_baseline.txt` を P0 で取得済みの前提だったが、**本セッション開始時点でプロジェクト
直下にもgit履歴にも存在しなかった**（P0セッションでの保存漏れ、または成果物の取り違えと思われる。
運用上の抜けとして記録。次回P0実行時は生成後に必ずファイルの存在を確認すること）。

ベースラインが無いため「既存失敗との差分」という形の照合はできなかったが、代わりに
`python manage.py test --verbosity=1` を実行の要所ごとに都度フルセットで流し、**現在の失敗数が
常に0件であること**を直接確認する形で代替した：

- 本ゲート開始時点（修正前）：1008件 実行、**失敗0・エラー0**。
- 3.のレビューで検出した3件（下記）を修正し、回帰テストを4件追加した後の最終実行：
  **1013件 実行、失敗0・エラー0（OK）**。

新規に増えた失敗はゼロ、既存失敗の残数もゼロ（ベースラインが仮に別途存在していたとしても、
現在ゼロ件である以上「悪化していない」ことは保証される）。

### 2. 静的チェック

- `python manage.py makemigrations --check --dry-run` → `No changes detected`（OK）
- `python manage.py check` → `System check identified no issues (0 silenced)`（OK）
- `python manage.py check --deploy --settings=config.settings.prod` → WARNING 2件、
  いずれもレビュー済みで許容：
  - **W019**（`X_FRAME_OPTIONS` が `DENY` でない）：`config/settings/base.py` のコメント通り、
    PDFプレビュー（保管画面２・検索結果詳細ポップアップ）を同一オリジンの `iframe`/`object` で
    表示するために `SAMEORIGIN` を意図的に設定している。許容。
  - **W021**（`SECURE_HSTS_PRELOAD` 未設定）：既定 `False` のままで、プリロードリストへの登録は
    別途の運用判断が必要な事項のため妥当。`.env` の `SECURE_HSTS_PRELOAD` で有効化可能。
  - 上記チェックはこの開発環境の `.env`（`ALLOWED_HOSTS=*` 等、dev向けの値）を使って実行して
    おり、本番用 `.env` そのものではない点に注意。本番デプロイ時は `.env.example` の案内に従い
    `ALLOWED_HOSTS`・`CSRF_TRUSTED_ORIGINS`・`SECRET_KEY` 等を実運用値に設定すること
    （`config/settings/prod.py` は未設定なら `ImproperlyConfigured` で起動を止める設計のため、
    設定漏れ自体は起動時に検知できる）。
  - 実行のたびに django-environ から `Invalid line:  ` という警告が出るが、これはこの開発環境の
    ローカル `.env` 末尾に紛れ込んだ空白行が原因。`.env` は `.gitignore` 対象でリリース差分にも
    本番環境にも関係しないため、リリースの可否とは無関係。

### 3. 差分全体レビュー（/code-review high 相当）

`main...HEAD` 全体を対象に、「4グループ＋セキュリティの個別修正が互いに矛盾・重複していないか」
「共通コード（core・config/settings・base.html・common.js）の変更が他画面に副作用を出していないか」
に絞って8観点（line-by-line・削除された挙動の監査・cross-file呼び出し追跡・重複/再利用・
単純化・効率性・altitude・CLAUDE.md規約準拠）を並列調査した。**3件を「高」「中」として即時修正**
（優先度判断・修正とも本セッション内で実施）：

- **【高・修正済み】検索の期間逆転入力によるフェイルオープン**
  （[documents/search_services.py](documents/search_services.py)・
  [contracts/search_services.py](contracts/search_services.py)・
  [audit/services.py](audit/services.py)）。`data = form.cleaned_data if form.is_valid() else {}`
  という既存パターンに対し、review_pending.txt No.3で追加した `core.forms.validate_date_range`
  （期間の開始＞終了を弾くクロスフィールド検証）が組み合わさり、**期間を逆に入力しただけで
  部署・分類・タイトル・フリーワード等の他条件も含めて全て無視され、スコープ内の全件が
  無条件に表示される**状態になっていた（操作履歴ログはCSV出力も同様）。原本の想定は
  「逆転期間は単に0件」であり、大幅な後退だった。`form.is_valid()`の真偽で全体を門番せず、
  クロスフィールド検証で無効化された項目だけを欠落させる形に修正（`validate_date_range`が
  `add_error(end_field, ...)`する際、Djangoの仕様で該当フィールドだけが`cleaned_data`から
  除外される性質を利用）。documents/contracts/auditの3箇所に回帰テストを追加。
- **【高・修正済み】契約書「関連書類」タイトルの部署スコープ越境漏洩**
  （[contracts/views.py](contracts/views.py) `_related_rows_for_contract`/`_resolve_related_rows`）。
  検索結果詳細ポップアップ（`contracts/api.py`、review_security.txt No.1／S1）では部署スコープ外の
  関連契約書タイトルを伏せ字にする対応が入っていたが、**編集画面・一括編集画面・保管画面２側の
  同機能には同じガードが漏れていた**（CLAUDE.mdが明示的に警告する「同一注記の横展開漏れ」の
  典型例。独立した3系統の調査が同一箇所に収束）。`filter_valid_related_ids`がスコープ変更後も
  既存の紐付けを`keep_ids`で維持する仕様のため、部署間閲覧設定の変更後に「今は閲覧できない
  契約書」への紐付けが普通に残り得る。api.py側と同じ伏せ字ロジックを共有ヘルパーに切り出して
  views.py側にも適用、回帰テストを追加。
- **【中・修正済み】検索用PDF遅延生成でpypdf例外が未捕捉**
  （[core/record_views.py](core/record_views.py) `BaseSearchablePdfView.get`）。原本PDF実体が
  破損している場合、`core.pdf_text_embed_services.embed_textdatas_into_pdf`内の`PdfReader`呼び出しが
  `pypdf.errors.PdfReadError`等を送出するが、`OSError`/`SearchablePdfUnavailable`しか捕捉して
  おらず未処理のまま500になり得た（CLAUDE.mdの「外部境界は具体的な例外型を捕捉し
  logger.exceptionで記録」規約に反する）。このエンドポイントはまだどの画面からもリンクされて
  いないため実害は限定的。`PyPdfError`捕捉＋`logger.exception`＋`Http404`を追加、回帰テストを追加。
- **【低・記録のみ、方針通り未修正】** documents/contracts間の実装重複6件
  （per-fileメタデータフォームの`__init__`ロジック、アップロード登録のトランザクション処理、
  `_edit_delete_context`、`SearchForm`の自部署デフォルト計算、`_strip_ext`、越境アクセス監査
  ログ記録の`api.py`インライン重複）。RELEASE_QUALITY_WORKFLOW.mdの既定方針（再利用性・
  単純化・効率性の指摘は無理に直さず、別件で該当ファイルを触るときについで直す程度でよい）に
  従い記録のみで修正しない。
- `core/middleware.py`の例外捕捉範囲を`Exception`から`DatabaseError`へ狭めた変更（コメントで
  「実装バグは握りつぶさず伝播させる」と明記）は、CLAUDE.mdの「具体的な例外型を捕捉する」
  規約に沿った意図的な設計判断であることを確認。対応不要。
- altitude（根本原因での対応か）・cross-file呼び出し整合性・CLAUDE.md規約準拠の観点では、
  上記以外に新規の高優先度問題は検出されなかった。

### 4. フィデリティ・スポット再確認

`views.py`/`forms.py`/`api.py`を変更した20ファイル（accounts/audit/contracts/core/documents/
masters/organizations/permissions の各アプリ）のうち、差分が特に大きい `contracts/views.py`
（722行差分）・`documents/views.py`（494行差分）を中心に、原本HTML
（`../../HTML/html6/index.html` + `style.css`）と突き合わせた。

- 3.で検出した2件（期間逆転バグ・関連書類越境漏洩）は、フィデリティ側の調査からも独立に
  検出された（複数系統の調査が同一箇所に収束＝確度が高い）。いずれも修正済み。
- `{# ... #}`複数行コメントの罠（CLAUDE.md記載の既知の落とし穴）：変更テンプレート全件を
  機械的に確認し、該当する複数行コメントは全て`{% comment %}`で書かれており問題なし。
- `BaseBulkEditView`が提供するcontext変数、監査ログaction文言の全角スペース統一、
  masters重複エラーのフィールド→非フィールドエラー変更後の表示、accounts CSV出力の
  パスワード列廃止　等は、原本・xlsxとの整合を確認し問題なし。

### 5. 実アプリのスモークテスト

Browser paneで`runserver`（`.claude/launch.json`の`django-dev`構成）を起動し、下記フローを
一巡確認。**コンソールエラー・テンプレート構文の生表示・500は一件も発生せず**：

- `/accounts/login/`でログイン（職員番号1・菅理太郎）
- メイン画面：お知らせ件数（文書・契約書とも「有効期限切れ」「期限まで1ヶ月以内」
  「直近1ヶ月内で削除」の3種）が表示されることを確認
- `/documents/search/`で検索一覧表示→行クリックでプレビュー欄更新→ダブルクリックで
  検索結果詳細ポップアップ（ダウンロード/変更/削除ボタン）表示を確認
- `/documents/upload/step1/`（ファイル選択）→step2（部署・分類・カテゴリー選択ポップアップ、
  PDF.jsによるプレビュー描画）→登録→完了モーダル、を実PDFファイルで一巡
- 登録した文書を検索結果詳細ポップアップから削除→メイン画面お知らせの「直近1ヶ月内で
  削除された文書」リンクから遷移して削除済み一覧（ゴミ箱相当）に表示されることを確認
- `/contracts/search/`で同様に検索・詳細ポップアップ（契約金額・契約先名・関連書類欄を含む）
  を確認
- `/settings/`から設定メニュー各画面（職員マスタ・部署管理・分類管理・カテゴリー管理・
  保存期間設定・権限管理・操作履歴ログ）を開き、いずれも一覧が正常表示されることを確認
  （操作履歴ログには本テストで行った削除操作等が正しく記録されていることも確認）
- `/healthz/` → `200 OK` `{"status": "ok", "database": "ok"}`

なお、削除操作は`window.confirm()`によるネイティブダイアログを伴う仕様（`common.js`
`triggerDeleteFromDetail`）のため、自動テストツールの制約上`window.confirm`を一時的に
上書きして確認した（アプリケーションコード自体は変更していない）。

### 6. 総合判断

**ブロッカーなし。リリース可。** 検出した「高」2件・「中」1件は全て本ゲート内で修正・
テスト追加・全体テスト（1013件）確認まで完了。

ただし以下は本ゲートのスコープ外として残っており、引き続き別途対応が必要：

- 本ファイルの1〜6（static/js minify・本番初期マスタ投入手段・定期バッチのsettings module
  未指定・`SECURE_PROXY_SSL_HEADER`未設定・CSV初期パスワードの初回強制変更・監査ログ表記
  ゆれ）は本ゲートの対象外で、いずれも未解決のまま。
- `release_baseline.txt`が実際には作成されていなかった運用上の抜け（上記1.参照）。次回
  同種のP0実行時はファイル生成後に存在確認を行うこと。

---

## 8. 本番シークレット（SECRET_KEY／DBパスワード／GCPサービスアカウント鍵／SMTPパスワード）の生成・保管・ローテーション方針

`.env.example`は各値の「原則」（最小権限ロールを使う、パスを差し替えられる 等）は示すが、
実際の秘匿値をどう**生成**し、生成後どこにどう**保管**し、いつ・どう**ローテーション**するかは
未文書化だった（2026-09-14 指摘）。以下を本番運用の確定方針とする。

### 共通方針

- 秘匿値は例外なく本番サーバー上の`.env`（gitignore対象、リポジトリにコミットしない）にのみ
  平文で保持する。チケット・チャット・メール等に平文のまま貼り付けない（受け渡しが必要な場合は
  パスワードマネージャー等の共有機能を使う）。
- `.env`のファイルアクセス権限は、Webプロセス（IIS AppPool／Waitress）実行ユーザーおよび
  運用担当者のみに限定する（Windows ACL、`icacls`で確認・設定）。
- バックアップ対象に`.env`・GCPサービスアカウント鍵JSONを含める場合、バックアップ自体を
  暗号化するか、アクセス制御をファイル本体と同水準にする。
- 値を変更したら、Webプロセス（IIS）と定期実行バッチ（`ja_system/bat/`配下4本、本ファイル3.参照）
  の両方に新しい値が反映されるよう対象プロセスを再起動する。片方だけ更新すると新旧値が混在する。

### SECRET_KEY

- **生成**：`python -c "from django.core.management.utils import get_random_secret_key as g; print(g())"`
  （`.env.example`記載の既存の生成例。50文字のランダム文字列）。
- **保管**：本番`.env`のみ。開発環境の`.env`とは別の値にする（同一値を使い回さない）。
- **ローテーション**：定期ローテーションは不要（値を変更すると全セッション・署名済みCookie・
  パスワードリセット用トークン等が一斉に無効化されるため、通常運用では変更しない）。漏洩が
  疑われる場合のみ再生成し、`.env`更新後にWebプロセスを再起動する（＝全利用者が再ログインを
  求められる点を事前に周知してから実施する）。

### DATABASE_URLのパスワード（ja_appロール）

- **生成**：20文字以上の英大文字・小文字・数字混在のランダム文字列を生成する。例（PowerShell）：
  ```
  -join ((48..57)+(65..90)+(97..122) | Get-Random -Count 24 | ForEach-Object {[char]$_})
  ```
  記号は`DATABASE_URL`がURI形式（`postgres://user:password@host:port/db`）のため、
  `@`・`:`・`/`等URIの区切り文字と衝突する記号は避ける（英数字のみにするのが安全）。
- **設定**：PostgreSQLスーパーユーザーで`ALTER ROLE ja_app WITH PASSWORD '<生成値>';`を実行し、
  同じ値で本番`.env`の`DATABASE_URL`を更新する。
- **保管**：本番`.env`のみ。PostgreSQL側はロールのパスワードハッシュとして`pg_authid`に
  保持されるため別途の保管は不要。
- **ローテーション**：定期ローテーションの要求は無いが、以下のタイミングでは必ず変更する。
  - DB接続情報を知る運用担当者の異動・離任時
  - 漏洩の疑いが生じた時

  変更手順は「`ALTER ROLE`でDB側を変更→`.env`更新→Webプロセス・定期バッチ双方を再起動」の順。
  旧パスワードでの接続は`ALTER ROLE`実行直後から失敗するため、`.env`更新〜再起動までの間は
  新規接続が失敗する短時間のダウンタイムが発生する前提でメンテナンス時間帯に実施する。

### GOOGLE_APPLICATION_CREDENTIALS（GCP Cloud Visionサービスアカウント鍵）

- **生成**：GCPコンソールの「IAMと管理」→「サービスアカウント」で、OCR用途専用の
  サービスアカウントを作成し、Cloud Vision APIの呼び出しに必要な最小限のロールのみ付与する
  （プロジェクト全体への編集権限等、過剰な権限を持たせない）。当該サービスアカウントの
  「鍵」タブから新しい鍵を作成し、JSON形式でダウンロードする。
- **保管**：ダウンロードしたJSONファイルは`MEDIA_ROOT`／`LOG_DIR`と同様にコード領域
  （`ja_pj`）と分離した場所に置く（`.env.example`記載例：`C:\ja_system\secrets\gcp-vision-key.json`）。
  NTFS権限でWebプロセス実行ユーザーのみ読み取り可に制限し、gitには絶対にコミットしない。
- **ローテーション**：GCPが推奨する鍵ローテーション（目安1年に1回）に従う。手順は
  「GCPコンソールで新しい鍵を発行→サーバーの鍵ファイルを差し替え（またはパスを新ファイルに
  変更）→`.env`の`GOOGLE_APPLICATION_CREDENTIALS`パスを更新→Webプロセス・定期バッチ双方を
  再起動→OCRが正常に動作することを確認→旧鍵をGCPコンソールで無効化・削除」の順。新旧鍵を
  一時的に並行させてから旧鍵を消す（ダウンタイムを避けるため）。

### EMAIL_HOST_PASSWORD（500エラー通知用SMTPアカウントのパスワード）

- **生成／取得**：庁内メールシステム管理者から払い出されたSMTPアカウントの認証情報を使う
  （このシステム専用にアプリケーションアカウントを新設する場合は、組織のパスワードポリシーに
  従った十分な長さ・複雑さのランダム文字列を生成する）。
- **保管**：本番`.env`のみ。
- **ローテーション**：SMTPアカウント自体の運用（庁内メールシステム側のパスワードポリシー）に
  従う。パスワード変更時は`.env`の`EMAIL_HOST_PASSWORD`を追従させ、Webプロセスを再起動する。
  このアカウントは500エラー通知専用（`ADMINS`宛のみ）のため、反映漏れによる影響は通知メールが
  送れなくなる点にとどまり、業務影響は無い。次回定期メンテナンス枠での反映で足りる。

## 9. web.config の maxAllowedContentLength と MAX_UPLOAD_SIZE_BYTES の連動（2026-09-16）

IISは`requestFiltering.maxAllowedContentLength`が未設定だと既定で約30,000,000バイト
（約28.6MB）を1リクエストボディの上限とする。一方、大容量ファイルのアップロードは
`config/settings/base.py`の`MAX_UPLOAD_SIZE_BYTES`（`.env`で設定、既定50MB）を閾値に、
これ以下のファイルは`static/js/chunk_upload.js`が分割せず単発送信する（超える場合のみ
`CHUNK_UPLOAD_CHUNK_SIZE_BYTES`単位のチャンクに分割）。IIS既定値のままだと、単発送信で
よいと判定される約28.6MB〜`MAX_UPLOAD_SIZE_BYTES`のファイルがIIS側に拒否される
（404.13）食い違いがあったため、`web.config`に`maxAllowedContentLength="62914560"`
（60MB、`MAX_UPLOAD_SIZE_BYTES`既定値52428800にmultipartオーバーヘッド分の余裕を
持たせた値）を明示追加した。

**運用上の注意**：`.env`の`MAX_UPLOAD_SIZE_BYTES`を60MB超に変更する場合は、`web.config`の
`maxAllowedContentLength`も連動して引き上げること。`.env`はgit管理外で環境ごとに値を
変えられるが、`web.config`はXMLの静的値であり`.env`を参照できないため、値の変更時は
両方を手動で揃える必要がある（反映後はIISの対象サイトを再起動 or `web.config`更新による
自動リサイクルを確認する）。

---

## 10. フェーズ5最終ゲート実行結果（2026-09-16）

RELEASE_QUALITY_WORKFLOW.md ⑦の最終ゲートを実行した結果。HEAD=`a1258ad`（ブランチ`main`）。
環境: Python 3.13.11 / Django 5.2.9 / venv `C:\Users\yamad\Claude\JA\ja_system\venv`。

**結論：ブロッカーなし。リリース可。**

**対象範囲の補足**：このリポジトリはフェーズ1〜4の修正を`main`へ直接コミットする運用のため、
テンプレート指示の`main...HEAD`は文字通りには空diffになる。代わりに、P0で取得済みの
`release_baseline.txt`（コミット`62962ea`、テスト実行時点のHEAD=`3875727`）から今回のHEAD
`a1258ad`までの差分（`git diff 62962ea..HEAD`＝フェーズ1〜4で積んだ4コミット：xlsx全行監査
フェーズ2の分類マスタ削除ブロック追加・masters/documents/contractsの品質チェック修正・
ワークフロー文書更新）を実質的な最終ゲート対象とした。

### 1. 全体テスト × ベースライン照合

`python manage.py test --verbosity=1`を実行：**1018件実行、失敗0・エラー0（OK）**。
`release_baseline.txt`の1013件から5件増（フェーズ1〜4の品質チェックで追加した回帰テスト分、
masters/tests.py・contracts/tests.pyの差分と一致）。新規に増えた失敗はゼロ。

### 2. 静的チェック

- `python manage.py makemigrations --check --dry-run` → `No changes detected`（OK）
- `python manage.py check` → `System check identified no issues (0 silenced)`（OK）
- `python manage.py check --deploy --settings=config.settings.prod` → WARNING 3件：
  - **W019**（`X_FRAME_OPTIONS`が`DENY`でない）・**W021**（`SECURE_HSTS_PRELOAD`未設定）：
    前回ゲート（7節）と同一内容で、意図的な設定として許容済み。
  - **W008**（`SECURE_SSL_REDIRECT`が`True`でない）：前回ゲート時は出ていなかった新規WARNING
    だが、コード側の問題ではない。この開発環境のローカル`.env`が`SECURE_SSL_REDIRECT=False`
    （プロキシを挟まないテスト用の値）になっているのが原因で、`config/settings/prod.py`側は
    `env.bool("SECURE_SSL_REDIRECT", default=True)`のまま変更されていない（4節の対応通り）。
    本番`.env`で明示的にFalseにしない限り本番には影響しない。

### 3. 差分全体レビュー

`git diff 62962ea..HEAD`のうちコード差分は6ファイル・約90行（contracts/api.py・
contracts/services.py・contracts/views.py・core/master_views.py・masters/views.py・
templates/masters/class_list.html。他はドキュメント・review_*.txt・xlsx_audit_*.txtのみ）と
小さく、かつ各変更はフェーズ1〜4の個別品質チェック内で`/code-review high`相当のレビュー→
修正→テスト追加まで完了済み（`review_code_masters.txt`「分類一覧の削除ボタン非活性条件が
新しいブロック条件に追随していない」＝高、`review_code_doc_contract_phase4.txt`「関連契約書の
部署スコープ外レダクションでis_deletedが漏れる」＝中、等）。本ゲートでは独立した再読み合わせを
行い、追加の問題は検出されなかった：

- `contracts/services.py`の新設`related_contract_scope_view`は`contracts/api.py`
  （`_related_contract_payload`）・`contracts/views.py`（`_related_row`）の両方から呼ばれており、
  他に個別実装が残っていないことをgrepで確認。
- `masters/views.py`の`active_category_count`アノテーションは`_group_queryset_with_counts()`に
  集約されており、`GroupListView.base_queryset`・`GroupDeleteView.get_object`（いずれも
  `scoped_get_object_or_404(_group_queryset_with_counts(), ...)`経由）の両方に反映されることを
  確認。テンプレート側の`{% if group.active_category_count == 0 and ... or ... %}`は
  Djangoテンプレートの`and`が`or`より優先される仕様に沿って意図通りの真偽になることを確認。
- `masters/views.py`の`_group_queryset_with_counts()`は`Count(..., distinct=True, filter=...)`を
  3つ（doc_count/contract_count/active_category_count）に増やしているが、既存の2つと同じく
  `distinct=True`があるため複数to-many関係のJOIN展開による重複カウントは発生しない
  （`review_code_masters.txt`で個別検証済みの内容を再確認）。

### 4. フィデリティ・スポット再確認

今回の差分は原本HTML/xlsxの新機能ではなく、xlsx全行監査フェーズ2で確定した削除ブロック条件の
追加（分類管理）と、既存の部署スコープ外レダクション（関連契約書）の漏れ修正。
`templates/masters/class_list.html`の`disabled`＋`title`属性パターンはCLAUDE.mdの既定パターンに
沿っており、原本との突き合わせが必要な新規UIは無い。

### 5. 実アプリのスモークテスト

Browser paneで`runserver`（`django-dev`構成）を起動し確認。**コンソールエラー・テンプレート
構文の生表示・500は一件も発生せず**：

- ログイン（職員番号1・菅理太郎）→ メイン画面表示を確認
- `/masters/class/`（分類管理一覧、今回の主な変更screen）：4件とも削除ボタンがdisabledで、
  ツールチップが新しい文言「紐づく書類または配下のカテゴリーがあるため削除できません
  （いずれも0件のときのみ削除可）」で表示されることを確認（seed_test_dataには
  active_category_count==0かつdoc/contract_count==0の分類が無いため、削除ボタンが活性化する
  ケースは今回のブラウザ確認では再現できず、そちらは上記ユニットテスト3件
  ＜test_class_list_delete_button_disabled_reflects_active_category_block等＞でロジック検証済み）
- `/contracts/search/`→検索→詳細ポップアップを開き、`related_contract_scope_view`経由に
  変わった`/contracts/api/1/`が200を返し表示も正常であることを確認
- `/healthz/` → `200 OK` `{"status": "ok", "database": "ok"}`

### 6. 総合判断

**ブロッカーなし。リリース可。** 本ゲートで新規に検出した問題は無し。

引き続き以下は本ゲートのスコープ外として未解決のまま残っている（本ファイル1〜6と同一）：
static/js minify・本番初期マスタ投入手段・定期バッチのsettings module未指定・
`SECURE_PROXY_SSL_HEADER`関連の本番`.env`設定・CSV初期パスワードの初回強制変更・
監査ログ表記ゆれ。
