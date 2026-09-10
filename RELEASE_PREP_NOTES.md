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
