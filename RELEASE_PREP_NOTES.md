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
