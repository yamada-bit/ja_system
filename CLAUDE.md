# CLAUDE.md

このファイルは、このリポジトリでコードを扱う Claude Code (claude.ai/code) 向けのガイダンスです。

## プロジェクト概要

JAふくおか八女向け「クラウド文書管理システム」。**画面構成・項目・挙動の一次情報源は
原本HTML（`../../HTML/html6/index.html`＋`style.css`、34画面を1ファイルにまとめた単一HTML）と
簡易設計指示書（`../../HTML/文書管理システム_簡易設計指示書_Rev1_5.xlsx`）そのもの**。この原本を基に
3陣構成（第一陣：検索・保管画面／第二陣：設定画面〈職員マスタ〜権限管理〉／第三陣：設定画面〈分類
マスタ〜その他設定〉）で作り直し、実装・原本フィデリティ監査・フェーズ8（全陣完了後の横断整合性
チェック）まで完了済み。

改訂履歴（原本HTML html1→html6、指示書 Rev1.0→Rev1.5）の各差分と反映経緯は
[HTML_REIMPL_CHECKLIST.md](HTML_REIMPL_CHECKLIST.md)「実装状況サマリ」および
`HTML_REIMPL_CHECKLIST_ARCHIVE.md`（Rev1.4=2026-08-28以降）／`HTML_REIMPL_CHECKLIST_ARCHIVE2.md`
（Phase 0〜8・Rev1.1〜1.3期）に反映節あり。新しい原本改訂を受け取ったら下記「原本改訂を受け取った
時の手順」に従う（追記先は ARCHIVE.md）。

旧実装（`../ja_pj_old/`）は参照専用。画面構成・機能範囲・命名は一切引きずらないこと。

### 技術スタック

- Python 3.13 / Django 5.2（`config/settings/base.py,dev.py,prod.py`）
- PostgreSQL（`ja_db`、`Japanese_Japan.utf8`ロケールでpg_trgmが日本語トライグラムに対応。
  `django.contrib.postgres`のGinIndexでフリーワード全文検索）
- 全文検索の本文抽出：`documents.Document`/`contracts.Contract.extracted_text`に、登録直後の
  同期テキスト層抽出（`core.text_extraction_services`、pdfplumber、外部通信なし）→対象外
  だったレコード（スキャン文書等）は5分間隔の定期バッチ（`core.management.commands.
  extract_pending_pdf_text`）でOCR（`core.ocr_services`、Google Cloud Vision
  `document_text_detection`）、の2段階で反映する。OCRはPDFをpdf2imageでページごとに画像化して
  1ページずつ投入する方式で固定しており、ページ数の上限は無い。`settings.OCR_ENABLED`
  （既定True）でOCR自体の無効化が可能（GOOGLE_APPLICATION_CREDENTIALS未設定の環境でも、
  バッチはOCR呼び出し失敗を1件ずつ捕捉してログに残すのみで停止しない）。poppler
  （pdf2imageの依存バイナリ）はリポジトリに含まないため、OS PATHが通っていない環境では
  `.env`の`POPPLER_PATH`で指定する。
- 認証はDjangoカスタムユーザー（`accounts.Employee`、`employee_no`でログイン、Argon2ハッシュ）
- フロントエンドはDjangoテンプレート＋素のJS（`static/js/common.js`、フレームワーク不使用）。
  原本HTMLのJS挙動（`popup-select`/`popup-detail`のドラッグ・リサイズ、各種トグル等）を
  `base.html`＋`common.js`に集約して全画面で共有している。唯一の例外はPDFプレビュー描画で、
  PDF.js（`static/vendor/pdfjs`、CDN不使用の自己ホスト、`static/js/pdf-preview.js`が制御。
  `settings.PDF_JS_PREVIEW_ENABLED`で旧`<iframe>`方式へ戻せる。2026-08-31ユーザー依頼）を使う
- REST API等は無し（画面内AJAX専用の`api.py`が`JsonResponse`を直接返す、DRF不使用）

### ディレクトリ構成（8アプリ）

- `accounts`: 職員マスタ・ログイン（`Employee`, `Rank`, `Position`）
- `organizations`: 部署マスタ・メイン画面項目設定・閲覧部署範囲（`Department`, `MenuItemSetting`,
  `DepartmentViewScope`）
- `masters`: 分類・カテゴリー・保存期間設定・システム設定（`Group`, `Category`, `RetentionPeriod`,
  `SystemSetting`。「設定ファイル等で容易に変更」系の値〈お知らせしきい値・契約書保存期限・「永年」
  実年数・操作履歴ログ保存期間〉は順次`.env`経由の`settings`へ移行済みで、`SystemSetting`の実使用は
  `session_idle_timeout_minutes`のみ）
- `documents` / `contracts`: 文書・契約書の検索・保管・編集・削除（ほぼ並行した構成。契約書は
  保存期間が選択式ではなく`settings.CONTRACT_RETENTION_YEARS`〈`.env`、既定10年〉で固定年数）
- `permissions`: 権限管理（`PermissionProfile`、システム権限は管理者/所属長/一般の3段階）
- `audit`: 操作履歴ログ（`AuditLog`、非正規化スナップショットで記録。保存期間
  `settings.AUDIT_LOG_RETENTION_MONTHS`〈`.env`、既定3ヵ月、xlsx 操作履歴ログ!B51-52〉より古い
  ログは一覧・CSV出力から除外し、日次バッチ`core.management.commands.purge_expired_audit_logs`で
  物理削除）
- `core`: 共通基盤（メイン画面・設定メニュー・その他設定・二重送信対策・お知らせ集計・
  popup-select/detail用API基底クラス）

各アプリ内のファイル役割分担は下記コーディング規約を参照。

### 主なURL

- `/accounts/login/`, `/accounts/staff/`〜（職員マスタ）
- `/organizations/`〜（部署管理）
- `/masters/class/`〜（分類管理）, `/masters/cat/`〜（カテゴリー管理）, `/masters/retention/`〜（保存期間設定）
- `/documents/search/`, `/documents/upload/step1/`〜（文書）
- `/contracts/search/`, `/contracts/upload/step1/`〜（契約書）
- `/permissions/`〜（権限管理）
- `/audit/`（操作履歴ログ）
- `/`（メイン画面）, `/settings/`〜（設定メニュー・その他設定)
- `/healthz/`（死活監視用、ログイン不要。原本HTML/xlsxには無い運用インフラ向けエンドポイント。
  詳細はHTML_REIMPL_CHECKLIST_ARCHIVE2.md「運用面の未実装改善候補の棚卸し・実装（2026-08-12）」参照）

### 既知の未実装・保留事項

xlsx側の「要再確認（赤字）」箇所や資料不足、業務要件未確定により、以下は未実装または保留のまま:

- 電子決裁の3権限フラグ（`eapproval_view_setting`/`eapproval_doc_name_manage`/
  `eapproval_retention`）の連動ロジック（xlsx 権限管理!B211-215「※保留」のまま。電子決裁機能
  自体が恒久的にスコープ外のため、フラグの保持のみで連動先が無い）
- 電子決裁機能全般（検索・閲覧・保管の実画面が原本HTML/xlsxのいずれにも存在しない。
  権限管理・保存期間設定マスタにのみ関連項目があるが恒久的にスコープ外）

論理削除した文書・契約書の**復元機能は「不要」で最終確定**（2026-08-24、UI・ビュー・API等とも
実装しない。詳細は`doc/文書管理システム_残項目_本番リリース手順書.xlsx`②、
`doc/文書管理システム_実装と原本の差異一覧.xlsx`「5_未実装_保留事項」No.5、ARCHIVE.md
「論理削除した文書・契約書の復元機能：不要と最終確定」参照）。ゴミ箱保管中（`is_deleted=True`）の
レコードは、削除から`settings.NOTICE_DELETED_THRESHOLD_MONTHS`（既定1ヶ月）経過後に日次バッチ
`core.management.commands.purge_expired_deleted_records`で完全削除される以外、元に戻す・個別に
完全削除する手段は無い（Rev1.2で個別完全削除ボタンは廃止済み）。

新たに要再確認事項の解消やユーザーからの仕様確定があった場合は、このセクションと
`HTML_REIMPL_CHECKLIST.md`の該当箇所を更新すること。

## コーディング規約

- **ビューはCBVのみ**。関数ベースビューは追加しない。
- **モデルの `verbose_name` / `help_text` / エラーメッセージ / docstring は日本語**で統一する。
- **設定は `config/settings/base.py` に集約**し、環境差分のみ `dev.py` / `prod.py` に書く。
  新しい設定値は `django-environ` 経由（`env(...)` / `env.bool(...)` / `env.int(...)`）で
  `.env` から読み込めるようにし、`.env.example` にも追記する。
- **アップロードファイル本体はコードと分離**して配置する（`MEDIA_ROOT` をコードの再配置・
  再デプロイの影響を受けない場所にする）。
- **パスワードハッシュは Argon2 優先**（`PASSWORD_HASHERS` の並び順を変更しない）。
- 監査が必要なイベント（ログイン/ログアウト、権限に関わる操作等）は一元的な記録機構
  （`audit`アプリ）を通す。「権限に関わる操作」のうち**成功した操作**と**他部署リソースへの
  URL直打ちアクセス試行**（`audit.services.log_denied_cross_department_access`）は`AuditLog`
  （操作履歴ログ画面・CSV出力の対象）へ記録する。一方、権限不足の保存・削除操作の拒否や
  フォーム改ざんによる不正pk混入・pks改ざん検出は`logger.warning`止まりとし`AuditLog`には
  残さない（操作履歴ログはエンドユーザー向け画面のためノイズを避ける。2026-09-09ユーザー確定、
  `review_rule_doc_contract.txt` No.1）。masters（分類・カテゴリー）の部署スコープ外直打ちは
  管理者用画面のため`logger.warning`のみ。
- 共通処理は `core` 相当の共通基底クラス・サービス関数に集約し、アプリ間で重複するロジックを
  増やさない。
- **コメントは「なぜ」を詳しく書く**。何をしているかはコード自体で分かるようにした上で、
  非自明な設計判断、他の似た実装との違い、既知の制約・将来の注意点を書き残す。クラス・
  非自明なメソッドにはdocstringを付ける。
- **ログを整備する**。新しいモジュールでは `logger = logging.getLogger(__name__)` を用意し、
  権限拒否・想定外の分岐・セキュリティ上意味のある事象は `logger.warning` で記録する。
  ログ出力先は設定ファイルの `LOGGING` 設定に一元化する。
  `logger` を用意する対象は「リクエスト処理・I/O・権限判定・失敗しうる分岐を持つモジュール」
  （`views.py`／`api.py`／`services.py`／`mixins`／`clean` 系を持つ `forms.py`／management
  コマンド 等）に限る。純粋な値変換ユーティリティ、モデル定義のみの `models.py`、記録すべき
  事象を持たない単純な `forms.py` は `logger` 宣言不要。宣言だけあって未使用の状態も、将来の
  ログ追加を見越したものとして許容する（規約準拠監査 R4/R9/R13/R20/R21 の整理）。
- **例外処理を完成させる**。ファイルI/O・外部境界（ストレージ、DBの制約違反等）は
  try/exceptで具体的な例外型を捕捉し、`logger.exception(...)` で原因を記録した上で、
  利用者にわかるエラー応答を返す。bare `except:` は使わない。「本質的でない処理の失敗で
  本処理まで巻き込まない」という設計判断が有効な場合は失敗を握りつぶして良いが、その場合は
  必ずコメントで理由を明記する。
- **一覧画面のページネーションはDjango Paginator**で実装する。機能しないボタンで利用者に
  誤解を与えるため、実装が伴わない限り静的ページャーは追加しない（xlsxが明示的に「ページャー
  不要」としている画面〈部署管理一覧等〉は例外）。
- **未実装・対象外の機能をUIに残す場合は`disabled`＋`title`属性で理由を明示する**
  （`<button disabled title="...">`のパターン。`alert()`で誤魔化す実装はしない。ただし原本の
  alert()自体が最終仕様として機能している箇所〈設定メニューの電子決裁管理・通知管理等〉は
  そのまま踏襲する）。
- 各アプリ内のファイル役割分担パターン：
  `models.py`（モデル定義）／`views.py`（CBV）／`api.py`（画面内AJAX用、`JsonResponse`直返し、
  DRF不使用）／`services.py`（ビューから分離したビジネスロジック）／`storage_paths.py`
  （アップロードファイルの保存パス生成）／`validators.py`／`forms.py`／
  `urls.py`・`admin.py`・`apps.py`（標準構成ファイル）。
  `core` の共有基底ビューは主題別に分割した `*_views.py`（`master_views.py`／`record_views.py`／
  `bulk_edit_views.py`／`upload_views.py`）へ置く（`core/views.py` に全部入れない。
  規約準拠監査 R23）。
- **新機能追加時は同様の観点でユニットテストを追加**する（`tests.py`、`python manage.py test`。
  実行時は`ja_system/ja_pj`をカレントディレクトリにすること。テストDB作成に
  `permission denied to create database`が出た場合はDBユーザーにCREATEDB権限が無いため、
  postgresスーパーユーザーで`ALTER ROLE <user> CREATEDB;`を実行する）。

## 原本フィデリティに関する運用方針

### 基本方針
- 「原本HTMLに100%一致で実装する」が基本方針だが、**原本のJS自体がモックとして壊れている
  （存在しないDOM要素を参照して例外を投げる、コピペ2重定義でデッドコードになっている等）箇所は
  文字通り再現しない**（過去に複数回この判断を下している）。
- パスワード等の機微情報は、原本が平文表示・プリフィルしていてもハッシュ化必須の規約を優先し
  マスク表示（`●●●●●●`）にする（ログイン画面・職員マスタ詳細/編集で一貫）。その他設定の
  パスワード変更は「変更後＝現在と同一ならエラー」の検証を`core.forms.OtherPassForm`に維持。
- 原本CSS未定義のクラス（例: `.system-name`）でも、原本が複数画面で一貫して使っている場合は
  タイポと決めつけず原本通りに実装する。逆に単発の欠落は都度判断し、ユーザーに確認する。
- **xlsxのセル文言diffは「何が変わったか」の手がかりに過ぎない**。実装の要否・粒度は必ず
  原本HTML（実際にレンダリングされるマークアップ・JS）と突き合わせて判断し、原本が実装していない
  動的制御を勝手に追加しない。
- 1つのHTML画面が複数モード（文書/契約書等）で共有されている場合、静的マークアップだけでなく
  JSのモード切替関数（`transitionToStorage()`等）まで確認する。
- xlsx/HTMLに仕様記載の無い危険な業務ロジックは、無断で憶測実装しない。UIのみ原本通り再現し、
  実行時はバリデーションエラーで案内する（※部署統合・分割の実処理はRev1.1で仕様が確定し
  `organizations/services.py apply_dept_action`で実装済み＝この例外ではない。Rev1.5 B215-219で
  更新前の対象部署名入り確認メッセージも追加）。
- ユーザーが明示的に「原本にはないが」と前置きして機能追加を依頼した場合は、原本一致より
  ユーザー指示を優先する。実装の詳細経緯（対象ファイル・関数名・設計判断の理由）は
  `HTML_REIMPL_CHECKLIST_ARCHIVE.md`の該当セクションに記録する（実プレビュー化・チャンク分割
  アップロード・OCR全文検索抽出・保管画面２のファイルごと個別メタデータ入力・PDFプレビューの
  PDF.js化 など。詳細はアーカイブ内の各節を参照）。
- ユーザー指示で意図的に見送った原本との差異（確認ダイアログの有無、文言の細かな違い等）は、
  実装せず理由付きで`HTML_REIMPL_CHECKLIST_ARCHIVE.md`に記録する（例：Rev1.5/html6で原本が削除した
  職員マスタ編集の目玉アイコン👁️は入力確認UXを優先してja_pjでは保持。ARCHIVE「H-3」節・
  差異一覧xlsxシート4参照）。

### 原本改訂を受け取った時の手順
1. Claudeに全文再監査させる前に、まず`diff`で機械的に差分を特定する。
2. 差分はテキスト文言だけとは限らない。xlsxのセルに**埋め込み画像のみ**で変更が示される
   ケースがあるため、画像もハッシュ突き合わせ＋目視確認する。
3. 差分を画面固有／共通部分（`common.js`等）のどちらかに振り分け、該当箇所のみ確認する。
4. 詳細な反映経緯は`HTML_REIMPL_CHECKLIST_ARCHIVE.md`に記録し、`HTML_REIMPL_CHECKLIST.md`の
   「実装状況サマリ」も1行で更新する。

### 同一注記が複数箇所に繰り返し付いている場合
xlsx/HTML上で同一の注記（「※〜の場合、ボタンを非表示とする」等）が複数のボタン・複数の
画面に繰り返し付いている場合、1箇所直して終わりにせず、該当箇所を1つずつ個別に開いて
実装済みか確認する（2026-08-24、検索結果詳細ポップアップのダウンロード/変更/削除3ボタンの
うち一部だけ「非表示」対応が漏れていた実例）。あわせて、以下の2点も併せて確認する：
- **同じ「非表示」要件でも実装方式（`style.display`か`disabled`か）が揃っているか**。
  片方のボタンで「disabled→非表示」への変更経緯があっても、隣のボタンに後から同種の要件が
  追加された際、その変更が横展開されず古い方式（disabled）のまま残ることがある。
- **ボタンの表示/非表示（クライアント側・APIのURL生成）と、そのボタンが叩くエンドポイントの
  サーバー側権限チェックは別物**。「delete_urlがNoneになる」ことは「DeleteView.post等が
  権限を検証している」ことを保証しない。URL直打ちを想定してサーバー側も確認する。

詳細な経緯は`HTML_REIMPL_CHECKLIST_ARCHIVE2.md`「検索結果詳細ポップアップ：ダウンロードボタンの
削除済み非表示漏れを修正」以降の3つの追記セクション参照。

### 技術的な既知の落とし穴
- Djangoテンプレートの複数行コメント`{# ... #}`は`.`が改行にマッチしないためコメントとして
  機能せず、生テキストが画面に表示される（同じ場所で複数回再発した既知の罠）。複数行コメントは
  `{% comment %}...{% endcomment %}`を使うこと。
