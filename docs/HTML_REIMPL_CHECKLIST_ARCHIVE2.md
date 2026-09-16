# HTML確定版への作り直し チェックリスト（アーカイブ2：Phase 0〜8・Rev1.1〜1.3期の詳細記録）

このファイルは[HTML_REIMPL_CHECKLIST_ARCHIVE.md](HTML_REIMPL_CHECKLIST_ARCHIVE.md)から、
初期（2026-08-07〜2026-08-28直前、Phase 0〜8の作り直し・原本フィデリティ監査・簡易設計指示書
Rev1.1〜Rev1.3改訂の反映まで）の記録を2026-09-07に切り出したものである（ARCHIVE.mdが3376行まで
肥大化し全文読みが高コストになったため。分割方針は[[feedback_html_checklist_archive_split]]）。

**新規セッションが通常参照すべきはHTML_REIMPL_CHECKLIST.mdのみ**。このアーカイブ2は、Phase 0〜8や
Rev1.1〜1.3期の特定の過去判断・バグ修正の詳しい経緯を掘り下げたい時にのみ参照する。
Rev1.4改訂の反映（2026-08-28）〜2026-09-03頃の記録は
[HTML_REIMPL_CHECKLIST_ARCHIVE3.md](HTML_REIMPL_CHECKLIST_ARCHIVE3.md)、
Rev1.5（html5→html6、2026-09-04）以降の記録は
[HTML_REIMPL_CHECKLIST_ARCHIVE.md](HTML_REIMPL_CHECKLIST_ARCHIVE.md)にある
（2026-09-16、ARCHIVE.mdの肥大化に伴い再分割）。

（2026-09-17注記：本文中の「旧実装」は執筆当時のまま残している。原則は削除済みの前身システム
（別リポジトリだった旧ja_pj_old）を指すが、一部（例: 1868行目付近）は本プロジェクト自身の
当時より前のリビジョンを指しており、前後の文脈で判別する必要がある。旧ja_pj_old削除に伴う
用語整理はCLAUDE.mdのコーディング規約を参照。）

一般化済みの運用ルールはCLAUDE.md「原本フィデリティに関する運用方針」に集約済み。

---

## 受領状況（2026-08-07）
- `HTML/html1/index.html`（+`style.css`）：36画面分を1ファイルにまとめた単一HTML（JSで`screen-*`を切替、demo4/5と同方式）
- `HTML/文書管理システム_簡易設計指示書_Rev1_0.xlsx`：表紙・目次・ひな形を除き14画面分のシート
- **3陣すべてが同時に届いた**（当初は段階配信の想定だったため、下記「全体方針」を見直し済み）
- 赤フォント＝要再確認箇所が全27件あり。内訳と対応方針は本ファイル末尾の「要再確認（赤字）箇所リスト」を参照

## 全体方針（3陣同時受領を踏まえた見直し、2026-08-07）
当初は「3陣が段階的に別々に届く」前提で、各陣ごとに参照先（カテゴリー/部署/権限/職員）を
暫定実装→後続陣で確定、という手順にしていたが、**実際は全陣が同時に届いたため暫定実装は不要**。
- 棚卸し（フェーズ1）は36画面すべてを対象に一括で実施
- データモデル設計（フェーズ2）も全アプリ横断で一括確定（暫定実装なし）
- **実装着手の順序**は元の3陣の順を踏襲：第一陣（検索・保管）→第二陣（職員マスタ〜権限管理）→第三陣（分類マスタ〜その他設定）
- 赤字27箇所は実装を止めず、変更されやすい前提で疎結合に作り、棚卸し表とチェックリスト末尾でトラッキングする

## フェーズ0: 受領時の初動確認 【完了 2026-08-07】
- [x] HTMLが仕様確定版であることを確認（Rev1.0／2026-08-07新規作成／担当:原田(TNW)。赤字27箇所は要再確認として別管理）
- [x] 全画面が対象範囲に含まれることを確認（目次で3陣すべて確認済み）
- [x] demo4/demo5と比較（参考情報）：構造は同じ単一HTML＋JS切替方式。新HTMLでは職員/部署/分類/カテゴリーに「登録」画面が新設、保存期間設定のフローが再構成、メイン画面項目設定に一覧・ページャが追加、等の差分あり

## フェーズ1: 全画面棚卸し（全陣横断・一括） 【完了 2026-08-07】
- [x] 36画面すべてをHTMLから分割 → 実際に`class="screen"`を持つ独立画面は**33**（`screen-retention-delete-doc`／`screen-retention-delete-doc-txt`／`screen-other-main-pager`の3つは独立画面ではなく親画面内部の要素IDと判明。下記「構造上の注意」参照）。分割ファイルは`HTML/html1/screens/`配下
- [x] 棚卸し表を作成 → 3ファイルに分割して作成済み：
  - [SCREENS_INVENTORY_WAVE1.md](SCREENS_INVENTORY_WAVE1.md)（共通:login/menu + 第一陣:storage1/storage2/search）
  - [SCREENS_INVENTORY_WAVE2.md](SCREENS_INVENTORY_WAVE2.md)（第二陣:設定メニュー〜権限管理）
  - [SCREENS_INVENTORY_WAVE3.md](SCREENS_INVENTORY_WAVE3.md)（第三陣:分類管理〜その他設定）
  - 上記棚卸し表を基にした手動確認用テストチェックリストを2026-08-17作成。当初Markdown版として
    作成したが、既存の第一陣分`文書管理システム_テストチェックリスト.xlsx`との形式統一のため
    Excel版に一本化し、Markdown版（TEST_CHECKLIST_WAVE2.md/WAVE3.md）は削除済み：
    `C:\Users\yamad\Claude\JA\doc\文書管理システム_テストチェックリスト_第二陣.xlsx`（第二陣）、
    `C:\Users\yamad\Claude\JA\doc\文書管理システム_テストチェックリスト_第三陣.xlsx`（第三陣）。
    要再確認箇所との切り分け方は各ファイルの表紙シートを参照
- [x] 簡易設計指示書(xlsx)の該当シートの補足説明を棚卸し表に反映
- [x] 画面間の遷移関係を記録

### 構造上の注意（フェーズ1で判明）
- `screen-retention-delete-doc`＝`screen-retention-delete`内の`<tr>`（電子決裁選択時のみ表示）
- `screen-retention-delete-doc-txt`＝同`<tr>`内の`<td>`
- `screen-other-main-pager`＝`screen-other-main`内のページャー`<div>`
- いずれも独立画面として実装しないこと（親画面のテンプレート内の一部として実装する）

### プロトタイプHTML側の不具合・デッドコード一覧（棚卸し中に発見、xlsx記載なし）
実装方針は要判断。いずれもJSモック特有の配線ミスであり、Djangoで実装する実処理には引き継がれない見込みだが、念のため一覧化。
- `screen-dept-edit`：div開閉タグが不整合（余分な`</div>`が1つ）
- 孤立JS関数`masterDatailChange()`：存在しない要素`master-detail-buka`を参照、どこからも呼ばれていない
- `screen-authority-list`のサンプルデータに権限コード"DX"があるが、xlsx定義の管理者/所属長/一般のいずれとも一致しない
- `showModal()`が参照する`modal-text`要素が存在せずJSエラーになる
- `setupStorageFormForActiveDoc()`が2重定義されており、片方は存在しない`storage-group`を参照
- `screen-cat-edit`の「更新」ボタンが`confirmUpdate`ではなく`confirmInsert('screen-cat-list')`を呼んでいる
- 未使用のデッドコード：`onEnterOtherSettingsForRadio()`（構文誤り`disp;ay`あり）、`docAndAppJudge()`（空関数）、`confirmCatUpdate()`/`confirmCatDelete()`
- `onEnterOtherSettings()`が参照する`tab-main-items`要素がHTML全体に存在しない（nullガード済みのため実害なし）

## フェーズ2: データモデル設計（全陣横断・一括） 【完了 2026-08-07】
- [x] Djangoプロジェクト骨格を作成（`config/settings/base.py,dev.py,prod.py`、8アプリ: accounts/organizations/masters/documents/contracts/permissions/audit/core、`manage.py check`エラー無し）
- [x] 棚卸し結果を基に、対象アプリのモデルを一括設計・実装（`makemigrations --dry-run`で全モデルの整合性を確認済み、DB未接続のため実際のマイグレーションファイルはまだ生成していない）
- [x] モデル名・フィールド名はHTML側の表記に合わせる
- [x] 権限管理まわり（要再確認16件、No.2〜17）は、`permissions.PermissionProfile`にHTML通りのフラグをそのままフィールド化し、フラグの意味を解釈するロジックは今後`permissions/services.py`に集約する方針（モデル自体は要再確認箇所の解決有無に影響されない設計）

### 実装したモデル一覧
- `accounts.Employee`（カスタムユーザー、`employee_no`ログイン。PermissionsMixin不使用＝`masters.Group`との名称混同回避と、認可は全てPermissionProfileに一元化する意図）
- `organizations.Department`（本支所+部課の組み合わせを1テーブルで管理）、`organizations.MenuItemSetting`
- `masters.Group`（分類）、`masters.Category`（カテゴリー）、`masters.RetentionPeriod`（保存期間、文書/電子決裁両対応）、`masters.SystemSetting`（シングルトン設定）
- `permissions.PermissionProfile`（職員1名1レコード、文書/契約書各8フラグ+分類表示範囲M2M、電子決裁3フラグは保留扱い）
- `documents.Document`（`extracted_text`+GinIndexを追加済み、フリーワード全文検索対応。OCR自体は未実装、フェーズ4以降で検討）
- `contracts.Contract`、`contracts.RelatedFile`（契約書は保存期間FKを持たずSystemSetting.contract_retention_yearsで固定10年計算）
- `audit.AuditLog`（職員番号/部署名/職員名は非正規化スナップショットで保存）
- `core`: モデル無し（共通基盤はフェーズ4以降でservices/views等に実装）

### 電子決裁について
権限フラグ・保存期間設定マスタにのみ存在し、実際の電子決裁画面はHTML上に存在しない（設定メニューの「電子決裁管理」ボタンはalertのみ）ため、電子決裁専用モデル・アプリは作成していない。

## フェーズ3: マイグレーション・データ保管 【完了 2026-08-07】
- [x] 全モデル確定後にマイグレーション作成・適用（`ja_db`、8アプリ+core.0001_enable_pg_trgm、全件OK）
- [x] ファイルアップロード関連の保存先パス設計：`documents/storage_paths.py`の`document_upload_path`、
  `contracts/storage_paths.py`の`contract_upload_path`/`related_file_upload_path`を実装。
  `{年}/{本支所コード}-{部課コード}/{カテゴリーコード}/{UUID}_{元ファイル名}`の階層で保存し、
  UUID付与で同名ファイルの上書き事故を防止。HTML/xlsxに保存先構成の指定は無いためバックエンド側の
  裁量で設計（`manage.py check`エラー無し、マイグレーション適用済み）。

### DB基盤（2026-08-07、ユーザー指示により本フェーズで前倒し実施）
- **フリーワード検索の解釈を確定**：screen-searchの「フリーワード」入力はファイル本文に対する
  全文検索も行う仕様として採用（ユーザー指示）。`documents.Document`/`contracts.Contract`に
  `extracted_text`（抽出本文）フィールドと`GinIndex(gin_trgm_ops)`を追加済み。実際の本文抽出処理
  （PDF等からのテキスト抽出）自体はフェーズ4以降で実装する。
- **DB名の整理**：旧`ja_db`/`ja_app`を`ja_db_old`/`ja_app_old`にリネーム（旧実装の`.env`更新済み、
  旧実装側は接続確認済み）。新実装は`ja_db`/`ja_app`を新規作成して使用。
- **pg_trgmの日本語対応を修正**：旧`ja_db`は`LC_CTYPE=C`のためpg_trgmが日本語トライグラムを
  生成できない既知の問題があった（旧CLAUDE.md記載）。新`ja_db`は`Japanese_Japan.utf8`ロケール
  （LC_CTYPE/LC_COLLATE）で作成し、日本語での`similarity()`・トライグラム生成が実際に機能することを
  psql・Django両方で検証済み（例: `similarity('文書管理システム','文書管理')` → `0.4`）。
  ※ICUロケール(`LOCALE_PROVIDER icu`)だけではLC_CTYPEは変わらず`C`のままで解決しない点に注意
  （試行錯誤の過程で判明。pg_trgmの文字種別判定はLC_CTYPE依存でICUの管轄外）。
- `ja_pj/.env`・`.env.example`を新規作成、`DATABASE_URL`は`ja_db`/`ja_app`を指す。

## フェーズ4〜7: 機能実装（着手順序は第一陣→第二陣→第三陣、各陣内は検索閲覧→登録編集→管理画面）

### 第一陣：検索・保管画面 【初期実装・動作検証完了 2026-08-07、フィデリティ監査・修正完了 2026-08-08】
- [x] 検索・閲覧・変更画面（documents/contracts双方、Paginator1ページ50件、AND/OR切替、フリーワード全文検索対応）
- [x] 保管画面１／２（documents/contracts双方、複数ファイル一括登録、編集画面、削除（論理削除）、ダウンロード）
- [x] 横断機能を同時組み込み：監査ログ（`audit.services.log`）・ログ整備・二重送信対策（`core.double_submit`）・Paginator。例外処理は基本形のみ（ファイルI/O周りの`try/except`は実装済み、網羅的な例外処理の見直しは今後の課題）
- [x] 画面ごとにHTML原本と突き合わせ検証【2026-08-07実施】。DOM構造・CSSクラス単位での突き合わせを実施し、多数の構造・レイアウト差異を修正（詳細は当時のセッション記録参照）
- [x] **5系統（ログイン+メニュー／保管画面１／保管画面２／検索画面／詳細ポップアップ+ポップアップ選択）を対象に、原本HTML/CSS/JSとDjangoテンプレートの1行単位の突き合わせ監査を再実施【2026-08-08】**。前回修正の再検証に加え、新たな差異を洗い出し・修正：
  - 保管画面１：`documents/storage1.html`のJS要素idタイプミス（`drop-zone`→`upload-drop-zone`）を修正。ドラッグ&ドロップが機能していなかった不具合を解消
  - 保管画面２：年・保存期間selectに原本の`size-short`クラス（幅90px固定）が欠落していたのを修正。有効期限リアルタイムプレビュー（`calculateExpiryDate()`、原本index.html:832-850）が未実装だったため新規実装（`RetentionPeriod`のperiod_unit/period_valueをdata属性でJSに渡す方式）。登録/更新完了画面に日時表示（`(登録日時：...)`）を追加
  - 検索画面：保存情報列の部署表記に「本店｜」等の支所プレフィックスが混入していたのを`section_name`のみに修正。保管・更新者列で部署名が欠落していたのを「部署｜氏名」形式に修正
  - 詳細ポップアップ：削除確認文言の「文書」の2文字欠落を修正
  - **重複実装の解消**：`templates/documents/detail.html`・`templates/contracts/detail.html`（対応する`DetailView`・URL名`detail`）が、検索画面から使われる実際の詳細ポップアップ実装（`base.html`+`static/js/common.js`）とは別に存在し、どこからもリンクされず内容も劣化した到達不能なコードになっていたため削除。**詳細表示は原本通りポップアップオーバーレイとして実装済み**（下記「実装上の簡略化」の記載は誤りだったため訂正）
  - 修正後、Django `manage.py check`エラー無し、ログイン→検索→詳細ポップアップ（ダブルクリック起動・削除確認文言）→保管画面２→編集画面の一連の流れをブラウザ操作＋Django test clientで実際に動作確認済み（`calculateExpiryDate()`のJS計算結果も実行して検証：1ヵ月→翌年1月末日、5年→+5年12月末日、永年→永年、いずれも原本の計算式と一致）
- [x] 要再確認No.20〜22（ダウンロード権限の表示制御）は`permissions.services.can_download`に一元化。権限プロファイル未設定の職員はダウンロード不可がデフォルト（テストで403を確認）

### 動作検証結果（Djangoテストクライアントによる実HTTPリクエスト検証）
- 文書: ログイン→保管画面１（アップロード）→保管画面２（登録）→検索→詳細→ダウンロード(403、権限未設定のため正しい拒否)まで確認
- 契約書: 上記に加えて編集（タイトル更新）・削除（論理削除）まで確認
- 保存満了日の自動計算を確認（文書: 保存期間「1ヵ月」→ +1ヶ月、契約書: 固定10年→ +10年）
- ストレージパス（`documents/{年}/{本支所}-{部課}/{カテゴリー}/{UUID}_{ファイル名}`）が設計通り生成されることを確認

### 実装上の簡略化・既知の未解決事項（2026-08-08時点）
- HTML確定版はPDFプレビュー＋ページャーで複数ファイルを1つずつ切り替えてタイトル入力する構成。本実装もページャー（`changeActiveDoc`）で原本通りファイルを切り替える構成になっている（旧記載「一覧を並べて個別入力する形に簡略化」は2026-08-08修正で解消・訂正）
- 契約書の関連書類添付は、バッチ内ファイルが1件の場合のみ対応（複数契約書一括登録時の関連書類振り分け方法がHTML/xlsxに明記が無いため）。原本には無い注意書きをUIに追加して案内している
- PDF実プレビュー（ズーム等）は原本通りモック（ファイル名表示＋ズームボタンの見た目のみ、実PDF描画は無し）として実装済み。実PDF描画自体は元プロトタイプにも存在しない機能のため対象外
  （※2026-08-08時点の記載。その後方針転換し、検索・閲覧画面「文書イメージ」欄の実ファイルプレビュー化（2026-08-10）／保管画面２・編集画面・検索/閲覧詳細ポップアップの画像/PDF実プレビュー追加（2026-08-12）で実際にPDF/画像を描画するよう変更済み。詳細は該当セクション参照）
- ~~保存満了日(expiry_date)の計算基準日の疑義は未解決~~ → **2026-08-20ユーザー確認により解決**。詳細は「保存満了日の計算基準日をユーザー確認・年欄との連動解消（2026-08-20）」セクション参照
- ブラウザの実ファイルアップロード（file input経由）は、このセッションのブラウザ自動化ツールでは検証不可のため、Djangoテストクライアントでの検証に留めた。ユーザーによるブラウザ実地確認を推奨
- テストデータが少なく（職員1名・文書3件程度）、複数部署・契約書特有項目を含む網羅的なシナリオでの実地確認はまだ行っていない

### 第二陣：設定画面（職員マスタ〜権限管理） 【実装・動作検証完了 2026-08-09】
- [x] 設定メニュー（`templates/core/settings.html`、`core.views.SettingsMenuView`）。電子決裁管理／
  通知管理／項目管理の3ボタンは原本が最終的にalert()のみを意図した設計（未実装機能の場当たり的な
  仮実装ではない）と判断し、原本のalert文言をそのまま再現。
- [x] **設定メニューのボタン表示/非表示制御を追加実装（2026-08-20ユーザー指示）**：xlsx 設定メニュー!B31
  「『権限管理』メニューで設定する"権限"によって、メニューボタン表示/非表示を制御する」の詳細は
  B46セル以降にセル値ではなく埋め込み画像として貼られており、テキストベースのセル値突き合わせでは
  見落とされていた（過去のこのセクションの「要再確認No.6,7,9,14,15,17のため未確定」という記述は、
  権限管理シート側の別の細かい追加制御と混同していたもので、この画像の表自体は○/―が全て確定済み）。
  画像を抽出し、システム権限（管理者/所属長/一般）ごとの11ボタンの表示可否を
  `permissions.services.visible_settings_menu_items`に実装、`SettingsMenuView.get_context_data`で
  テンプレートへ渡し`{% if %}`で出し分け。表側の「権限管理」行は「所属長への権限付与」
  （管理者のみ○）「職員への権限付与」（管理者/所属長○）の2行に分かれているが、
  `PermissionProfile`がこの2フラグを廃止しシステム権限プルダウン1本に統一済みのため、緩い方
  （職員への権限付与＝管理者/所属長）をボタン表示可否として採用（ユーザー確認・承認済み）。
  `core.tests.SettingsMenuVisibilityTests`で3ロール分を検証、ブラウザでも3ロールでログインし
  実際の表示ボタンが表と一致することを確認済み。
  **初回実装時に電子決裁管理行を誤読していたバグを修正（同日ユーザー指摘）**：電子決裁管理
  （「書類名作成・変更」「保存期間」の2行がマージされたセル）は管理者のみ○で所属長は―だが、
  初回実装では所属長にも○を付けてしまっていた。画像を再度ズームして全行を再確認し、
  `SETTINGS_MENU_VISIBLE_ROLES["eapproval_management"]`を`{ADMIN}`のみに修正、テストも合わせて修正。
  **サーバー側アクセス制御を追加実装（同日ユーザー指示）**：上記のボタン非表示はUI上の出し分けに
  過ぎず、`accounts.StaffListView`等の各設定画面のビュー自体には`LoginRequiredMixin`のみで
  ロール別のアクセス制御が入っておらず、URLを直接叩けば非表示のはずの画面にも到達できてしまう
  状態だった。`permissions.services.can_access_settings_menu_item()`（`visible_settings_menu_items`
  と同じ`SETTINGS_MENU_VISIBLE_ROLES`を参照し、表示側とアクセス制御側でロール判定がずれないように
  する）と、それを`dispatch()`で強制する`permissions.mixins.SettingsMenuAccessMixin`
  （`core.views.OtherMainEditView`等と同じ`PermissionDenied`(403)＋`logger.warning`パターン）を
  追加し、以下のビューに適用：`accounts.StaffListView/StaffDetailView/StaffRegistView/
  StaffEditView/StaffCsvExportView/StaffCsvImportView`（"staff_master"、管理者のみ）、
  `organizations.DeptListView/DeptRegistView/DeptEditView`（"dept_management"、管理者のみ）、
  `masters.GroupListView/GroupRegistView/GroupEditView/GroupDeleteView`（"class_management"、
  管理者/所属長）、`masters.RetentionListView/RetentionRegistView/RetentionEditView/
  RetentionDeleteView`（"retention_setting"、管理者のみ）、`audit.AuditLogListView/
  AuditLogCsvExportView`（"audit_log"、管理者のみ）、`permissions.AuthorityListView/
  AuthorityCsvExportView`（"authority_management"、管理者/所属長）。
  `masters.CategoryListView`等（カテゴリー管理）はxlsx表で全ロール○のため対象外。
  `permissions.AuthorityEditView`は既存の`can_manage_target()`が対象職員単位で一般ロールを
  含め既に弾いているため二重管理を避けて対象外。`core.OtherSettingsView`・`OtherMainEditView`・
  `OtherLogoutEditView`（その他設定配下）はB46表の粒度（画面全体の表示可否）とは別に画面内
  タブ単位のより細かい制御を既存実装が担っているため据え置き。「電子決裁管理」「通知管理」
  「項目管理」は実画面が無い`alert()`のみのモックボタンのためアクセス制御の対象外。
  既存テスト（`accounts.StaffCsvExportViewTests`等7クラス）はログインユーザーに
  `PermissionProfile`を作成しておらず（＝既定で一般ロール扱い）今回のアクセス制御でそのままでは
  403になるため、該当`setUp()`に管理者ロールの`PermissionProfile`作成を追加。新規に
  `accounts.StaffSettingsMenuAccessControlTests`、`organizations.
  DeptSettingsMenuAccessControlTests`、`masters.MasterSettingsMenuAccessControlTests`、
  `audit.AuditLogSettingsMenuAccessControlTests`、`permissions.
  AuthoritySettingsMenuAccessControlTests`を追加し、対象外ロールでの直接アクセスが403になること・
  対象ロールでは通ることを検証。ブラウザでも一般ロールで`/accounts/staff/`に直接アクセスし、
  既存の「アクセスが拒否されました」画面（`core.OtherMainEditView`等が使う共通403テンプレート）が
  表示されることを確認。`python manage.py test`で全369件パス。
- [x] 職員マスタ（一覧/詳細/登録/編集、`accounts`アプリ）。要再確認No.1「削除機能なし」を踏まえ削除機能は
  実装せず。本支所→部課の連動選択は原本の固定サンプル値ではなく`organizations.Department`の実データから
  動的生成（xlsx注記通り）。パスワードは原本のような平文表示・プリフィルをせず
  （ハッシュ化必須の規約と矛盾するため、ログイン画面と同種の必然的な逸脱）、「リセット」ボタンは
  `ja+職員番号下4桁`をその場で入力欄にセットするのみで実際の保存は更新ボタン押下時（原本と同じ2段階）。
  xlsx B228「本支所〜役職変更または退職時に権限設定をリセット」を`accounts/services.py`に実装
  （安全側に倒し全フラグFalse・役職一般にリセット）。
- [x] 部署管理（一覧/登録/編集、`organizations`アプリ）。xlsx B60「ページャー不要」を踏まえPaginatorなし。
  検索selectの選択肢は原本の空value(実装不備の静的モック)ではなく実データから生成。「部署統合・分割」UIは
  原本通り再現するが、実際のマージ・分割ロジックはxlsx/HTMLいずれにも仕様記載が無いため実装せず、
  選択時はバリデーションエラーで案内（無断で危険な業務ロジックを憶測実装しない判断）。
- [x] 権限管理（一覧/詳細/編集、`permissions`アプリ）。要再確認No.2〜17（各フラグの他画面への連動仕様）は
  未確定のため、フラグの保存のみ実装しフラグの意味を解釈する連動ロジックは実装しない
  （`permissions/services.py`に将来集約する前提）。閲覧範囲はxlsx B68-70（管理者=全件、所属長=自部署）に
  従い、記載の無い「一般」は安全側で所属長と同じ自部署のみに制限。B112「所属長は自分自身の編集不可」を実装。
  PermissionProfile未作成の職員は編集画面表示時に既定値（一般・全フラグFalse）で自動作成。
- [x] 画面ごとに検証（Django test client一往復＋ブラウザでのレンダリング・JS動作確認、詳細は下記）。
- [ ] 第一陣のダウンロード権限表示ロジックの見直しは、要再確認No.20〜22自体が本陣でも解決していない
  （xlsxに記載のフラグ自体は`permissions.services.can_download`で既に反映済み）ため対象外のまま。

### 第二陣の動作検証結果（2026-08-09）
- `manage.py check`エラー無し。
- Django test clientで各画面のGET(200)・POST（登録・更新・重複検証・二重送信対策）を一往復確認。
  職員の部署変更で権限プロファイルが正しくリセットされること、部署統合・分割の送信がエラーで
  ブロックされることも確認済み。
- ブラウザでログイン→部署管理（一覧/新規登録/編集）→職員マスタ（一覧/詳細/登録/編集、本支所→部課の
  連動選択のJS実動作を確認）→権限管理（一覧/詳細/編集、一括許可/一括無許可ボタン、分類選択ポップアップの
  API疎通）まで実際に操作し、コンソールエラー無しを確認。
- **実装中に発見したバグ**: Django複数行`{# ... #}`コメントはDjangoテンプレートエンジンの字句解析の
  制限（`.`が改行にマッチしない）によりコメントとして認識されず、画面に生のテキストとして表示される
  不具合が新規作成した2ファイル（`organizations/dept_list.html`、`accounts/staff_detail.html`）で
  発生し修正済み。複数行コメントは`{% comment %}...{% endcomment %}`を使うこと（今後の実装でも注意）。
- 設定メニュー自体は分類管理・カテゴリー管理・保存期間設定・操作履歴ログのURLを参照するため、
  第三陣実装後に改めてクリック導線を確認する。

### 第三陣：設定画面（分類マスタ〜その他設定） 【実装・動作検証完了 2026-08-09】
- [x] 分類管理（一覧/登録/編集/削除、`masters`アプリGroup）。コード重複登録・重複更新は不可
  （xlsx B119/B161）。文書件数0件の分類のみ削除可（xlsx B68、論理削除=`is_deleted`）。
  検索selectの分類名選択肢は原本の静的サンプル(分類Ａ〜Ｉ)ではなく実データから生成。
- [x] カテゴリー管理（一覧/登録/編集/削除、Category）。分類管理と同様の重複チェック・0件削除制約
  （xlsx B119/B155、B196）。カテゴリー名検索は部分一致（xlsx B36）。
- [x] 保存期間設定（一覧/登録/編集/削除、RetentionPeriod）。原本の「文書/電子決裁(稟議書/経費支出伺)の
  3tbody事前描画+ラジオ/プルダウンでJS表示切替」という構成をそのまま踏襲（サーバー側で3種類とも
  取得しテンプレートに渡す）。「永年」選択時に保存期間を空欄+readonly化するJS(`handlePermanent`)も
  原本通り実装。保存期間・表示順の重複登録は不可（xlsx B77/B191、モデルのUniqueConstraint）。
  削除はxlsx B146/B271「論理削除」の指定だが、RetentionPeriodモデルに元々is_deletedフィールドが
  無く（フェーズ2設計時点で未反映）、文書・契約書からのFK参照がある場合は物理削除するとデータ整合性が
  壊れるため、参照が無い場合のみ物理削除を許可する実装に留めた（モデル変更を伴う対応はスコープ外と判断）。
  独立画面ではない`screen-retention-delete-doc`/`-doc-txt`は棚卸し表の注記通り実装対象から除外。
- [x] 操作履歴ログ（一覧のみ、`audit`アプリAuditLog）。CSV出力ボタンは原本の
  `alert('CSV出力はデモ機能のため動作しません')`をそのまま踏襲（「動作しない」ことの開示自体が
  原本の最終意図と判断、詳細は[[feedback_ja_pj_mock_fidelity_precedent]]と同種の判断）。
- [x] その他設定（`core`アプリ）。原本はログインユーザーのデモ用固定ID(`login-user`が"2"/"3"か)で
  管理者向け(screen-other-main)か一般向け(screen-other-pass)かを振り分けるモック実装だったが、
  本実装ではその「意図」を実際の`PermissionRole`（管理者/所属長/一般）にマッピングし、
  `PermissionRole.ADMIN`かどうかで同一URL(`core:other_settings`)の表示内容を振り分ける。
  パスワード変更は現在のパスワードを平文表示せず（ハッシュ化必須の規約、ログイン画面と同種の逸脱）、
  変更後パスワードと確認用の一致検証を追加（xlsx未記載だが確認欄の目的上必須と判断）。
  メイン画面項目編集・自動ログアウト時間編集は管理者以外アクセス時403（原本には無い実アクセス制御、
  実システムとして必要な安全策として追加）。
- [x] 画面ごとに検証（Django test client一往復＋ブラウザでの実導線確認、詳細は下記）。
- [x] 要再確認No.23〜24（保管画面の完了ポップアップ画像未完成）は2026-08-21、調査誤りと判明し解消。
  詳細は本ファイル末尾「要再確認No.23〜24（保管画面完了ポップアップ画像）の調査誤り訂正
  （2026-08-21）」参照。

### 第三陣の動作検証結果（2026-08-09）
- `manage.py check`エラー無し。
- Django test clientで各画面のGET(200)・POST（登録・更新・削除・重複検証・二重送信対策）を一往復確認。
  分類/カテゴリーの文書件数0件判定、保存期間の重複表示順ブロック・永年時のクリア、その他設定の
  管理者/一般ロール別ルーティングと403ブロック、パスワード確認不一致ブロックをそれぞれ確認済み。
- ブラウザで設定メニュー→分類管理→カテゴリー管理→保存期間設定（ラジオ切替・永年JS）→操作履歴ログ→
  その他設定（タブ切替JS）まで実際にクリック・操作し、コンソールエラー無し（新規発生分）を確認。
- **実装中に発見・修正したバグ**: `templates/core/settings.html`の保存期間設定リンクが
  存在しないURL名`masters:retention_doc`を参照しており`NoReverseMatch`で設定メニュー自体が
  500エラーになっていた。正しいURL名`masters:retention_list`に修正済み。
- [x] **原本フィデリティ監査完了（2026-08-09）**: 第一陣と同様の5系統並列監査
  （設定メニュー+職員マスタ／部署管理+権限管理／分類管理+カテゴリー管理／保存期間設定／
  操作履歴ログ+その他設定）を実施し、見つかった差異をすべて修正した。
  **修正内容**:
  - 【高】職員マスタ登録・編集の職階/役職プルダウン初期値がDjango既定の「---------」に
    なっていたのを原本通り「(選択してください)」に修正
  - 【高】権限管理編集画面で「分類(作成・変更・削除)」チェックボックス（文書管理・契約書とも）が
    フォーム定義から漏れており画面に表示されず更新もできなかった不具合を修正
  - 【高】`Department.__str__`が部課の無い本支所（物流センター等）でも「｜」を付けてしまう
    表示バグを修正（区切り文字無しで本支所名のみ表示するよう修正）
  - 【中】部署管理・権限管理・分類管理・カテゴリー管理・保存期間設定（計15画面）で、
    原本が一貫して使用する`.system-name`クラス（style.css未定義）を実装が`.system-sub`に
    独自統一していた点を、ユーザー確認の上で原本通り`.system-name`に復元
  - 【中】保存期間設定一覧の「表示」ボタン欠落、削除確認画面の「No.」が一覧の表示順と
    食い違う実装（同一区分内の順位計算に修正）
  - 【中〜低】検索パネル等のselect/inputに原本の`width:150px`等のインラインstyleが
    複数画面（権限管理・分類管理・カテゴリー管理・操作履歴ログ・保存期間単位）で
    欠落していたのを追加
  - 【低】その他設定のラジオ/チェックボックスラベル、部署編集の統合分割ラジオの
    全角スペース間隔欠落を修正
  第一陣同様、原本JS自体が壊れている箇所の再現不要というprecedentの下で判断し、
  confirm()ダイアログの欠如（プロジェクト全体で一貫してサーバー側POST+メッセージ表示に
  統一する設計方針のため）等は意図的な設計として維持した。

## フェーズ8: 全陣完了後の横断整合性チェック 【完了 2026-08-09】
- [x] FK関係の最終確認: 全モデルのForeignKey/OneToOne/ManyToManyのon_delete設定を確認。
  マスタ系（Group/Category/RetentionPeriod/Department）参照は原則PROTECT（文書・契約書の
  誤った巻き添え削除防止）、詳細レコード（MenuItemSetting/RelatedFile/PermissionProfile）は
  CASCADE、という一貫した使い分けを確認。問題なし。
- [x] モデル名・フィールド名・URL命名の統一確認: 全8アプリのurls.pyを確認。
  `<画面群>_list/regist/edit/delete`という命名が一貫している（documents/contractsのみ
  `upload_step1/2`など2段階アップロード固有の命名だが、画面構成自体が異なるため妥当な差異）。
  masters内で「分類管理(HTML/URL上の呼称)」="class"、モデル名は`Group`という対応は
  フェーズ2からの既存設計（Django標準`auth.Group`との名前衝突回避、doc_visible_groups等
  既存M2Mとの整合のため）で、新規の不整合ではない。問題なし。
- [x] 共通UI要素の陣間矛盾チェック: 全テンプレートが`base.html`を正しくextendsしていること、
  「設定メニューへ戻る」ボタンが原本通りの画面にのみ存在し`core:settings`に統一されていること、
  ログアウトフォームの構成が全27画面で一貫していること、user-info欠落画面（class-regist/edit等、
  原本通り）が正しく再現されていることを確認。問題なし。
- [x] 要再確認27箇所の解消状況を最終確認: xlsxの赤字セルをopenpyxlで再カウントし27件
  （職員マスタ1、権限管理16、検索閲覧変更8→5論理項目、保管2）と一致することを確認、
  チェックリストの24論理項目に漏れが無いことを検証。**この過程で実装バグを1件発見・修正**：
  要再確認No.2「所属長は自分の権限の変更が不可」が、詳細画面の編集ボタン非表示のみで
  編集URLへの直接アクセスをサーバー側で防いでいなかったため、`AuthorityEditView.dispatch()`に
  同条件のチェックを追加（403）。No.1（職員マスタ削除機能）・No.3〜17（権限フラグ連動仕様）・
  No.19（保存期間設定データの検索画面での扱い）・No.23〜24（保管完了ポップアップ画像未完成）は
  xlsx自体が未確定としている業務仕様のため実装側では解決不可、ユーザー確認待ちのまま。
- [x] 全体テストスイート（`python manage.py test`）を実行し全件PASSを確認: 実行前は全アプリで
  テストが0件だったため、8アプリ全てに主要機能のユニットテストを新規作成（**73件、全件PASS**）。
  モデルのバリデーション・ロジック（重複コードチェック、パスワードリセット、権限プロファイル
  リセット、保存満了日計算、検索AND/OR切替等）と主要ビュー（ロール別ルーティング、
  アクセス制御403等）を中心にカバー。**テスト作成中に実装バグを1件発見・修正**：
  `masters.Group`/`masters.Category`の`UniqueConstraint(fields=["code"])`が論理削除
  (`is_deleted`)を考慮しておらず、削除済みコードを再利用登録しようとすると
  `GroupForm.clean_code()`の重複チェック（is_deleted=False行のみ対象）を通過しても
  モデル側の制約で弾かれる不整合があったため、`condition=Q(is_deleted=False)`を追加した
  マイグレーション(`masters.0002`)を作成・適用。
- [x] 棚卸し表全体の最終消込: `index.html`から抽出した独立screen div 31件（非独立の
  3要素`screen-retention-delete-doc`/`-doc-txt`/`screen-other-main-pager`を除く）全てが
  対応するURL・テンプレートとして実装済みであることを確認。

## フェーズ8後の追加改善（2026-08-09、業務仕様確認待ち以外の残項目を対応）

要再確認事項の解決を待たずに進められる項目を洗い出し、対応した。
- [x] 職員マスタCSV出力（xlsx B88-91、一覧の絞込み結果をCSV出力・パスワードは空欄）。
  CSV**取込**は取込用CSVの列レイアウト表がxlsx上に実在しない資料不足のため見送り継続
  （`disabled`+`title`で理由明示）。
- [x] 権限管理一覧CSV出力（列構成は一覧画面の表示列に準拠。列レイアウトの個別記載はxlsxに
  無いが、他画面のCSV出力方針〈一覧表示内容をそのまま出力〉と揃えた）。
- [x] 検索画面（文書・契約書）の「一括ダウンロード」をZIP一括ダウンロードとして実装
  （権限判定は要再確認No.20〜22で既に確定済みの`can_download`をそのまま利用）。
  「一括編集」は対象項目・適用範囲がHTML/xlsxいずれにも未定義のため`disabled`のまま。
- [x] メイン画面「電子決裁」ボタンの案内文言を「第二陣以降で実装予定」（誤り、全陣完了後も
  対応する画面が存在しない）から「原本に画面が存在しないためスコープ外」に訂正。
- [x] 旧`CLAUDE.md`をHTML基準の内容へ全面書き換え（プロジェクト概要・技術スタック・
  ディレクトリ構成・主なURL・既知の未実装、原本フィデリティ運用方針を追記）。
- [x] 新機能（CSV出力2件・一括ダウンロード2件）のユニットテストを追加、全体テスト**82件**PASS。
  **テスト作成中に実装バグを1件発見・修正**：`StaffSearchForm(request.GET or None)`という
  書き方が、クエリパラメータの無い初回アクセス時にフォームを未バインド扱いにし
  `is_valid()`が常にFalseを返すため、「退職者を含めない」既定フィルタが効かず退職者が
  一覧・CSV出力に混入するバグがあった。同じパターンを使っていた全10箇所
  （accounts/organizations/masters/documents/contracts/permissions/audit の一覧系ビュー）を
  `request.GET`直接バインドに統一して修正。

## レイアウト差異監査・修正（2026-08-09、原本HTMLとの表示位置・サイズの突き合わせ）

テキスト・機能面のフィデリティ監査（フェーズ8等）とは別に、原本HTMLと実装テンプレートの
**レイアウト（表示の位置・サイズ）**のみに絞った突き合わせを実施し、見つかった差異を全件修正した。
- [x] 【高】権限管理一覧の列ズレ：`templates/permissions/authority_list.html`のデータ行に
  `doc_group_manage`/`contract_group_manage`の`<td>`が抜けており、ヘッダーの`colspan="19"`に
  対して17列しか描画されず全列がズレていた（`authority_edit.html`/`authority_detail.html`は
  既に正しく実装済みだった）。該当2つの`<td>`を正しい位置に追加し、Djangoテストクライアントで
  1行あたり25個の`<td>`（sticky5＋フラグ19＋操作1）が描画されることを確認。
- [x] 【中】検索画面（文書・契約書）の条件テーブル空行：`templates/documents/search.html`/
  `templates/contracts/search.html`の右側条件テーブル先頭に、原本(`index.html:377-380`)に
  ある空の`<tr><td class="label"></td><td></td></tr>`が無く、左側テーブルと縦位置がズレていた。追加して解消。
- [x] 【中】職員マスタ一覧の検索欄スタイル：`accounts/forms.py`の`StaffSearchForm`
  （本支所・部課・氏名）に原本の`padding:4px; width:150px;`が指定されておらず既定幅で
  描画されていた。ウィジェットに`style`属性を追加。
- [x] 【中】`PopupSelectWidget`の`mode`流用問題：`mode="search"`はJS側の選択方式
  （チェックボックス複数選択）を切り替えるためのフラグだが、表示用inputのCSS幅も
  `mode`から一律導出していたため、原本で幅指定が無い/異なる箇所まで250px固定になっていた
  （部署管理の統合・分割対象選択＝原本は幅指定なし、権限管理の
  `doc_visible_groups`/`contract_visible_groups`＝原本は200px）。`display_attrs`パラメータを
  追加して個別上書きできるようにし、該当2箇所を原本通りに修正。
- [x] 【中】第三陣5画面の`system-name`クラス復元：以前のシステム名クラス統一対応
  （15画面）から`templates/audit/log_list.html`/`templates/core/other_pass.html`/
  `other_main.html`/`other_main_edit.html`/`other_logout_edit.html`の5画面が漏れており
  `system-sub`のままだった。原本（例:`index.html:3270`）通り`system-name`に統一。
- [x] 【低】保管画面2の細かいレイアウト差異：契約書の保管・編集画面で契約日行の
  `margin-top:10px`（原本の`#storage-contract-fields`ラッパーの余白相当）が無かった点、
  文書の個人情報有無ラジオが`.radio-group`のflexbox `gap:15px`ではなく
  `static/css/django_widgets.css`の汎用上書き（Django RadioSelect用、`margin-right:10px`）が
  優先されていた点を修正。あわせて、Djangoの`messages`フレームワーク用`<ul class="messages">`
  （原本に存在しない要素でCSSリセットが無く既定の黒丸装飾が出ていた）に`list-style:none`を追加。
  保管完了ポップアップ（`storage_complete.html`）のモーダル⇔ページ構造差異は、
  1URL1画面というDjangoルーティングの性質上の根本差であり、CSSのみでの部分修正は
  かえって見た目の一貫性を損なう可能性があるため見送り（既知の差異として現状維持）。
  → **2026-08-12にユーザー報告を受けて修正済み**：`documents`/`contracts`の
  `UploadStep2View.post()`/`DocumentEditView.post()`/`ContractEditView.post()`が登録・更新成功後に
  別テンプレート`storage_complete.html`へ丸ごと差し替えていたため、原本の
  「`overlay-modal`をdisplay:flexにするだけで背後のscreen-storage2は画面遷移せず残り続ける」
  という挙動と異なり、完了ポップアップの背後が空白になっていた（原本フィデリティ監査では
  「CSSのみでは直せない構造差」として見送っていたが、実際にはビュー側でGET時と同じcontextを
  使い`storage2.html`/`edit.html`をそのまま再描画し、`complete`コンテキスト変数経由で
  完了モーダル（`documents/contracts`それぞれの`_complete_modal.html`にHTMLを分離）を重ねて
  表示するだけで解決できた）。`storage_complete.html`は削除。
- [x] 検証：`manage.py check`（問題なし）、全体テストスイート**82件PASS**、

  Djangoテストクライアントで権限管理一覧の列数・検索画面の空行描画を実サーバーレスポンスで確認。

## 文言・機能面差異監査・修正（2026-08-09〜08-10）

レイアウト差異監査（上記）とは別に、原本HTMLと実装テンプレートの**文言（ラベル・ボタン・
メッセージ）と機能面（バリデーション・条件表示・確認ダイアログ等）**のみに絞った突き合わせを
7画面グループ（ログイン/メニュー/設定メニュー、保管画面1・2、検索画面/詳細ポップアップ/
ポップアップ選択、職員マスタ、部署管理/権限管理、分類/カテゴリー/保存期間設定、操作履歴ログ/
その他設定）で並列実施。高5件・中8件・低6件の差異を検出し、ユーザー指示（「高・中を修正して。
低はドキュメントに残して」）に基づき高・中の13件全件を修正、低6件は意図的に見送った。

### 修正した高優先度（5件）
- [x] 詳細ポップアップ「削除」ボタンのfetch/JSON不整合：`static/js/common.js`の
  `triggerDeleteFromDetail()`は`X-Requested-With`ヘッダー付きでJSONレスポンスを期待していたが、
  `documents/contracts`の`DeleteView.post()`は常に`redirect()`（302→200 HTML）を返しており
  `r.json()`のパースに失敗、削除自体は成功してもポップアップを閉じる・完了通知・一覧再描画の
  いずれも動作しないバグがあった。両`DeleteView`にAJAX検知時のみ`JsonResponse`を返す分岐を追加。
- [x] 監査ログがdocuments/contracts以外から一切呼ばれていない：`accounts.LoginView`/`LogoutView`、
  `core.OtherSettingsView`（パスワード変更）/`OtherMainEditView`/`OtherLogoutEditView`、
  `permissions.AuthorityEditView`、`masters`の分類・カテゴリー・保存期間設定の登録/更新/削除、
  いずれも`audit_services.log()`を呼んでおらず、原本操作履歴ログのサンプルが示す主要操作種別
  （ログイン/ログアウト/パスワード更新/権限管理更新/マスタ登録等）が実運用で一切記録されない
  状態だった。該当箇所すべてに`audit_services.log()`呼び出しを追加。
- [x] `masters`系フォームの空選択肢「---------」混入（3画面）：`GroupForm.doc_kbn`、
  `CategoryForm.doc_kbn`/`group`、`RetentionPeriodForm.period_unit`が、Django ModelFormの
  既定のblank選択肢生成により原本に無い「---------」を持ち、登録画面では未選択のまま送信すると
  必須エラーになっていた（原本は常に先頭の実選択肢が暗黙選択済み）。職階/役職プルダウンで
  以前修正した同種のバグが`masters`アプリに残っていたもの。choicesを明示指定・`empty_label=None`
  で解消。

### 修正した中優先度（8件）
- [x] 詳細ポップアップ「まもなく有効期限（更新月）」バナー未実装：`core.notice_services`に
  `is_expiring_soon()`を新設（`SystemSetting.notice_threshold_months`を流用）、
  `documents/contracts`のdetail API・`common.js`の`renderDetailPopup()`に反映。
- [x] メイン画面お知らせ2番目リンクの契約書検索への分岐：原本`clickNoticeLink()`は2番目のお知らせ
  （表示文言は「文書」）クリック時のみ契約書検索へ遷移する原本特有の挙動。`templates/core/menu.html`
  のリンク先を`contracts:search`に変更（件数集計自体は文書基準のまま、原本自体が持つ矛盾として
  踏襲）。
- [x] 「登録した文書/契約書を確認する」ボタンが絞り込み表示しない：`documents/contracts`の
  `search_services.build_queryset()`に`pks`引数を追加し、`storage_complete.html`から
  `?pks=1,2,3`形式で直前に登録したレコードだけを検索条件に関係なく表示できるようにした。
- [x] 契約書の複数件一括登録時の関連書類添付制限を解除：以前はHTML/xlsxに複数件時の割り当て方法が
  未定義という理由で1件登録時のみ許可していたが、原本`setupStorageFormForActiveDoc()`通り
  文書ごとに独立した関連書類欄を持つよう`storage2.html`を`title-row`と同じ`data-doc-index`方式に
  再構成（`related_files_{doc_index}`）、`UploadStep2View.post()`で文書ごとに振り分けて保存。
- [x] カスタム403テンプレート追加：`templates/403.html`を新設。以前はテンプレートが無く
  `PermissionDenied`のメッセージ（所属長の自己権限編集ブロック等）が実際には利用者に届かず
  汎用の「403 Forbidden」になっていた。
- [x] その他設定「メイン画面項目編集」の「No.」欄修正：一覧画面と同じ並び順
  （`branch_code, section_code`）での行位置を計算して渡すよう修正（以前は`department.pk`を
  そのまま表示しており、作成順と一覧の表示順がずれると編集画面の「No.」が一覧と食い違っていた。
  保存期間設定削除確認で過去に発見・修正した同種のバグパターン）。
- [x] 職員マスタの本支所→部課連動プルダウン無効化ロジックを復元：原本`updateCode()`の
  「本店(000)以外は部課select自体を無効化する」業務ルールが、選択肢の絞り込みのみ実装されていて
  disabled化が再現されていなかった。`staff_regist.html`/`staff_edit.html`の`updateSections()`に
  同ロジックを追加。

### 見送った低優先度（6件、ドキュメントのみ・修正なし）
ユーザー指示により意図的に未修正。将来対応する場合の参考として記録する。
- 詳細ポップアップの削除完了メッセージ文言が原本「文書を削除しました。」に対し実装は
  「削除しました。」（`static/js/common.js`の`triggerDeleteFromDetail()`）。
- ~~保管画面のメモ欄「削除」ボタン（`clearMemo()`）に、原本には無い確認ダイアログ・実消去機能が
  独自に追加されている（原本はonclick未設定の完全な無反応ボタン）。~~
  → **2026-08-27解消**。ユーザー確定でレコード削除／アップロード取り消しに再定義し、`clearMemo()`
  は廃止。下記「保管画面２「削除」ボタンをメモ消去→レコード削除／アップロード取り消しへ変更」節参照。
- 編集画面（documents/contracts双方の`edit.html`）ヘッダーの「＜ 戻る」ボタン遷移先が、原本の
  `transitionTo('screen-storage1')`（ファイル選択画面）ではなく検索画面になっている
  （原本側がこの导線を更新し忘れている疑いがあり、実装側の解釈は妥当と考えられる）。
- 職員マスタ一覧（`staff_list.html`）に、原本には無い列見出しソート機能が追加されている
  （他の一覧画面と同じ全社的パターンとしての拡張）。
- 職員マスタ編集（`staff_edit.html`）のパスワード欄に、原本には無いヒント文言
  「空欄のまま更新すると変更されません。」が追加されている（パスワードマスク表示化という
  既存の意図的逸脱から派生した補足）。2026-09-01ユーザー依頼で、セル内の入力欄下（縦積み）から
  セル右外の欄外（右側）へ配置変更（`.password-note-aside`、`password-wrapper`=relative基準の
  絶対配置。パスワード行だけ行高が増えて他行と不揃いになるのを避けるため）。
- その他設定パスワード変更の更新完了メッセージが原本「更新しました」に対し実装は
  「パスワードを更新しました。」（`core.views.OtherSettingsView.post()`）。

### 検証
- [x] `manage.py check`（問題なし）
- [x] 全体テストスイート**102件PASS**（修正前82件から、監査ログ・空選択肢排除・pks絞り込み・
  AJAX削除レスポンス・No.表示順・複数件一括登録時の関連書類振り分け、について新規20件追加）
- [x] Djangoテストクライアントで契約書の複数件一括登録＋関連書類の個別振り分けを実POSTで確認
  （文書ごとに異なるファイルが正しく紐づくことを確認済み）

## 保管画面１ チャンク分割アップロード追加（2026-08-10）

原本HTML/xlsxには記載の無い技術的対応として、旧実装と同様のチャンク分割アップロードを
ユーザー依頼で追加した。
- [x] 旧実装側にあった「結合済みファイルを一旦別の保留プールに貯めて通常アップロードPOST側で
  合流させる」という中間層は、本実装の`save_pending_files`が呼ばれるたびに既存セッション内容へ
  追記する設計のため不要と判断し省略した
- [x] `settings.CHUNK_UPLOAD_MAX_SIZE_BYTES`追加（結合後最終ファイルサイズ上限、既定500MB）
- [x] `core/upload_services.py`に`save_upload_chunk`/`combine_upload_chunks`/`ChunkUploadError`追加
- [x] `core/upload_views.py`（新規）に`BaseChunkUploadAPIView`追加、documents/contracts双方の
  `api.ChunkUploadAPIView`から継承（`upload/chunk/`エンドポイント）
- [x] `static/js/chunk_upload.js`（新規、旧実装から移植）。`storage1.html`のsubmitハンドラで
  `max_upload_size_bytes`基準の自動振り分け（単体超過分・合計超過分ともにチャンク経由）を実装
- [x] `documents/contracts.UploadStep1View.post`の潜在バグを発見・修正：`save_pending_files`は
  ファイルI/Oエラーを`PendingFileStorageError`にラップして送出するにもかかわらず、ビュー側は
  素の`OSError`をexceptしており、実際には一度もエラーハンドリングに到達していなかった
  （既存テストがモックで直接`OSError`を投げていたため見過ごされていた）。正しい例外型に修正し、
  該当テストのモックも実際の契約に合わせて修正
- [x] テスト新規17件追加（core: サービス層5件、documents/contracts: API・統合各6件）、
  全体テスト**150件PASS**、`manage.py check`問題なし
- [x] ブラウザ実地確認済み：12MBファイルを選択→5MBチャンク3回のPOSTで自動分割送信→
  保管画面１の「実行」（ファイル欄は空のまま）→保管画面２に正しく引き継がれることを確認。
  1KBの通常ファイルは従来通り一括POSTで即座に保管画面２へ遷移することも確認（回帰無し）

## 運用面の未実装改善候補の棚卸し・実装（2026-08-12）

ユーザーから「原本にはないが実装したほうがいい項目」の調査依頼を受け、セキュリティ・運用監視・
データ整合性等の観点でDjangoプロジェクト全体を監査（実装コードは書かず調査のみ）。見つかった
候補のうち、**既存画面の見た目に影響しないバックエンド／設定系の項目のみ**を選んでユーザー指示で
実装した。詳細な運用方針の経緯はCLAUDE.md「原本フィデリティに関する運用方針」ではなく
このセクションに記録する（原本一致方針の例外ではなく、そもそも原本に対応する画面が無い
純粋な追加機能のため）。

- [x] ログイン失敗の監査ログ記録（`accounts.views.LoginView.form_invalid`）。成功時のみ
  `audit_services.log()`が呼ばれ失敗が一切記録されない状態だった。認証済みEmployeeを経由
  できない場面向けに`audit.services.log_raw()`を新設（職員番号が未登録の場合は「不明」で記録）。
  レート制限・アカウントロックは失敗画面に新規UI文言が必要になるため対象外とした。
- [x] ダウンロード／プレビュー操作の監査ログ追加（`documents`/`contracts`の`DownloadView`・
  `PreviewView`・`BulkDownloadView`）。登録・更新・削除は記録されるのに、文書管理システムの
  核心操作である「誰がいつ閲覧・持ち出したか」だけ監査ログに一切残っていなかった。
  保管前の`PendingPreviewView`（pkの無いセッション保留ファイル）は対象外。
- [x] 500エラー（未処理例外）発生時の管理者メール通知（`config/settings/prod.py`に`ADMINS`／
  `MANAGERS`／SMTP設定／`AdminEmailHandler`を追加）。base.py末尾に「望ましい」と書き残されて
  いた対応。`.env`の`ADMIN_EMAILS`等が未設定の間はDjango本体の仕様で何もしない安全側の既定。
- [x] 本番向けセキュリティヘッダー追加（`config/settings/prod.py`に`SECURE_HSTS_SECONDS`・
  `SECURE_CONTENT_TYPE_NOSNIFF`・`CSRF_TRUSTED_ORIGINS`）。
- [x] ヘルスチェックエンドポイント追加（`GET /healthz/`、`core.views.HealthCheckView`、
  `LoginRequiredMixin`無し）。DB疎通のみ確認しJSONで返す。既存画面とは無関係の新規URL。
- 実装せず見送った候補（理由付きで次回検討用に記録）：
  - アップロードファイルの拡張子偽装・ウイルススキャン検証（新規の失敗時UI文言が発生するため）
  - 同時編集の競合検知・楽観的ロック（衝突時に新規のUI/エラー表示が必要になるため）
  - バックアップ運用の自動化（保存先・保持期間等の運用方針の意思決定が必要なため）
  - フォームのリアルタイムバリデーション強化・audit一覧の検索/絞り込み/エクスポート拡充
    （いずれも既存画面の見た目・操作性が変わるため今回のスコープ外）
  - 依存パッケージの脆弱性スキャン（pip-audit等）の定期実行の仕組み化
- [x] テスト新規12件追加（accounts 2件、documents 4件、contracts 4件、core 2件）、
  全体テスト**225件PASS**、`manage.py check --deploy`（prod設定）で新規の警告無し確認

## 原本HTML改訂差分の確認（html1→html2、2026-08-12確認）

原本HTML改訂を受け取ったら、Claudeに全文再監査させる前にまず`diff`で機械的に差分を特定する
運用を導入（2026-08-12）。`HTML/html1`→`HTML/html2`（2026-08-08受領）で試したところ：
- [x] `diff html1/index.html html2/index.html`で全差分はわずか2行、共通ポップアップ選択JS
  `openPopupPopup()`内（`type === 'year'`の時に検索欄`popup-select-search`を非表示にする分岐）
  のみと判明。個別33画面の`screens/*.html`は`diff -rq`で全て同一と確認、影響なし
- [x] `screens/*.html`は画面ごとの`<div id="screen-...">`断片のみを含み、共通`<script>`部分は
  元々含まない設計と確認（分割ファイルの更新漏れではない）
- [x] `static/js/common.js`の`openPopupPopup()`（162行目
  `searchInput.style.display = type === "year" ? "none" : "block";`）で該当挙動が既に実装済みと
  確認。修正不要
- 今後も原本HTML改訂を受け取った際は、上記と同じ手順（`diff`で差分特定→画面固有／共通部分の
  どちらかに振り分け→該当箇所のみ確認）で対応する

## 検索・閲覧画面「文書イメージ」実プレビュー追加（2026-08-10）

原本のscreen-searchでは、一覧をクリックすると「文書イメージ」欄にクリックした行のタイトルを
表示するだけの固定シミュレーションだった。ユーザーが「原本にはないが」と前置きした依頼を受け、
実ファイルのプレビュー表示に対応した。
- [x] `documents`/`contracts.PreviewView`新設、`Content-Disposition: inline`でiframe埋め込み
- [x] ダウンロード権限（`can_download`）が無いユーザーには実ファイルを読み込ませず、原本通りの
  シミュレーション文言にフォールバックする

## OCR（Google Cloud Vision）本文抽出・PDF埋め込み追加（2026-08-10）

`documents.Document`/`contracts.Contract.extracted_text`（2026-08-07にユーザー指示で追加済みの
全文検索基盤）の本文抽出処理として、旧実装と同種のOCRを追加した（原本HTML/xlsxにOCR・
全文検索の抽出処理に関する記載は無い）。
- [x] 旧実装は「プランA」（Vision同期API`batch_annotate_files`、1リクエスト最大5ページ制約）と
  「プランB」（`pdf2image`でページ画像化、ページ数制限なし）を`settings.OCR_PLAN_B_ENABLED`で
  切替可能にしていたが、本実装ではその切替は設けずプランB方式のみで固定した（2026-08-10ユーザー指示）
- [x] `OCR_ENABLED`は「コンプライアンス未承認のため既定False」だったのを、承認済みの前提で
  既定Trueに変更（`config/settings/base.py`）
- [x] 同日追って、OCR結果をPDFへ透明テキストとして埋め込む機能（旧実装の`searchable_file`／
  `OCR_EMBED_TEXT_TO_PDF`）も移植。`OCR_EMBED_TEXT_TO_PDF`は既定False（埋め込み済みPDFを原本とは
  別に恒久保存する運用自体は別途承認が必要と判断し、`OCR_ENABLED`とは異なり既定をTrueにはしていない）
- [x] `OCR_EMBED_TEXT_TO_PDF`がTrueの間、スキャン文書のOCR実行時に座標付き抽出
  （`core.ocr_layout_services.extract_text_and_layout_via_ocr`）を使い、結果を透明テキストとして
  埋め込んだPDFを`core.pdf_text_embed_services.embed_textdatas_into_pdf`（reportlab/pypdf）で生成し
  `searchable_file`（null許容、既定未生成）に保存する。原本（`file`フィールド）は変更せず別ファイル
  として保持する（監査・原本性の観点）
- [x] 埋め込み失敗は全文検索の本体（`extracted_text`）に対する付加処理の失敗として握りつぶし、
  テキスト抽出自体は成功させる
- [x] `searchable_file`は本追加時点で検索・プレビュー・ダウンロード画面とは未連携（バックエンドでの
  生成のみ）

## OCR単純抽出とPDF埋め込み用抽出の統合、個人情報フラグ連動の埋め込み制御（2026-08-19）

ユーザーから「`core.ocr_services.extract_text_via_ocr`と`core.ocr_layout_services.
extract_text_and_layout_via_ocr`が似た処理で統合できないか」「`OCR_EMBED_TEXT_TO_PDF`を
ファイル単位（個人情報を含む場合は貼り付けない等）で切り替えられないか」の2点を指摘され、
両方ともユーザー承認を得て実装（原本HTML/xlsxに存在しない機能改善、CLAUDE.mdの運用方針の通り
ユーザー指示を優先）。
- [x] **OCR統合**: `core.ocr_services.extract_text_via_ocr`（Vision標準の`full_text_annotation.text`
  をそのまま使う単純版）を廃止し、`core.management.commands.extract_pending_pdf_text`は常に
  `core.ocr_layout_services.extract_text_and_layout_via_ocr`（座標付き抽出）を使うよう統合した。
  両関数はpdf2image変換・Visionクライアント生成・ページ単位ループの大部分が重複していた一方、
  本文の組み立て方（Vision標準の再構成 vs 座標からの独自再構成、傾き・回転補正込み）が異なり、
  統合により**既存のextracted_textの中身（行順等）が変わりうる**ことをユーザーに明示した上で
  本格統合を選択。統合後は`core.ocr_services`モジュール自体（is_scanned判定・OcrDisabledError
  しか残っていなかった）を廃止し、`is_scanned`は主な利用者である`core.text_extraction_services`
  へ、`OcrDisabledError`は唯一のOCR呼び出しモジュールになった`core.ocr_layout_services`へ
  それぞれ移設した
- [x] **ファイル単位の埋め込み制御**: `extract_pending_pdf_text.Command._should_embed(obj)`を追加。
  `documents.Document.privacy_flag`（個人情報が含まれる、既定True）がTrueのレコードは、
  `OCR_EMBED_TEXT_TO_PDF=True`でも埋め込みをスキップする（個人情報を検索用PDFへ透明テキストと
  して複製しないための判断）
- [x] `contracts.Contract`は元々`privacy_flag`相当のフィールドを持たない設計（要再確認事項として
  意図的に省略済み）。ユーザー確認の結果、契約書は個別判定を設けず`OCR_EMBED_TEXT_TO_PDF`の
  グローバル設定のみに従う方針とした（`_should_embed`は`privacy_flag`属性を持たないモデルに対し
  常にTrueを返す）
- [x] `core/tests.py`のOCR関連テストを全面的に更新（`extract_text_via_ocr`関連テストを削除し、
  ページ単位エラーのスキップ検証は`OcrLayoutServicesTests`に移設。`_should_embed`単体テストの
  `ShouldEmbedTests`クラスを新設、`ExtractPendingPdfTextEmbedTests`に個人情報フラグ連動のテストを追加）

## 保管画面２・編集画面・検索/閲覧詳細ポップアップの画像/PDF実プレビュー追加（2026-08-12）

原本HTML/xlsxはファイル名を切り替えるだけの固定モックのみで実データ連携は無い。ユーザー明示依頼
（当初は画像のみの依頼だったが、同日中に追加依頼でPDFにも対応）。
- [x] 保管画面２（登録前）・編集画面の`pdf-mock-page`に、対象が画像／PDFの場合のみ実データの
  プレビュー（画像は`<img>`、PDFはブラウザ内蔵ビューアに任せる`<iframe>`）を表示
- [x] 種別判定は`core.file_type_services.get_preview_kind`（拡張子ベースで"image"/"pdf"/Noneを返す。
  DB・保留ファイルいずれもMIME種別を保持するフィールドが無いため。SVGはインラインscriptを
  含められるためXSS対策上画像として扱わない）
- [x] 編集画面（`DocumentEditView`/`ContractEditView`）は既存の`PreviewView`（pkベース、
  `can_download`権限）をそのまま使う
- [x] 保管画面２（`UploadStep2View`）はDB登録前でpkが無いセッション保留ファイルが対象のため、
  新規に`PendingPreviewView`（`upload_step2_preview`、保留ファイル一覧のindexで参照、
  `can_download`権限で保護）を追加
- [x] 登録・更新完了後の完了モーダルでは保留ファイルが`clear_pending_files`で削除済みのため、
  代わりに登録済みオブジェクトのpkを使う`PreviewView`を指す
- [x] `can_download`が無いユーザーには`preview_urls`を空にし、従来の擬似PDF文言のモック表示のまま
  変わらないようにする（screen-searchの実プレビュー機能と同じgating方針）
- [x] 検索・閲覧画面の一覧ダブルクリックで開く詳細ポップアップ（`#popup-detail`、`common.js`の
  `renderDetailPopup()`）にも同じ実プレビューを追加。fetch()で毎回動的に開く共通DOM
  （documents/contracts兼用）のため、`{% if %}`分岐ではなく`DetailAPIView`のJSONに
  `preview_url`/`preview_kind`（`can_download`権限gating込み）を追加し、`renderDetailPopup()`側で
  JSにより表示を切り替える方式にした
- [x] 同時に、契約書の「関連書類」欄がAPIで`rf.file.name`（MEDIA_ROOT基準のフルパス）をそのまま
  返しており表示が長くなっていたバグを発見・修正（`rf.display_name`を使うよう変更。原本フィデリティ
  とは無関係の実装バグ）

## ゴミ箱保管中の文書・契約書に対する完全削除機能追加（2026-08-12）

ユーザー報告：削除済み（ゴミ箱保管中）文書一覧の詳細ポップアップで「変更」ボタンが404、「削除」
ボタンが紛らわしい失敗アラートになる（`DocumentEditView`/`DeleteView`双方が`is_deleted=False`
でしか対象を取得できない実装のため）。
- [x] まず`DetailAPIView`の`edit_url`/`delete_url`を`is_deleted`の間はNoneにし、
  `renderDetailPopup()`側もdisabled+titleでボタンを無効化する対応を先行実施
- [x] 続けてユーザーから「ゴミ箱保管中を削除で完全削除にできるか」と依頼があり、`DeleteView.post()`
  を「対象がまだ`is_deleted=False`なら従来通り論理削除、既に`is_deleted=True`（ゴミ箱保管中）なら
  DBレコード・ファイル実体（契約書は関連書類のファイル実体も含む）ごと完全削除」という二段階の
  挙動に変更
- [x] これにより`delete_url`は`is_deleted`に関わらず常に返す（「削除」ボタンは常時有効）よう戻し、
  `edit_url`のみ引き続き`is_deleted`の間はNoneのまま（削除済み文書の編集は非対応）
- [x] 原本index.html:1126のconfirm文言「この文書データを完全に削除してもよろしいですか？」は、
  通常削除時（実際は論理削除のみ）は文言と実態が完全には一致しないが、ユーザーの明示判断で
  原本フィデリティ優先のため文言変更はしない方針（ゴミ箱保管中からの削除時は文言通り実際に
  完全削除になる）
- [x] （2026-08-17追記）上記方針をユーザー指示で転換。通常削除時に「完全に削除」という文言を
  見せると誤解を招くとのフィードバックを受け、`static/js/common.js`の`triggerDeleteFromDetail()`
  に`isDeleted`引数を追加し、`is_deleted`の値でconfirm文言を「この文書データをゴミ箱に移動しても
  よろしいですか？」（通常削除時）／「この文書データを完全に削除してもよろしいですか？」
  （ゴミ箱保管中からの削除時）に出し分けるよう変更（原本フィデリティよりユーザー指示・実挙動との
  整合を優先）。同じ理由で、AJAX完了時のalert文言も従来の固定「削除しました。」から
  `DeleteView.post()`が返す`message`（「文書を削除しました。」／「文書を完全に削除しました。」等）
  を使うよう変更し、`JsonResponse`に`message`フィールドを追加（documents/contracts双方）。
  関連する`documents/tests.py`・`contracts/tests.py`のJSON完全一致アサーションも更新

## 保管画面１・２ 監査・修正（2026-08-12）

ユーザー依頼で保管画面１・２（`documents`/`contracts`の`UploadStep1View`/`UploadStep2View`および
編集画面）まわりの矛盾・不自然な実装点を横断監査。

- [x] チャンク分割アップロードのチャンクサイズ食い違いを修正（`static/js/chunk_upload.js`）。
  `CHUNK_UPLOAD_CHUNK_SIZE`が5MBから1MBへテスト用に変更されたまま、コメントアウトされた旧5MB行と
  末尾の「// 5MB」という誤ったコメントが残っており、`config/settings/base.py`のコメントや
  「12MBファイル→5MBチャンク3回のPOST」という本ファイル437行目の実地確認記録と食い違っていた。
  5MBに戻し、死んだコメントアウト行・誤コメントを削除
- [x] 編集画面「年」フィールドが古い文書・契約書を無言で書き換える不具合を修正（`documents/forms.py`・
  `contracts/forms.py`の`UploadStep2Form`）。年の選択肢は値のハードコードを避けるため実行時の
  直近6年分（現在年+1〜現在年-4）のみ動的生成していたが、編集対象の年がその範囲外（保存期間が
  長く何年も前に登録された文書・契約書等）だと、Djangoが生成する`<select>`のどのoptionにも
  `selected`属性が付かない（実際にレンダリングして確認済み）。ブラウザはこの場合HTML仕様により
  先頭optionを自動選択するため、利用者が年欄に一切触れずメモ欄修正等だけ行って更新すると、
  年が意図せず直近ウィンドウの最大値へ書き換わってしまっていた
  - `core/forms.py`に`year_choices_with_existing()`を新設（documents/contracts共通処理として集約）。
    編集対象の現在の年（`self.initial.get("year")`）が動的ウィンドウの外にある場合、選択肢へ
    追加してから降順ソートする
  - documents/contracts双方の`UploadStep2Form.__init__`を、この関数経由で選択肢を生成するよう修正
  - 回帰テストを追加（`documents.tests.EditScreenYearFieldTests`・
    `contracts.tests.EditScreenYearFieldTests`）：(1) 範囲外の年がGET時に`selected`付きで
    レンダリングされること、(2) 年欄を変更せず送信しても年が保持されること、を確認

## メイン画面お知らせ件数を検索画面の可視範囲に合わせる修正（2026-08-13）

ユーザー指摘：メイン画面「有効期限切れ」お知らせの件数と、クリック先の検索・閲覧画面の
検索結果件数が一致しない。

- 原因：`core/notice_services.py`の`get_notice_counts()`が全部署の文書を無条件で集計していた
  一方、リンク先の`documents/search_services.py`（`build_queryset()`）は
  `permissions.services.can_select_department()`がFalse（管理者ロール以外）の職員には
  `department=employee.department`の絞り込みを掛けていたため。管理者ロールでログインしている
  間は一致するが、所属長・一般ロールでは検索結果の方が少なくなる。
- [x] `get_notice_counts()`に`employee`引数を追加し、`can_select_department(employee)`がFalseの
  場合は検索画面と同じ`department=employee.department`フィルタを適用するよう変更
  （バッジ件数は「クリックした先で実際に見える件数」と一致するべき、というユーザー判断）
- [x] 呼び出し元`core/views.py`の`MenuView.get_context_data()`を`get_notice_counts(self.request.user)`
  に更新
- [x] 回帰テスト追加（`core.tests.NoticeCountsTests.test_other_department_document_not_counted_for_staff`）：
  他部署の期限切れ文書が一般ロール職員のカウントに含まれないことを確認

## お知らせしきい値・契約書保存期限をDB(SystemSetting)から.env設定値へ移行（2026-08-13）

xlsx メイン画面!B36「有効期限切れまでのXヵ月」/B38「直近Xヵ月」/B48「契約書の保存期限固定10年」は
いずれも「設定ファイル等で定義し、先方より変更依頼を受けた際に容易に変更できること」と明記されて
いるが、実装当初は`masters.SystemSetting`のDBフィールド（`notice_threshold_months`・
`contract_retention_years`）として持っており、編集用の管理画面もDjango管理サイト登録も無く、
実質DB直接操作でしか変更できていなかった。加えてB36とB38はxlsx上別々の設定値（別セル）にも
関わらず、実装は`notice_threshold_months`1つを両方で共有していた。ユーザー確認の上、以下を対応。

- [x] `config/settings/base.py`に`NOTICE_EXPIRING_THRESHOLD_MONTHS`・
  `NOTICE_DELETED_THRESHOLD_MONTHS`（分離）・`CONTRACT_RETENTION_YEARS`をdjango-environ経由
  （`.env`で上書き可）で追加。`.env.example`にも追記
- [x] `masters.SystemSetting`から`notice_threshold_months`・`contract_retention_years`フィールドを
  削除（`masters/migrations/0002_remove_systemsetting_contract_retention_years_and_more.py`）
- [x] `core/notice_services.py`の`get_notice_counts()`/`is_expiring_soon()`を上記settingsを見るよう
  変更。月加減算ヘルパーは`_add_months`から`add_months`へ改名し公開関数化（documents/contracts
  双方の`_apply_notice_filter()`と共有するため）
- [x] `documents/search_services.py`・`contracts/search_services.py`の`_apply_notice_filter()`を
  settings参照に変更する過程で、**「有効期限切れまでXヵ月以内」の絞り込みに上限が無く未来の全件が
  ヒットしてしまうバグを発見・修正**（xlsx「本日日付よりXヵ月以内に保存期間を過ぎる予定の文書のみ」
  だが実装は`expiry_date__gte=today`のみで上限`__lte`が無かった）。あわせて`recently_deleted`側の
  月加減算も簡易な`day=min(today.day, 28)`打ち切りから、日数を正確に扱う`add_months()`共有関数に
  統一
- [x] `contracts/services.py`の`calculate_expiry_date()`を`settings.CONTRACT_RETENTION_YEARS`参照に変更
- [x] 回帰テスト追加：`core.tests.NoticeCountsTests.test_expiring_and_deleted_thresholds_are_independent`
  （2つのしきい値が独立して効くこと）、`documents.tests.NoticeFilterTests`・
  `contracts.tests.NoticeFilterTests`（「期限切れまでXヵ月以内」の上限バグの回帰確認）

## メイン画面お知らせ文言のXヶ月未置換・2件目の遷移先統一（2026-08-13）

- [x] `templates/core/menu.html`「X ヶ月」（原本index.html:121-122のJSでも一度も置換されない静的
  モック文言）を`core/views.py`の`MenuView.get_context_data()`が渡す実際の設定値
  （`notice_expiring_threshold_months`/`notice_deleted_threshold_months`）に置換。回帰テスト
  `core.tests.MenuViewNoticeThresholdDisplayTests`を追加
- [x] ユーザー実運用報告：「有効期限切れまで1ヶ月以内の文書が10件」をクリックすると遷移先
  （契約書検索画面）の表示件数が10件と一致しない。原因は、お知らせのバッジ件数が
  `documents.Document`基準の集計である一方、2件目のリンク先だけ`contracts:search`
  （`contracts.Contract`という別テーブル）に飛んでいたため（本チェックリスト内「メイン画面
  お知らせ件数を検索画面の可視範囲に合わせる修正」で対応した部署フィルタの話とは別原因）。
  以前は原本HTML実JSの`clickNoticeLink()`挙動に合わせて契約書検索への遷移を維持していたが、
  ユーザー判断により3件とも文書検索（`documents:search`）へ統一（`core/notice_services.py`・
  `templates/core/menu.html`のコメントも更新）

## 第一陣以外（第二陣・第三陣28画面）の原本フィデリティ再監査・修正（2026-08-13）

「5画面グループ」（第一陣：ログイン/メイン/保管画面1・2/検索画面）のテストレビュー
（popup-select部署選択APIの権限不備、コミットd641322）を受け、残り28画面（第二陣11画面・
第三陣17画面）についても原本HTMLと実装テンプレートを並列で突き合わせ監査した。

- [x] 【高】権限管理編集画面（`permissions/views.py`の`AuthorityDetailView`/`AuthorityEditView`）
  で、所属長ロールが対象社員の部署・現ロールを一切チェックされないまま任意の職員のpkを
  直接指定でき、他部署職員の権限詳細閲覧・編集や、ロールを「管理者」まで昇格させることが
  できてしまっていた（xlsx 権限管理!B113「所属長は自分の部署の"一般"職員のみ権限変更可」、
  B153/155「所属長はロールを"職員(一般)"のみ選択可」が未実装だった）。
  - `permissions/services.py`に`can_manage_target(viewer, target)`を新設（管理者は制限なし、
    所属長は自部署かつ対象が一般ロールの場合のみ、一般は常に不可）
  - `AuthorityDetailView`は閲覧対象自体を一覧と同じ`visible_employees()`（自部署のみ）の
    範囲に絞り、`can_edit`も`can_manage_target()`に統一
  - `AuthorityEditView.dispatch()`で`can_manage_target()`により対象外アクセスを403に統一
  - `AuthorityEditForm`に`editable_roles`引数を追加し、所属長が編集する場合は`role`
    フィールドの選択肢自体を「一般」のみに絞り込み（ChoiceFieldの`choices`を絞るため、
    POSTで直接`admin`等を送ってもバリデーションで弾かれる、テンプレート側の見た目の
    絞り込みだけに頼らない実装）
  - 回帰テスト5件追加（`permissions.tests.AuthorityEditViewTests`）
- [x] 【中】その他設定「メイン画面項目編集」一覧（`templates/core/other_main.html`）の
  ページャーが常に「1ページ固定・次へ/前へdisabled」の静的表示で、`OtherSettingsView`が
  全部署を無条件に1ページで返しており、他の一覧画面（分類管理・カテゴリー管理・操作履歴
  ログ等）と異なりDjango Paginatorが未実装だった。`OtherSettingsView._render_main()`に
  `Paginator`（PAGE_SIZE=50、他画面と同じ）を導入し、テンプレートのページャーも他画面と
  同じ実装に統一。行の「No.」表示は`page_obj.start_index`基準にしページをまたいでも
  通し番号を維持（`OtherMainEditView`側の「No.」計算は元々全件基準のため変更不要）。
  回帰テスト2件追加（`core.tests.OtherMainListPaginationTests`）
- 【低】2件（実害なし、修正見送り）：部署編集画面のラジオ`name`属性が原本`dept-action`
  （ハイフン）に対し実装は`dept_action`（アンダースコア、Django仕様上の帰結でJS側と整合
  済み、挙動差異なし）／権限管理一覧の原本サンプルデータ「DXロール」を実装で再現していない
  （既知・意図的）
- 上記以外の24画面（第二陣8画面・第三陣16画面）は差異なし。08-10〜08-13の機能追加
  （チャンクアップロード・OCR・実プレビュー・完全削除機能・お知らせ設定env化等）は
  これら28画面のテンプレート自体には影響していないことを確認した
- [x] 検証：`manage.py check`問題なし、全体テストスイート**257件PASS**、ブラウザ実地確認
  （所属長ロールで他部署職員の詳細ページ`/permissions/<pk>/`が404、編集ページが403、
  自分自身の編集も403のまま維持されること。管理者ロールでは従来通り3ロール全て選択可能
  でその他設定一覧のページングが視覚的に既存表示のまま壊れていないことを確認）
- ブラウザ確認中に本監査と無関係な別バグを1件発見（`templates/core/menu.html`50-55行目の
  Djangoコメント`{# #}`が複数行にまたがっており、Django側の仕様（単一行のみ対応）により
  コメントとして解釈されずメイン画面のお知らせ欄にコメント文がそのまま表示されてしまう）。
  今回のスコープ外のため別タスクとして切り出した（未着手）

## 第二陣・第三陣 コメント/ログ/例外処理の再点検・修正（2026-08-13）

上記の原本フィデリティ再監査とは別に、コメントの「なぜ」の説明、ログの整備、例外処理の
完成度という観点でユーザー指示により`accounts`/`organizations`/`permissions`/`masters`/
`audit`/`core`を通読点検し、4件を修正した。

- [x] 【中〜高】権限管理CSV出力（`permissions/views.py`の`AuthorityCsvExportView`）が
  `logger.info()`のみで`audit_services.log()`を一切呼んでおらず、監査ログに記録されて
  いなかった。同種の個人情報一覧CSV出力である`accounts/views.py`の`StaffCsvExportView`は
  `personal_info_flag=True`で監査ログに記録しており、権限管理CSVは氏名・部署に加え権限
  フラグという更に機微な情報を含むため記録漏れと判断。`audit_services.log()`呼び出しを
  追加し、回帰テスト`permissions.tests.AuthorityCsvExportViewTests.
  test_export_creates_audit_log_with_personal_info_flag`を追加した。
- [x] 【低、既存バグ・未着手だった上記の別バグを解消】`templates/core/menu.html`50-55行目の
  複数行`{# #}`コメントを`{% comment %}...{% endcomment %}`に置き換え、メイン画面
  「お知らせ」欄にコメント文が生テキスト表示される不具合を解消した。
- [x] 【低】`core/views.py`の`OtherSettingsView.post()`で管理者が一般向けパスワード変更
  エンドポイントにPOSTした場合の403分岐に`logger.warning()`が無く、同じファイル内の
  `OtherMainEditView.dispatch()`/`OtherLogoutEditView.dispatch()`の権限拒否ログと
  一貫していなかったため追加した。
- [x] 【低、実害なし】`templates/core/other_main.html`の新規ページャー（本監査直前に追加）が
  `?page=N`のみで遷移しており、`class_list.html`等の既存ページャーが統一して使う
  `?{{ request.GET.urlencode }}&page=N`パターンから外れていたため揃えた。
- 検証：`manage.py check`問題なし、全体テストスイート**258件PASS**。

## テストチェックリスト③保管画面２ No.19 NG調査・修正（2026-08-13）

テストチェックリストの「年セレクトの値を変更する→有効期限プレビューが変更後の年を基準に
再計算される」がNGとの報告を受け調査。

- [x] 原因：`documents/forms.py`の`UploadStep2Form.year`（`<select id="storage-year">`）に
  `onchange`が設定されておらず、`calculateExpiryDate()`は`retention_period`側
  （`storage-period`）の`onchange`からしか呼ばれていなかった。関数自体は年セレクトの値を
  読んで計算する実装（`documents/storage2.html`・`edit.html`）になっており、配線漏れと
  判断。原本index.html:217の`<select id="storage-year">`にも同様に`onchange`が無く、
  原本自体の配線漏れが引き継がれていた（過去の2026-08-08監査でも見落とし）。
- [x] `year`フィールドのwidget属性に`onchange="calculateExpiryDate()"`を追加
  （`documents/forms.py`）。`UploadStep2Form`は保管画面２・編集画面の両方で共用のため
  1箇所の修正で両画面に反映される。

## 権限管理一覧・詳細画面のレイアウト不具合修正（2026-08-13）

ユーザー報告：権限管理一覧のスクロールバーの動作がおかしい（権限列でスクロールが終わらない）、
詳細ボタンで遷移した画面の入力エリアが、入力（〇）が無いと高さがおかしい。

- [x] 【権限管理一覧】固定列（職員番号/部署/氏名/役職/権限、`.col-1`〜`.col-5`）の
  `left`位置が`style.css`側で60px/102px/78px/100px幅を前提にしたハードコード値になっていた。
  これは原本CSSそのままの値（原本モックの固定文言「本　店|ＤＸ推進課」等を前提にしたもの）
  だが、実データでは列幅が変わり、`position:sticky`の`left`と実際の列幅が食い違って
  隣接列が重なったり隙間が空いたりしていた（実測：2列目が1列目に約11.5px重なり、
  5列目〈権限〉の手前に約55pxの不自然な空白ができ、横スクロールが終わらないように見える
  原因になっていた）。`static/js/common.js`に`fixAuthorityStickyOffsets()`を追加し、
  実際に描画された列幅からDOMContentLoaded時・リサイズ時に`left`を都度計算し直すよう変更
  （CSS側の値は原本のまま残し、JSで補正する方式。style.css自体は原本コピーとして
  手を加えない方針のため）
- [x] 【権限管理詳細】`templates/permissions/authority_detail.html`の各権限フラグ
  `{% if profile.xxx %}〇{% endif %}`が、フラグが1つもONでない区分（PermissionProfile
  未設定の職員、または電子決裁のように運用上常に全OFFの区分）だと該当行の全`<td>`が
  完全に空になり、行の高さが他の行（〇が入っている行）より縮んで見える不具合があった
  （実測：30.5px→11px）。原本モックは常に「〇」が入ったデータのため再現しない不具合。
  空の場合は`&nbsp;`を出力するよう修正（`{% else %}&nbsp;{% endif %}`、
  分類表示欄の`{% for %}`ループも`{% empty %}&nbsp;{% endfor %}`に変更）
- [x] 検証：Djangoテストクライアントで回帰テスト1件追加（`&nbsp;`が19箇所出ることを確認）、
  全体テストスイート**259件PASS**。ブラウザでも列オフセット計算・行高さ双方を実測し修正を確認
  （検証中、テンプレート編集後もこの開発セッション内の同一プレビュータブが古いレスポンスを
  返し続ける現象に遭遇したが、devサーバー再起動後は正しく反映されることを確認済み。
  コード自体の問題ではなく検証環境固有の事象と判断）

## 保存期間設定ラジオボタン位置・一覧ソートリンク色の修正（2026-08-13）

- [x] `templates/masters/retention_list.html`の「文書」ラジオ直後に、原本（`index.html:3011`）に
  ある全角スペース（`　`）が抜けており、「電子決裁」ラジオが原本より約13px左（全角文字1個分）に
  寄っていた。全角スペースは通常の空白と違って畳み込まれない実文字のため、原本ではこれが
  意図的な余白として機能していた。追加して原本通りの間隔（実測46px）に修正。
- [x] ユーザー確認：職員マスタ一覧・部署管理一覧・権限管理一覧のソート可能列見出しが既定の
  青字＋下線（ブラウザの`<a>`既定スタイル）で表示されていた件、原本HTML・xlsxいずれにも
  これら3画面のソート機能自体が存在しない（`HTML_REIMPL_CHECKLIST.md`「職員マスタ一覧に、
  原本には無い列見出しソート機能が追加されている」の通り、検索画面と同じ全社的パターンとしての
  独自拡張）ため、色の原本指定も無いことを確認。検索画面（`.result-table`）の
  `.sort-link`は`django_widgets.css`で既にリンク色・下線を打ち消し済みだったが、
  `.data-table`/`.data-table-auth`（職員マスタ・部署管理・権限管理）側は対象外のままだった。
  ユーザー指示（「指定が無ければ検索画面側と揃えて」）により、`.result-table th`への
  スコープ限定をやめて`a.sort-link`全体に適用するよう変更し、3画面とも検索画面と同じ
  地の色・下線無しの見た目に統一した。
- [x] 検証：全体テストスイート**259件PASS**、ブラウザで`getComputedStyle`により
  修正前`rgb(0,0,238)`+下線→修正後`rgb(51,34,17)`（地の文字色）+下線無し、を確認

## 検索・閲覧画面/第二陣一覧の列見出しソート不具合修正・第三陣への追加（2026-08-17）

ユーザー報告「検索結果一覧で列ソートのNoで番号が変わらない、保存情報のソートがおかしい」を
発端に、検索画面・第二陣・第三陣の一覧すべての列見出しソートを横断点検・修正した。

### 検索・閲覧画面（documents/contracts）
- [x] `documents/contracts/search_services.py`の`apply_sort()`。「No.」列は`sort_key="no"`の
  昇順方向が既定表示順（保存日が新しい順）と同じ並びになってしまい、初回クリックで見た目が
  一切変化しない不具合があった。また「保存情報」列は表示（部署名/年/カテゴリー）と無関係な
  `department__branch_code`のみで近似ソートしており、「保管・更新者」列も表示（部署名｜氏名）と
  無関係に氏名のみでソートしていた。「保存期間」列（文書のみ）も表示文字列ではなくPK
  （`retention_period_id`、作成順）でソートしており、`masters.RetentionPeriod.display_order`
  （画面上の意図した並び順）と無関係だった。
- [x] いずれも表示されている値と一致する複合ソートに修正（保存情報→部署名/年/カテゴリー名、
  保管・更新者→部署名/氏名、保存期間→`display_order`）。
- [x] 「No.」列はさらにユーザー指摘「番号自体が変わらない」を受け、原本`sortTable()`が
  DOM行を並べ替えるだけで各行のNo.セルの値自体は書き換えない（＝番号が行についてくる）挙動を
  忠実に再現するよう作り直した。`ROW_NUMBER() OVER (ORDER BY save_date DESC)`をウィンドウ関数で
  各行に一度だけ付与（`display_no`）し、その値を昇順/降順でそのまま数値比較する
  （＝原本`sortTable(1,'num',btn)`と同じ処理）。ユーザー指示「原本に合わせる原則を維持して」を
  受け、いったん独自に発明した「昇順＝保存日の古い順」という向き付けを廃止し、原本通り
  「昇順＝display_no昇順（＝既定表示順と一致、行番号を行番号で並べ替える以上自然な結果）、
  降順＝その逆順」に統一した。

### 第二陣（職員マスタ・部署管理・権限管理）
- [x] 職員マスタ一覧・部署管理一覧のソート対象列は表示列と1対1で対応しており問題なし。
- [x] 権限管理一覧の「部署」列（`employee.department`＝本支所名｜部課名を表示する単一列）が
  `department__section_code`のみでソートされ、本支所をまたぐと表示と無関係な順序になる
  不具合を発見。xlsx 権限管理!I54「※部署名ではなく、部課コードで昇順/降順…(本支所コード+
  部課コードの5桁にて)」の通り、本支所コード→部課コードの複合ソートに修正
  （`permissions/services.py`）。
- [x] **旧記載の訂正**：本チェックリスト「保存期間設定ラジオボタン位置・一覧ソートリンク色の
  修正（2026-08-13）」に「職員マスタ一覧・部署管理一覧・権限管理一覧のソート機能自体は原本
  HTML・xlsxいずれにも存在しない」と記載していたが、これはHTMLモック（`sortTable()`）のみを
  確認した結果で誤りだった。簡易設計指示書xlsxの職員マスタ!B56、部署管理!B52、権限管理!B52に
  「・下記項目に▲▼ボタンにて昇順/降順切替が可能なようにする。(文書検索画面の一覧表示部と
  機能同等)」と明記されており、対象列（職員マスタ：職員番号/氏名/本支所コード/部課コード/
  職階コード/役職コード、部署管理：本支所コード/本支所名/部課コード/部署名、権限管理：
  職員番号/部署/氏名/役職/権限）も本実装の`STAFF_SORT_FIELDS`/`SORT_FIELDS`/
  `AUTHORITY_SORT_FIELDS`と完全一致していた。原本には無い独自拡張ではなく、xlsx仕様の
  正しい実装だったと判明したため訂正する。

### 第三陣（分類管理・カテゴリー管理）への▲▼ソート追加
xlsxの記述に合わせ、▲▼ボタンでのソートが明記されている画面にのみ追加した（ユーザー指示
2026-08-17）。保存期間設定・操作履歴ログ・その他設定は「初期ソート順」の記載のみで
「▲▼ボタン」の記述が無いため対象外（xlsx各シートB40-55台を確認）。
- [x] 分類管理一覧（`class_list.html`）：分類コード・分類名・文書件数の3列に追加
  （xlsx 分類管理!B55-58）。
- [x] カテゴリー管理一覧（`cat_list.html`）：カテゴリーコード・分類・文書件数の3列に追加
  （xlsx カテゴリー管理!B57-61）。xlsxは「分類コード」「分類名」を別項目として列挙しているが、
  一覧画面（原本HTML・本実装とも）には分類コードを表示する専用列が無く、分類名のみを表示する
  単一の「分類」列しか存在しない（新しい列を追加すると原本の画面構成から逸脱する）。そのため
  この「分類」列のソートは分類コード→分類名の複合キーとして扱い、xlsxが列挙する2つの並び替え
  基準を1つの列見出しで両立させた（`masters/views.py` `CategoryListView` docstring参照、
  documents/contracts検索の「保存情報」列と同じ複合ソートパターン）。
- [x] 「文書件数」列は書類管理区分(doc_kbn)に応じてdoc_count/contract_countのどちらを表示するか
  切り替えている（テンプレート側の`{% if %}`分岐）ため、ソート対象も表示値と一致するよう
  `Case`式で一本化した`item_count`アノテーションを新設した。
- [x] 副産物として発見・修正：分類管理・カテゴリー管理とも、初期ソート順の書類管理区分
  （xlsxが「文書管理、契約書管理の順」と明記）を`order_by("doc_kbn", ...)`で実装していたが、
  `doc_kbn`の実値は`"document"`/`"contract"`の文字列のため昇順ソートすると`"contract"`が
  先に来てしまい、xlsxの指定と逆順になっていた。`Case`式で文書管理=0/契約書管理=1に読み替えて
  修正（`_DOC_KBN_ORDER`）。また分類コード/カテゴリーコードがそれぞれDB制約で常に一意のため
  実際にはこの書類管理区分による同着は発生し得ず、回帰テストは書けない（コード自体は
  xlsx記載への忠実な実装として残す）。
- [x] 検証：`python manage.py test`**275件PASS**（新規テスト16件追加：documents 6件、
  contracts 1件、permissions 1件、masters 2件、うち本エントリの第三陣追加分は2件）。
  開発サーバーでブラウザ実機動作確認済み（分類管理一覧の文書件数ソート昇順で
  3→6→7→27の順に並び替わることを確認）。

## 職員マスタ登録・編集画面：職階・役職のコード表示欠落を修正（2026-08-18）

- [x] ユーザー指摘で発見：`templates/accounts/staff_regist.html`/`staff_edit.html`は
  本支所・部課には原本index.html `updateCode()`（1977〜2001行目付近）と同じ
  `<span class="ctg-code-area">`（選択したコードを表示するエリア）＋`<span class="ctg-name-area">`
  （selectそのもの）の構成をJS連動込みで実装していたが、職階・役職の行だけ
  `{{ form.rank }}`/`{{ form.position }}`を素で置いているだけで、コード表示エリアも
  変更時のJS連動も存在せず、選択肢のラベル（例:「考査役」）しか見えずコード（例:「20」）が
  画面上のどこにも表示されない状態だった。
- [x] `accounts.models.Rank`/`Position`は専用マスタ画面が無くDjango choicesの固定値のため
  （本支所/部課のような動的な連動選択とは異なり）、両テンプレートに`code-rank-*`/`code-pos-*`の
  `ctg-code-area`スパンを追加し、`change`イベントで選択値をそのままテキスト表示する
  `wireCodeDisplay()`をextra_scriptに追加。編集画面は初期表示時点で既存値が選択済みのため、
  ページ読み込み直後にも一度実行して初期コードを表示させた。
- [x] 検証：開発サーバーで職階=25/役職=40への変更、既存職員（職階20/役職16）の編集画面初期表示、
  変更後の再連動をJS経由で確認。`python manage.py test accounts`23件PASS。

## 第二陣・第三陣一覧画面への総件数表示追加（2026-08-18）

- [x] 職員マスタ一覧(xlsx B68)・部署管理一覧(B62)・権限管理一覧(B65)・分類管理一覧(B64)・
  カテゴリー管理一覧(B67)・操作履歴ログ(B61)・その他設定メイン画面項目タブ(B48)の7画面とも
  xlsxで「一覧表右上辺りに、総件数を表示すること」が明記されているにもかかわらず、原本HTML
  自体に総件数表示欄が無く（SCREENS_INVENTORY_WAVE2.md職員マスタ/部署管理/権限管理の項目に
  「※HTML上に総件数表示欄は無い」と既に記録済み）、本Django実装でも未反映のまま残っていた
  ことをユーザー指摘で発見。第一陣の検索画面（`templates/documents/search.html:74`
  `{{ page_obj.paginator.count }} 件`）と同じパターンで、各一覧のテーブル直上に
  `総件数：N 件`を追加した。
- [x] 部署管理一覧のみPaginator不使用（xlsx B60「ページャーは不要」のためDeptListViewが
  `departments`を全件表示、`page_obj`を持たない）。総件数は`{{ departments|length }}`で
  クエリセットを1回評価してそのままテンプレートのループにも再利用させ、二重クエリを避けた。
- [x] その他設定は「メイン画面項目」「自動ログアウト時間」の2タブをJSで切り替える単一画面
  （`core/other_main.html`）。総件数表示・ページャーとも一覧のあるメイン画面項目タブ専用の
  要素のため、既存の`kbnSelectForOtherSettings()`にタブ切替時の表示/非表示トグルを追加し、
  ページャーと同じ挙動にした。
- [x] 検証：開発サーバーでadminロールの検証用一時アカウントを作成しブラウザ実機確認
  （職員マスタ6件・部署管理4件・権限管理7件・分類管理4件・カテゴリー管理4件・
  操作履歴ログ682件・その他設定4件、いずれも一覧の実件数と一致。その他設定はタブ切替時に
  総件数表示とページャーが連動して非表示になることも確認）。確認用アカウントは検証後削除済み。
- [x] 配置の追加調整（ユーザー指摘：画面右端でなく一覧表の右上に、ボタン行があれば改行せず
  同じ行に）。職員マスタ・部署管理・分類管理・カテゴリー管理は`action-bar`（新規登録等の
  ボタン行）を`justify-content:space-between`にし、ボタン群と総件数を同じ行の左右に配置。
  さらにその行と一覧表本体を`display:inline-block; max-width:100%;`の共通ラッパーで包み、
  ラッパーの横幅を一覧表の実際の描画幅にshrink-to-fitさせることで、ボタン行の右端＝一覧表の
  右端に一致させた（block要素はshrink-to-fitした親の解決済み幅いっぱいに広がる性質を利用）。
  action-barが無い権限管理・操作履歴ログ・その他設定（メイン画面項目タブ）は総件数表示単体を
  同じラッパーで一覧表と束ね、テーブル直上・右端揃えにした（権限管理のみ横スクロールする
  幅広テーブルのため、可視領域＝スクロールコンテナの右端に揃う）。ブラウザの
  `getBoundingClientRect()`で7画面とも総件数の右端と一覧表（またはボタン行）の右端が一致する
  ことを確認済み。

## 保存期間設定削除を物理削除から論理削除へ変更（2026-08-19）

- [x] `masters.RetentionDeleteView`はxlsx B146/B271「保存期間マスタから論理削除とする」が
  明記されているにもかかわらず、`RetentionPeriod`モデルにフェーズ2設計時点で`is_deleted`
  フィールドが存在せず、「documents/contracts側のretention_period外部キー(on_delete=PROTECT)
  で参照されていなければ物理削除、参照中なら`ProtectedError`を捕捉してエラーメッセージ表示」
  という代替実装で妥協していた。分類管理(`Group`)・カテゴリー管理(`Category`)は既に同じ
  パターンの論理削除を実装済みだったため、ユーザー指摘によりこちらも揃えることにした。
- [x] `RetentionPeriod`に`is_deleted`（既定False）を追加。`unique_retention_display_order`
  制約もGroup/Category同様`condition=Q(is_deleted=False)`にし、論理削除済みの
  kbn/doc_name/表示順の組み合わせを再利用可能にした（マイグレーション
  `masters/migrations/0003_retentionperiod_is_deleted.py`）。
- [x] `RetentionListView`・`RetentionEditView`・`RetentionDeleteView`（一覧・編集の
  `get_object_or_404`、削除確認画面の「No.」計算）に`is_deleted=False`条件を追加。
  `RetentionPeriodForm.clean_display_order`の重複チェックも同様。
- [x] `documents.forms`の`retention_period`（保管画面２/編集画面共用のUploadStep2Form、
  検索画面のSearchForm）の`ModelChoiceField`querysetにも`is_deleted=False`を追加し、
  Group/Categoryと同じく削除済みの選択肢を新規選択できないようにした（既存文書が
  削除済みの保存期間を参照している場合の編集時の扱いも、Group/Categoryで既に許容している
  挙動と同じ）。
- [x] `RetentionDeleteView.post`は`period.delete()`+`ProtectedError`捕捉から
  `period.is_deleted = True; period.save(update_fields=["is_deleted"])`に変更。論理削除は
  行自体を消さないため参照整合性を壊さず、`ProtectedError`のハンドリング自体が不要になった
  （`masters/views.py`の未使用importも削除）。
- [x] `masters/tests.py`の`test_retention_period_referenced_by_document_cannot_be_deleted`を
  `test_retention_period_referenced_by_document_can_be_logically_deleted`に更新し、
  参照中でも論理削除が成功し、既存文書の参照はそのまま残ることを検証する内容にした。
  `python manage.py test`（全283件）で確認済み。

## 原本HTML/xlsx Rev1.1改訂の反映（2026-08-19）

原本が`HTML/html2`→`HTML/html3`（Rev1.1、印刷枠外の"Rev1.1"表記で変更箇所を明示）に改訂され、
xlsxも`Rev1_0`→`Rev1_1`に改訂された。html1→html2の時（本ファイル481行目）と同じく、まず
`diff html2/index.html html3/index.html`・`diff html2/style.css html3/style.css`、および
openpyxlでのRev1_0/Rev1_1セル単位比較・埋め込み画像抽出（xlsxの一部シートは表がセル値ではなく
画像として貼り付けられており、単純なセルテキスト比較では検出できない）で機械的に差分を洗い出し、
そこから実装対象を特定した。作業前に`git tag backup/before-rev1.1-20260819`でバックアップを
取得済み。今回はhtml1→html2と異なり非常に広範囲（ほぼ全アプリ）の改訂だったため、変更点をまとめて
記録する。

- [x] **共通JS/CSS**: `common.js`の`openPopupPopup()`にポップアップが画面右端からはみ出す場合の
  左方向スライド補正を追加。`style.css`の`.col-3〜5`/`.col-td-3〜5`（権限管理一覧の固定列offset）
  を2px縮小。
- [x] **ページネーション**: 職員マスタ・権限管理・分類管理・カテゴリー管理・操作履歴ログ・
  その他設定（メイン画面項目設定）・文書検索・契約書検索の`PAGE_SIZE`を全て50→100件に変更。
- [x] **氏名検索のフルネーム対応**: `core.text_normalization.filter_by_full_name`を新設し、
  氏名フィールドの全角/半角スペースを除去した上でicontains比較する共通ロジックに統一
  （職員マスタ・権限管理・操作履歴ログの氏名検索で共有）。
- [x] **職員番号**: `StaffRegistForm.clean_employee_no`でNFKC正規化により全角→半角数字変換、
  数字以外はエラー、"0000"（管理者用）も許可するよう変更。
- [x] **部署名表示から本支所名プレフィックス撤去**: `Department.__str__`を
  `f"{branch_name}|{section_name}"`から`section_name or branch_name`に変更（部課が無い部署は
  従来通り本支所名のみ）。権限管理一覧・詳細、その他設定メイン画面一覧等、`str(department)`に
  依存する全箇所に反映。
- [x] **分類管理検索**: `GroupSearchForm.name`をプルダウン（`ChoiceField`）からテキスト部分一致
  検索（`CharField`、`CategorySearchForm`と同じ方式）に変更。
- [x] **分類コード/カテゴリーコードの数字限定**: `GroupForm`/`CategoryForm`の`clean_code`に
  NFKC正規化による全角→半角変換＋数字以外拒否のバリデーションを追加。
- [x] **監査ログ検索**: `AuditLogSearchForm`に「職員番号」（完全一致）フィールドを追加。
  「イベントメッセージ」をスペース区切りAND検索に対応（`filter_audit_log_queryset`）。
- [x] **パスワード変更**: `OtherPassForm`に半角英数6桁以上のバリデーション、現在のパスワードと
  同一の場合のエラーを追加。テンプレートに「(半角英数6桁以上)」のヒント表示を追加。
- [x] **メイン画面ボタンの表示制御**: 「×は押下不可(disabled)」から「×は非表示」に変更。
  `organizations.MenuItemSetting`（既存モデルだが従来メイン画面側で未使用だった）を`MenuView`が
  参照し、部署ごとの検索・保管ボタンをテンプレート側`{% if %}`で表示/非表示に切り替えるよう
  新規に配線した（電子決裁ボタンは実画面が無いため恒久的に非表示のまま）。
- [x] **削除・ダウンロードボタンの非表示化**: 文書/契約書のダウンロードボタン（検索一覧の
  一括ダウンロード、詳細ポップアップ）を権限なし時disabled表示から非表示に変更。削除ボタンは
  「保存から1週間経過で削除不可」というxlsx記載の制限（従来コードに存在しなかった）を
  `documents/contracts.services.can_delete`として新規実装し、期限超過時はサーバー側
  （`DeleteView.post`）でも拒否した上でボタン自体を非表示にする。
- [x] **部署の統合・分割機能**: 従来UI（ラジオ+対象部署ポップアップ）はあったが
  `DeptEditForm.clean()`が常に`ValidationError`でブロックする未実装状態だった。Rev1.1で
  「削除ではなく閲覧部署範囲テーブルを更新する」という仕様が確定したため、新規モデル
  `organizations.DepartmentViewScope`（viewer_department/visible_department/action）と
  `organizations.services.apply_dept_action`/`visible_department_ids`を追加し、実際に機能する
  ようにした。documents/contracts検索の非管理者向け部署フィルタ・検索フォームの部署初期値にも
  この統合/分割スコープを反映する（xlsx 検索・閲覧・変更!B48,417-418「閲覧部署範囲テーブルを
  参照し...自動セットする」）。
- [x] **permissionsアプリの大規模再設計**（xlsx 権限管理!B8「画面変更」）:
  - 詳細画面（`screen-authority-detail`/`AuthorityDetailView`）を廃止。原本HTML自体も
    この画面への遷移ボタンが無くなり到達不能な死んだマークアップとして残るのみだったため、
    「モックとして壊れている箇所は再現しない」方針に従い削除した。一覧の「詳細」ボタンは
    「編集」ボタンとして`AuthorityEditView`に直接遷移する。
  - `PermissionProfile`から部署・事業所/カテゴリー単位の「作成・変更・削除」権限
    （`doc_department_edit`/`doc_group_manage`/`doc_category_manage`とその契約書側計6項目）、
    「所属長への権限付与」「職員への権限付与」（doc/contract各2項目、計4項目）、文書側の
    「部門間閲覧設定」（`doc_cross_department_view`）を削除（マイグレーション
    `permissions/migrations/0002_...`）。これらはシステム権限プルダウン1段階（管理者/所属長/
    一般）に統一され、`can_manage_target`（既存実装がそのまま新仕様と合致）で制御する。
  - 契約書側の「部門間閲覧設定」を真偽値`contract_cross_department_view`から複数選択
    `contract_visible_departments`（M2M、doc_visible_groups等と同じ「選択」ポップアップ方式）に
    変更。`permissions.services.can_select_department(kind="contract")`・
    `contract_searchable_department_ids`を新設し、対象部署に限定した検索・閲覧を可能にした
    （documents側は従来通り管理者のみで非対称、Rev1.1の仕様通り）。
  - 新規権限「文書管理-文書-保存満了日変更」（`doc_retention_edit`）を追加。OFFの場合、
    `documents.forms.UploadStep2Form`（`edit_mode=True`時のみ）で`retention_period`フィールドを
    disabled化し、保存済み文書の保存期間を編集できないようにした
    （`permissions.services.can_edit_retention`）。
  - CSV出力・一覧・編集画面のテンプレートを新しい9項目構成（文書管理3・契約書3・電子決裁3）に
    全面書き換え。一括許可/一括無許可ボタンは、無許可にした際に「選択」系3項目
    （doc_visible_groups/contract_visible_departments/contract_visible_groups）もクリアする
    仕様（xlsx B119-123）をJS側で追加。
  - `core.api.BaseOptionListAPIView`の部署選択ポップアップに`department_kind`を追加し、
    document/contract/organizations（部署統合・分割は全部署対象、無制限）で挙動を分けた。
    `permissions.api.OptionListAPIView`に`type=dept`対応を追加（`contract_visible_departments`
    の選択ポップアップ用、他職員への権限付与という性質上、閲覧者自身の検索範囲とは無関係に
    全部署を選択肢にする）。
- [x] **職員マスタCSV取込機能を新規実装**: xlsxのCSVレイアウトは実はセル値ではなく埋め込み画像
  として存在しており（`HTML_REIMPL_CHECKLIST.md`旧版の「表が実在しないため実装見送り」との
  記載は誤りだった。openpyxlでシートの`_images`を走査して発見）、Rev1_0の時点で既に存在し
  Rev1.1で「所属長フラグ」列が追加されていた。`accounts.csv_import_services.import_staff_csv`
  として新規実装：職員番号での突合、部課コード"99"での退職扱い、氏名のみ変更時の更新、
  部課/役職/職階変更時の権限リセット（`reset_permission_profile_if_needed`再利用）、
  新規職員の初期登録（パスワード`ja`+職員番号下4桁、PermissionProfile初期値）、部署マスタの
  自動生成・更新、所属長フラグ"1"時のシステム権限「所属長」への更新（既に管理者の職員は
  降格させない）。1行の処理失敗は他行を止めず`ImportSummary.errors`に集積する。
  `screen-staff-list`のCSV取込ボタン（従来disabled固定）から実際にアップロードできるようにした。
- [x] 上記に伴い`CLAUDE.md`「既知の未実装・保留事項」を更新（CSV取込は実装済みに、権限管理の
  「連動仕様の大半が未実装」という記載はRev1.1で大半が解消されたため電子決裁3フラグのみに縮小）。
- [x] `python manage.py test`（全333件）PASS、`manage.py check --deploy`（prod設定）で
  新規の警告無し確認。

## Rev1.1反映の過剰実装を原本一致に戻す・見落とし修正（2026-08-19）

上記Rev1.1反映後、ユーザーから「差分実装前は完全に原本一致だったレイアウトが変わった」との
指摘を受け、html3/index.html・style.cssとの1行単位フィデリティ監査を実施した。原因は、
xlsxの文言（○△×等の説明文）を字面通りに解釈し、原本HTML自体には存在しない動的な連動を
新規に作り込んでしまったことだった。原本HTML（screen-menu、popup-detailの各ボタン）は
いずれも静的モックで、権限や経過日数による表示/非表示の条件分岐を一切持たない
（電子決裁ボタンのdisabled等、既存の恒久的スコープ外のものを除く）。以下を原本通りに戻した：

- [x] **メイン画面のボタン表示制御を撤回**: `organizations.MenuItemSetting`と`core.MenuView`を
  連動させ、部署ごとに検索・保管ボタンを表示/非表示にする実装を追加していたが、未設定部署では
  全ボタンが消えてしまい、原本（常時表示の静的モック）と大きく乖離していた。`menu.html`・
  `core/views.py`・`core/tests.py`を元の「常時表示」に戻した（`MenuItemSetting`モデル自体・
  screen-other-main-editでの設定保持機能は維持、メイン画面への連動のみ撤回）。
- [x] **文書/契約書の削除ボタン「保存から1週間経過で非表示」を撤回**: `documents/contracts.
  services.can_delete`・関連する`DetailAPIView`のdelete_url制御・`DeleteView.post`のサーバー側
  拒否・`common.js`のボタン非表示化を全て削除した。原本の`openDetailPopup()`モックはこの制御を
  一切持たず常に削除ボタンを有効表示しており、この制限は当該Rev1.1反映で新規に作り込んだもので
  差分実装前のコードにも存在しなかった（実際に既存の擬似データの大半で削除ボタンが消える
  副作用が発生し、ユーザー報告で発覚）。
- [x] **ダウンロードボタンの「非表示」化を「押下不可(disabled)表示」に戻す**: 削除ボタンと同様の
  理由に加え、ダウンロード権限が無い場合の制御自体は差分実装前から存在した既存機能のため、
  スタイル（disabled表示⇔非表示）のみ差分実装前の状態に戻した
  （`documents/contracts/search.html`、`common.js`のdlBtn制御）。
- [x] **文書/契約書の詳細ポップアップに「保存者」「保存日時」が無い不具合を修正**：Rev1.1で
  原本`openDetailPopup()`モックに追加された項目（index_diff20260819で検出済みだったが、当初の
  実装作業で対応漏れしていた）。`documents/contracts.api.DetailAPIView`のレスポンスに
  含まれていた`uploader`/`save_date`は元々JSONに存在したが`common.js`の`renderDetailPopup()`が
  行として描画していなかった。両詳細ポップアップに「保存者」「保存日時」の行を原本と同じ位置
  （文書：個人情報の次／契約書：契約先名の次）に追加。`save_date`はAPI側でも
  `timezone.localtime().strftime("%Y-%m-%d %H:%M:%S")`に整形して返すよう変更した
  （原本表示例"2026-01-20 09:34:06"に合わせる）。
- [x] **契約書の保管・編集画面に「保存期間」欄が無い不具合を修正**：この欠落自体は今回のRev1.1
  反映が原因ではなく、契約書は保存期間が選択式ではなく`settings.CONTRACT_RETENTION_YEARS`
  （既定10年）固定という既存の設計（`contracts.services.calculate_expiry_date`docstring参照）
  のため、画面上に一切表示されていなかった。原本index.html:240の`storage-period-row`は文書・
  契約書共通のマークアップで契約書モードでも表示されるため、`contracts/storage2.html`・
  `contracts/edit.html`の[2]文書情報セクションに「保存期間」の読み取り専用表示
  （`contract_retention_years`、選択式ではないため`<select>`ではなくテキスト表示）を追加した。
  `ContractEditView`・`UploadStep2View`（contracts）の該当render()呼び出し6箇所に
  `contract_retention_years`をcontextとして追加。
- [x] 上記の1週間削除制限に関するユニットテスト（`DeleteViewWindowTests`等）を削除し、
  `python manage.py test`（全324件）PASSを確認。ブラウザ実操作（Chrome preview経由）で
  削除ボタン・保存者/保存日時・契約書の保存期間表示が原本通り機能することも確認済み。

**教訓**: xlsxの文言変更（Rev1.1マーカー）は「何が変わったか」の手がかりに過ぎず、実装の
要否・粒度は必ず原本HTML（実際にレンダリングされるマークアップ）と突き合わせて判断すること。
xlsxの説明文だけを根拠に、原本HTMLに存在しない動的挙動を新規に作り込まない
（原本フィデリティ運用方針に「原本のJS自体がモックとして壊れている箇所は再現しない」とあるのと
表裏の原則：逆に「原本が実装していない動的制御を勝手に足さない」も同様に重要）。

### 訂正：「削除ボタン・1週間経過制限」は再実装（同日）

上記で撤回した「文書/契約書の削除ボタン、保存から1週間経過で非表示」について、ユーザーより
「初回登録から1週間以上経過しているものは削除不可。ボタンを非表示にする。」は原本xlsx
（保管!B300,B581・検索・閲覧・変更!B339-340,B664-665）に明記された実仕様であり反映すべき、との
指示を受けた。撤回時の判断（原本HTMLモックが動的挙動を持たないことを理由に不要と結論づけたこと）
は誤りで、この制限自体は独自解釈ではなくxlsxに明記された仕様そのものだった。`documents/
contracts.services.can_delete`・`DetailAPIView`のdelete_url制御・`DeleteView.post`のサーバー側
拒否・`common.js`のボタン非表示化（`style.display`、xlsxの「非表示にする」という文言通り）を
全て再実装し、対応するユニットテスト（`DeleteViewWindowTests`等）も復元した。
`python manage.py test`（全332件）PASS確認済み。

メイン画面ボタンの動的表示制御・ダウンロードボタンの「非表示」化撤回については、ユーザーから
再実装の指示が無いため撤回した状態のまま維持している（電子決裁機能自体が存在しないメイン画面の
ケースは原本にも根拠が無く、ダウンロードボタンは差分実装前からdisabled表示だったため）。

### 訂正：契約書の「保存期間」表示追加は誤りのため取り消し（同日）

上記「契約書の保管・編集画面に保存期間欄が無い不具合を修正」は誤りだった。原本index.html:611の
`transitionToStorage(moduleType)`関数を確認したところ、`moduleType === 'contract'`の分岐で
`rowPeriod.style.display = "none";`と明示的に保存期間欄を非表示にしている（文書モードでは
`"flex"`で表示）。screen-storage2は文書・契約書で共有する1つのHTML断片だが、JSがモードに応じて
動的に出し分けており、契約書モードでは保存期間欄が原本でも常に非表示という仕様だった。静的な
マークアップ（`<div id="storage-period-row">`が無条件に存在すること）だけを見てモード切替JSを
見落としたのが原因。`contracts/storage2.html`・`contracts/edit.html`に追加した保存期間の
読み取り専用表示、および`contracts/views.py`の該当render()呼び出し6箇所に追加していた
`contract_retention_years`をすべて削除し、元の状態（保存期間欄なし）に戻した。
`python manage.py test`（全332件）PASS確認済み。

**教訓（重ねて）**: 原本HTMLの1画面が複数モード（文書/契約書等）で共有されている場合、静的な
マークアップだけでなく、モード切替時にJSが要素を動的に表示/非表示・書き換えする箇所
（`transitionToStorage()`等のモード分岐関数）まで必ず確認すること。

## 実装とxlsx Rev1.1全文の突合監査・実装漏れ修正（2026-08-19）

上記の差分実装・原本一致修正が一段落した後、「実装とxlsx Rev1.1に照らし合わせて差異はないか」を
xlsx全13シート（表紙・目次・(ひな形)を除く）に対して網羅的に監査した。openpyxlで全シートのセル
テキストをファイルに抽出した上で、シート単位に分割して7件の独立したバックグラウンド調査エージェント
（結果報告のみ、修正はしない）に並行調査を依頼し、各エージェントには本ファイルに記録済みの教訓
（「xlsxの文言だけを根拠に、原本HTMLに存在しない動的挙動を新規実装すべきと判断しない」
「1画面が複数モードで共有されている場合はJSのモード分岐関数まで確認する」）を明示的な留意事項として
共有した。7件の報告を「確度の高い実装漏れ」「判断が必要な項目」「低優先」の3群に分類し、後者2つは
ユーザーに確認の上で対応方針を決定した。

### 判断が必要だった3項目（AskUserQuestionで確認）
- 分類コード/カテゴリーコード（`masters.Group`/`Category.code`）の一意性スコープ：原本サンプル
  データでは同じコードが文書管理/契約書管理の`doc_kbn`をまたいで再利用されていたが、現状の
  グローバル一意制約（`UniqueConstraint(fields=["code"], condition=Q(is_deleted=False))`）を
  維持する方針を確認。**対応不要（現状維持）**。
- 操作履歴ログの保存件数上限・CSV出力の最大対象期間設定：xlsx記載はあるが、今回は実装を見送る
  方針を確認。**対応不要（見送り）**。
- 職員編集画面「退職」チェックボックスのラベル：原本index.html:2130の表記「退職(使用不可)」に
  ラベルのみ合わせ、機能（チェックボックス自体の有効/無効）は変更しない方針を確認。
  → `accounts/forms.py`の`StaffEditForm.Meta.labels`を修正（実装済み、後述はしない軽微な変更）。

### 確度の高い実装漏れ7件（Tasks 15-21として全て実装・テスト済み）

1. **本支所→部課連動プルダウンを検索パネルに追加**（xlsx 職員マスタ!B38、部署管理!B38）：
   職員マスタ一覧・部署管理一覧の検索パネルで、本支所を選択しても部課プルダウンの選択肢が
   絞り込まれていなかった（登録/編集画面のupdateSections()相当のJSが検索パネルには無かった）。
   `organizations.services.departments_json()`（accounts側の旧`_departments_json()`から移設、
   accounts/organizations両方で共用）を`accounts.views.StaffListView`・
   `organizations.views.DeptListView`双方のcontextに追加し、`staff_list.html`/`dept_list.html`に
   同じ構造の`updateSectionOptions()` IIFEを追加した。
2. **検索パネルの部課プルダウンから退職(99)を除外**（xlsx 職員マスタ!B41、部署管理!B45
   「(但し部課コード99の退職者は対象外)」）：`accounts.forms.StaffSearchForm`・
   `organizations.forms.DeptSearchForm`双方の部課選択肢生成に
   `.exclude(section_code=RETIRED_SECTION_CODE)`を追加。
3. **文書検索の保存期間プルダウンを実データ抽出に変更**（xlsx 検索・閲覧・変更!B182-184
   「保存済み全文書に紐付けられている保存期間を重複なしで抽出し、プルダウン化する。
   (リストは日数の短い順から昇順で生成)　※「保存期間設定」で設定したデータは使用しない」、
   要再確認No.19として2026-08-07時点で赤字指定されていた項目でもある）：
   `documents.forms.SearchForm.retention_period`が`masters.RetentionPeriod`マスタの全件
   （表示順ソート）を選択肢にしていたのを、`documents.services.used_retention_periods()`
   （新規、ゴミ箱を除く保存済み`Document`に実際に紐付いている`RetentionPeriod`のみを、
   月=30日・年=365日・永年=最大値の近似日数でソートして返す）に差し替えた。
4. **年選択ポップアップ・検索パネルの年選択肢を実データ範囲に変更**（xlsx 検索・閲覧・変更
   !B137-140「対象年選択は…今年～文書が保存されている最古の年」、B499で契約書も同一規則）：
   `core.api.BaseOptionListAPIView._year_items()`・`documents/contracts.forms.SearchForm`の
   `year`選択肢が「今年+1年～今年-10年」の固定12年ハードコードだったのを、
   `core.forms.search_year_choices(kind)`（新規、documents/contracts双方の`is_deleted=False`
   レコードの最古`year`を集計）に統一した。
5. **保管画面２の部署欄、管理者への初期値設定**（xlsx 保管!B78-82「部署名欄の初期値はログイン
   ユーザーの部署名をセット」・B412-416「※保管画面(文書)と同じ」）：従来は非管理者のみ
   `department`の初期値を自部署にセットしており、管理者は新規登録時に部署欄が空のまま
   だった。`documents/contracts.forms.UploadStep2Form.__init__`に、新規登録（`edit_mode=False`）
   時は権限に関わらず`self.initial["department"] = employee.department_id`を設定するelse分岐を
   追加した。編集画面（`edit_mode=True`）は既存文書/契約書の部署をview側（`_build_form`）が
   `initial=`で渡すため上書きしない（上書きすると年欄で既に修正済みの「触れていないのに値が
   書き換わる」のと同種の事故になる。`contracts.views.ContractEditView._build_form`には
   `edit_mode=True`の指定が漏れていたため合わせて追加した）。なお`self.initial[...]`への代入は
   `self.fields[...].initial`への代入と異なりForm側の`initial=`引数より優先解決される
   （`Django BaseForm.get_initial_for_field`）ため、非管理者の自部署強制も同じ書き方に統一した。
6. **can_downloadに管理者の無条件許可を追加**（xlsx 権限管理シートの「※管理者は、所属長及び
   職員に対して設定する」という記述から、管理者は権限設定の対象ではなく設定する側と解釈し、
   `can_select_department`/`can_edit_retention`と同じ前例に揃えた）：
   `permissions.services.can_download`に管理者ロールの無条件`True`を追加。
7. **権限管理一覧の既定ソート順にbranch_codeを追加**（他の一覧画面と同じ「本支所→部課」の
   複合ソート順に統一）：`permissions.services.filter_authority_queryset`の既定ソート分岐に
   `department__branch_code`を`department__section_code`より前に追加。

全項目にユニットテストを追加し、`python manage.py test`（全347件）PASS確認済み。

### 要再確認（赤字）箇所リストの更新
- No.19（`B184`検索・閲覧・変更「保存期間設定で設定したデータは使用しない」）は上記3.で解消。

## 原本HTML改訂差分の確認（html3→html4）・検索結果一覧 一括編集の実装（2026-08-20）

原本が`HTML/html3`→`HTML/html4`に改訂された。html1→html2の時（本ファイル529行目）と同じ手順で、
`HTML/html4/index_diff20260820.html`（WinMergeレポート）による機械的な差分洗い出しを実施。
`style.css`は無変更（`diff html3/style.css html4/style.css`で確認）、`index.html`の唯一の
差分として、検索結果一覧「一括編集」ボタンに初めてモックJSが追加されたことを確認した。これまでは
「対象項目・共通値の適用範囲がHTML/xlsxいずれにも未定義のため未実装」として`disabled`のまま
残していた（上記「フェーズ8後の追加改善」参照）。簡易設計指示書(xlsx)側はhtml4に対応する追加
改訂を受領しておらず、Rev1_1のまま。

原本モックJSの意図：検索結果一覧でチェックボックス選択→「一括編集」→保管画面２相当の編集
フォームを選択件数分、ページャー（＜ ＞）で1件ずつ表示→各ページで内容編集→最後の「更新」で
まとめて完了ポップアップに全件表示、という「複数レコードを順番に編集するウィザード」。

**原本モックをそのまま再現しなかった点（原本フィデリティ運用方針に基づく判断）**:
1. 原本が新規に定義した`changeActiveDoc(direction)`（一括編集のページャー用）が、保管画面の
   複数ファイル同時アップロード時に既に使われている同名関数`changeActiveDoc(dir)`
   （`storage2.html`の登録前ページャー）を完全に上書きして壊す不具合を持っていた。文字通りの
   再現はせず、そもそも本実装はクライアントJSのページャーを追加しないサーバーサイドPRG方式
   にしたため、この衝突自体が発生しない設計にした。
2. 原本は検索結果テーブルのtd列を決め打ちインデックスで文字列スクレイピングし、
   `"総務部"`/`"3年"`等をハードコードしたフォールバック値にしていた（実DBを持たないブラウザ内
   モック特有の作り込み）。実DBを扱う本実装では各文書/契約書の実データをpkから直接引けるため
   不要。
3. 原本はブラウザ内の配列に全件の編集内容を溜め、最後の「更新」で初めて一括保存する設計
   だったが、ModelChoiceFieldの値（部署・分類・保存期間等）はセッションへのJSONシリアライズに
   向かないため、本実装は「どのボタン（＜／次へ／更新）を押しても、まず今表示している内容を
   検証・保存してから移動する」save-as-you-go方式にした。ブラウザクラッシュ等で中断しても
   それまでの編集が失われない利点もある。

**実装**:
- `core/bulk_edit_services.py`（新規）: `core.upload_services.get_pending_files`/
  `clear_pending_files`と同じ最小主義パターンで、セッションに`{"pks": [...], "index": int}`
  だけを持たせるヘルパー（`start_bulk_edit`/`get_bulk_edit_state`/`set_bulk_edit_index`/
  `clear_bulk_edit_state`）。documents/contracts両アプリが自分のセッションキー文字列
  （`documents_bulk_edit`/`contracts_bulk_edit`）を渡して共有する。
- `documents.services.apply_document_edit`/`contracts.services.apply_contract_edit`
  （新規）: 既存の`DocumentEditView.post`/`ContractEditView.post`にあった「フィールドコピー＋
  保存」ロジックを切り出し、単体編集と一括編集の両方から呼べるようにした（重複を増やさない
  ため）。`contracts`側は関連書類の追加・削除も含めて`transaction.atomic()`にまとめる元の設計を
  維持し、`parse_remove_related_ids`も共通化した。
- `documents.views.BulkEditStartView`/`BulkEditView`、`contracts`側も同一パターンで並行実装
  （`BulkDownloadView`と同じpks検証パターン。編集権限自体は既存の単体編集・検索詳細ポップアップ
  「変更」ボタンと同じくログイン済み・未削除であれば誰でも編集できる前提のため、追加の権限判定
  は行っていない）。
- `templates/documents/edit.html`・`templates/contracts/edit.html`: 原本と同じく
  hardcoded disabledだった死んだページャーUIを、`bulk`コンテキスト変数の有無で実際に機能する
  ように変更。既存の完了モーダル（`_complete_modal.html`）は`complete.created`をループする作り
  だったため**無変更のまま**複数件表示に対応できた。
- `templates/documents/search.html`・`templates/contracts/search.html`: `disabled`だった
  「一括編集」ボタンを、既存の一括ダウンロード用`<form>`内の`formaction`違いのsubmitボタンに
  変更（新規JS不要）。
- 監査ログ（`audit.AuditLog`）は一括ダウンロードのような集約1件ではなく、編集した文書/契約書
  ごとに1件ずつ記録する（ユーザー指示、既存の単体編集と同じ粒度）。
- `documents.tests.BulkEditViewTests`/`contracts.tests.BulkEditViewTests`を追加し、
  `python manage.py test`（documents 161件・contracts含む全体）PASS確認済み。ブラウザでも
  実際に2件選択→1件目編集して「次へ」→2件目編集して「更新」→完了ポップアップに編集後の
  タイトルで2件とも表示・DBの実更新・AuditLog 2件（1件ずつ）作成を確認済み。

CLAUDE.mdの「既知の未実装・保留事項」から一括編集の項目を削除した。

## 保存満了日の計算基準日をユーザー確認・年欄との連動解消（2026-08-20）

「実装上の簡略化・既知の未解決事項（2026-08-08時点）」に記載していた疑義
（原本JS `calculateExpiryDate()`は保管画面の「年」欄基準、実装はアップロード実日付基準になって
いる疑いあり）について、ユーザーへ確認したところ次の仕様が確定した。

- 保存満了日 ＝ 保存した日（アップロード/更新の実日付） + 保存期間
- 有効期限 ＝ 保存満了日
- 保管画面２の「年」欄（文書の業務上の区分年）は保存満了日の計算には一切関与しない

`documents/services.py`の`calculate_expiry_date()`（`documents/views.py`から
`save_date=timezone.now().date()`／編集時は`timezone.localdate()`で呼ばれる）は元々この仕様
どおりに実装済みだったため、実際のDB保存値のロジック自体に変更は無い。一方で保管画面２・編集画面の
JSプレビュー（`calculateExpiryDate()`、2026-08-08新規実装／2026-08-13に年selectのonchange追加）は
「年」欄を基準に計算する原本JSの移植のままで、実際の保存値とプレビュー表示が食い違っていたため、
今回の確認を機に是正した。

- [x] `documents.services.expiry_date_previews()`（新規）：`calculate_expiry_date()`をそのまま
  再利用し、`{保存期間pk: 保存満了日(ISO文字列)}`を返す。基準日は常に今日（`timezone.localdate()`）。
- [x] `documents/views.py`に`_expiry_preview_context(form)`ヘルパーを追加し、`UploadStep2View`
  （GET／POSTバリデーションエラー／登録完了）・`DocumentEditView`（GET／POSTバリデーションエラー／
  更新完了）・`BulkEditView`（`_context`／最終更新完了）の全レンダリング箇所に`expiry_previews`を
  コンテキストとして渡すよう変更。
- [x] `templates/documents/storage2.html`・`edit.html`：`{{ expiry_previews|json_script:"expiry-previews" }}`
  で埋め込み、`calculateExpiryDate()`を「保存期間selectの選択値でこの辞書を引くだけ」に単純化
  （日付計算ロジックをJS側に二重実装しない）。「年」欄のonchangeは撤去（2026-08-13に追加した
  ものだが、年欄が計算に無関係と確定したため今回撤去。原本の配線漏れ修正という当時の判断は
  「年欄が計算に使われる」という前提自体が誤りだったことになる）。
- [x] `documents/forms.py`の`RetentionPeriodSelect`（`data-unit`/`data-years`をJSへ渡すためだけの
  ウィジェット）は上記変更で不要になったため削除し、`retention_period`は素の`forms.Select`に戻した。
- [x] CLAUDE.md「既知の未実装・保留事項」から当該項目を削除。
- 上記調査のために別セッションへ切り出していたタスク（`task_id: task_c6b1d67f`）は、本セッションで
  直接解決したため取り下げた。

---

## 要再確認（赤字）箇所リスト（xlsx記載、2026-08-07時点）

**2026-08-19追記**: Rev1.1改訂で権限管理画面が全面的に再設計され、以下は解消・陳腐化した
（詳細は上記「原本HTML/xlsx Rev1.1改訂の反映」参照）。
- No.2〜17（権限管理シートの要再確認事項）: 「所属長への権限付与」「職員への権限付与」
  「部署・事業所/カテゴリー単位の作成・変更・削除」フラグそのものがRev1.1で廃止され、
  システム権限プルダウン1段階に統一されたため、これらの連動仕様の疑問自体が対象を失った。
  No.3・11（部署選択ボタンの表示条件）はRev1.1で文書側=管理者のみ、契約書側=管理者または
  `contract_visible_departments`設定ありに確定した。
- No.18（`C52`）: 文書検索画面の部署選択条件からして「文書管理-部門間閲覧設定」自体が
  Rev1.1で廃止されたため対象外（管理者のみに単純化）。
- No.20〜22（ダウンロードボタンのdisabled表示）: Rev1.1で「権限が無い場合は非表示」に確定した
  （disabled表示ではなくなった）。

**2026-08-19追記2**: 実装とxlsx Rev1.1全文の突合監査（詳細は上記「実装とxlsx Rev1.1全文の突合
監査・実装漏れ修正」参照）で以下を解消した。
- No.19（`B184`検索・閲覧・変更「保存期間設定で設定したデータは使用しない」）:
  `documents.services.used_retention_periods()`で実データ抽出に変更し解消。

**2026-08-21追記**（ユーザー指摘で発覚、詳細は下記「要再確認No.1（職員マスタ削除機能）の
解消確認」参照）: No.1（`D120`職員マスタ削除機能）はRev1.1改訂で解消済みだったが、
2026-08-19の一斉反映作業で見落とされていた。CSV取込差分更新条件のセルがRev1_1
`D122`「…処理不要とする。(職員削除処理も不要)」に書き換えられ、赤字の「要相談」注記自体が
削除済みだったため。

### 職員マスタ
1. ~~`D120` 職員マスタに「削除」機能が無いため、エンドユーザと要相談~~ → 2026-08-21解消
   （Rev1.1で「削除処理も不要」と確定済み。詳細は上記追記および下記訂正セクション参照）

### 権限管理
2. `B156` 所属長は自分の権限の変更が不可
3. `B186` 文書検索画面の項目「部署」で部署選択が可能となる
4. `B190` 所属長が所属部署の職員の"文書管理"「権限」編集を可能とする
5. `B193` 詳細不明
6. `B197` OFFの場合…設定メニュー画面「部署管理」ボタンを非表示にする制御でいいか？
7. `B201` ONの場合…設定メニュー画面「分類管理」で"書類管理区分"が"文書管理"のみ新規作成/編集/削除可能となる
8. `B206` 所属長が職員に対して設定する。「所属長への権限付与」がOFFの場合の表示制御は？
9. `B210` ONの場合…設定メニュー画面「カテゴリー管理」で"書類管理区分"が"文書管理"のみ新規作成/編集/削除可能となる
10. `B215` "保存満了日"は所属長による権限設定で可能となっているが、どこで設定するのか？
11. `B219` 契約書検索画面の項目「部署」で部署選択が可能となる
12. `B223` 所属長が所属部署の職員の"契約書"「権限」編集を可能とする
13. `B226` 詳細不明
14. `B230` OFFの場合…設定メニュー画面「部署管理」ボタンを非表示にする制御でいいか？文書管理の時との違いは？
15. `B234` ONの場合…設定メニュー画面「分類管理」で"書類管理区分"が"契約書管理"のみ新規作成/編集/削除可能となる
16. `B239` 所属長が職員に対して設定する。「所属長への権限付与」がOFFの場合の表示制御は？
17. `B243` ONの場合…設定メニュー画面「カテゴリー管理」で"書類管理区分"が"契約書管理"のみ新規作成/編集/削除可能となる

### 検索・閲覧・変更
18. `C52` 文書管理-部門間閲覧設定がONになっているログインユーザ
19. `B184` 「保存期間設定」で設定したデータは使用しない
20. `B263`〜`B264` 「権限管理」で文書管理-文書-ダウンロードがONのユーザのみダウンロード可、権限が無いユーザはボタンdisabled
21. `B328`〜`B329` 同上（別画面）
22. `B616`〜`B617` 「権限管理」で文書管理-契約書-ダウンロードがONのユーザのみダウンロード可、権限が無いユーザはボタンdisabled

### 保管
23. `X496` ※画面は開発中のものです（「登録完了」ポップアップの画像モックのみ未完成、機能仕様自体は本文記載から把握可能）
    → 2026-08-21判明：調査誤り。画像自体はxlsxに実在しており、この赤字注記は「画像未着」では
    なく「掲載画像は開発中の暫定版」という意味だった。詳細は本ファイル末尾の訂正セクション参照。
24. `AA592` ※画面は開発中のものです（「更新完了」ポップアップの画像モックのみ未完成、同上）
    → 同上（Rev1.1では本注記自体が削除され現存せず）。

## 要再確認No.23〜24（保管画面完了ポップアップ画像）の調査誤り訂正（2026-08-21）

これまで「`X496`/`AA592`の赤字注記＝画像モック自体が未着」と判定していたが、ユーザー指摘を
受けて簡易設計指示書xlsxの`保管`シートを`openpyxl`で実際に開いて確認したところ、調査誤りと
判明した。

- `保管`シートの下記4箇所には、Rev1_0の時点から一貫して画像が埋め込まれている（Rev1.1での
  新規追加ではない）。
  - 210〜227行目：文書「登録完了」ポップアップ
  - 307〜322行目：文書「更新完了」ポップアップ
  - 495行目（単一セルアンカー、範囲指定なし）：契約書「登録完了」ポップアップ
  - 588〜603行目：契約書「更新完了」ポップアップ
- `X496`の赤字注記「※画面は開発中のものです」は、Rev1_0からRev1_1まで一貫して残存している。
  これは「画像が届いていない」という意味ではなく「掲載画像は開発中の暫定版キャプチャであり、
  最終デザインとは限らない」という注記だった。対の`AA592`（更新完了側）は同一文言がRev1_0には
  あったが、Rev1.1で削除されている。
- 画像の中身を確認したところ、`#overlay-modal`要素（原本HTML `html4/index.html:536-565`）を
  そのままキャプチャしたスクリーンショットだった。タイトル文言・分類/年/カテゴリー/タイトルの
  表構成・ボタン構成のいずれも原本HTMLの当該要素と一致している。
- 実装側（[templates/documents/_complete_modal.html](templates/documents/_complete_modal.html)・
  [templates/contracts/_complete_modal.html](templates/contracts/_complete_modal.html)）は、
  当初から「原本index.html:536-565の`.overlay`要素の移植」として作られており、画像の内容と
  最初から一致していた。つまり「画像モック未反映」という課題自体がそもそも存在していなかった。
- 契約書の登録完了ポップアップ画像（495行目）のみ、文書の登録完了ポップアップ画像（210行目）と
  完全に同一ファイル（MD5一致）で、中身も文書側の内容（総務部／一般文書／00008.pdf）のまま
  契約書向けに差し替わっていない。原本xlsx側で契約書用の画像が別途用意されなかったための
  流用と見られる。実装側は`_complete_modal.html`が文書・契約書それぞれの実データを正しく表示
  するため、この流用の影響は受けていない。

## 要再確認No.1（職員マスタ削除機能）の解消確認（2026-08-21）

ユーザー指摘（「退職チェックボックスがあるので削除機能が無いわけではないのでは」）を受けて、
Rev1_0とRev1_1の`職員マスタ`シートを`openpyxl`で直接突き合わせたところ、No.1は既に
Rev1.1改訂で解消済みと判明した（2026-08-19のRev1.1一斉反映作業で見落とされていた）。

- Rev1_0 `D120`（赤字・フォント色`FF0000`）：CSV取込時「職員マスタテーブルに存在し、取込用
  CSVにない場合」（`D119`「…処理不要とする。」）に続けて「※但し、職員マスタに『削除』機能が
  無い為、エンドユーザと要相談。」と注記されていた。
- Rev1_1では該当セルが`D122`「…処理不要とする。**(職員削除処理も不要)**」に書き換えられ、
  赤字の「要相談」注記自体が削除されている。つまり「取込CSVから消えた職員をマスタからも
  削除するか」という論点について、「削除処理そのものが不要」と業務要件側で明示的に確定した。
- 退職フラグ機構（部課コード"99"→退職扱い）はRev1_0時点から別項目として存在しており
  （Rev1_0 `D112`／Rev1_1 `D115`）、今回の解消はこの退職フラグが「削除機能の代替」と
  再定義されたわけではない。両者は独立した仕様で、たまたま結果として「実データを消す
  delete操作は不要（退職フラグによる論理的な使用不可化のみで足りる）」という結論で一致した。
- 実装（`accounts`アプリ、職員マスタに削除ボタン無し・「退職」チェックボックスで
  `is_retired`相当のフラグを立てる方式）は元々この結論と一致しており、コード変更は不要。
  CLAUDE.md「既知の未実装・保留事項」から当該項目を削除した。

この訂正に伴い、[CLAUDE.md](../CLAUDE.md)「既知の未実装・保留事項」から本項目を削除した。

## 簡易設計指示書 Rev1.2改訂の反映（2026-08-24）

`HTML/文書管理システム_簡易設計指示書_Rev1_1.xlsx`→`Rev1_2.xlsx`への改訂（印刷枠外の
"Rev1.2"表記で変更箇所を明示、担当:原田(TNW)、2026-08-21回答反映）。html4からのHTML側の
改訂は無く、xlsx（指示書）のみの改訂。Rev1.0→Rev1.1の時と同じくopenpyxlでのセル単位比較
（画像埋め込み表も同じくハッシュ比較で確認、差分無し）で機械的に差分抽出してから反映した。

### 差分の内容（openpyxlセル単位diff、対象7シート）
- **表紙**：Rev1.2の版数・改訂日（2026-08-21）・担当者記録のみ。
- **メイン画面**：お知らせ3項目（有効期限切れ／有効期限切れまでXヵ月以内／直近Xヵ月内で削除）が
  「文書」のみから「文書、契約書」両方対象に拡張。加えて新規の補足事項「"直近Xヵ月"を経過した
  文書・契約書は自動的に物理削除を行うこと」が追加。
- **権限管理**：新規権限「契約書-契約書-契約書情報変更」追加（OFFで契約書の保存・編集不可）。
  既存の「契約書-文書-ダウンロード」表記の誤記修正（「契約書-契約書-ダウンロード」へ）。
  「契約書-部門間閲覧設定」の編集・一覧検索「部署」プルダウンが管理者のみ表示に narrow。
- **分類管理・カテゴリー管理**：検索・登録・編集画面に「部署」プルダウン（管理者のみ表示）を
  新設、一覧の閲覧範囲・ソート・列表示を部署単位でスコープ（管理者=全部署、非管理者=自部署のみ）。
- **検索・閲覧・変更**：分類/カテゴリー選択ポップアップが「自部署の内容を表示」に変更（部署を
  複数選択できる権限の場合は選択部署分を選択可）。一括ダウンロード/一括編集ボタンをメイン画面
  お知らせ「直近Xヵ月内で削除された」リンクからの遷移時は非表示に。削除済み(is_deleted=True)の
  文書/契約書は削除ボタンを非表示、かつ「本文書/本契約書は削除されています」の表示を追加。
- **保管**：分類/カテゴリー選択の「自部署の内容を表示」表記変更のみ（検索・閲覧・変更と同旨）。

### ユーザーとの確認事項（実装前に2点確認）
1. **削除ボタンの扱い**：Rev1.2「削除済みは削除ボタンを非表示」が、2026-08-12にユーザー依頼で
   追加した「ゴミ箱保管中の削除ボタンで完全削除する」機能と直接競合。ユーザーに確認し
   **Rev1.2通り非表示にする**（完全削除機能は廃止）を選択。完全削除自体は新設の日次バッチ
   `core.management.commands.purge_expired_deleted_records`に一本化した。
2. **お知らせの文書・契約書表示**：DocumentとContractは別モデル・別検索画面のため、1行に
   統合して両方を検索結果に表示する新機能は今回のスコープ外と判断し、ユーザーに確認。
   **1行を2件数＋2リンクに分割**（例：「有効期限切れの文書がX件、契約書がY件あります」）を選択。

### 反映した変更ファイル（アプリ別）
- **permissions**：`models.py`（`contract_edit`フィールド追加、マイグレーション
  `0003_permissionprofile_contract_edit`）、`forms.py`（`_FLAG_FIELDS`に追加、
  `AuthorityEditForm.show_contract_visible_departments`で管理者以外はフィールド自体を除外）、
  `views.py`（`AuthorityListView`/`AuthorityEditView`に管理者判定を追加、CSV出力に列追加）、
  `services.py`（`can_edit_contract()`追加）、`templates/permissions/authority_list.html`・
  `authority_edit.html`（列追加・管理者限定表示）。
- **masters**：`models.py`（`Group`/`Category`に`department`FK追加、null許容。マイグレーション
  `0004_category_department_group_department`）、`services.py`（新規、
  `department_scope_ids()`・`scope_queryset_by_department()`）、`forms.py`（4フォームに
  `department`フィールド追加、`show_department`で管理者以外は除外）、`views.py`（一覧の部署
  フィルタ・スコープ、登録・編集・削除の部署スコープとアクセス制御、ソート順変更）、
  `templates/masters/class_*.html`・`cat_*.html`（部署列・フィールド追加）。
- **permissions.services**：`department_ids_for_group_scope()`追加（documents/contracts側の
  分類・カテゴリー選択を部署でスコープ、masters側の`department_scope_ids`とは別目的）。
- **documents/contracts**：`forms.py`（保管・検索フォームのgroup/categoryを部署スコープに）、
  `services.py`の`can_delete()`（削除済みなら常にFalseへ変更）、`views.py`の`DeleteView`
  （完全削除の分岐を削除、単純な論理削除のみに）、`api.py`（contracts側`edit_url`/`delete_url`
  に`can_edit_contract`判定を追加）、`contracts/views.py`（`ContractEditView`・
  `BulkEditStartView`・`BulkEditView`・`UploadStep1View`・`UploadStep2View`に
  `can_edit_contract`のサーバー側ゲートを追加）、`templates/documents/search.html`・
  `contracts/search.html`（notice=recently_deleted時に一括ボタン非表示）。
- **core**：`notice_services.py`（`NoticeCounts`を文書/契約書別カウントに再構成）、`views.py`
  （`can_edit_contract`をメイン画面コンテキストに追加）、`api.py`
  （`BaseOptionListAPIView._group_items`/`_category_items`に部署スコープ追加）、
  `templates/core/menu.html`（お知らせ2リンク化、保管枠「契約書」ボタンの権限出し分け）、
  新規`management/commands/purge_expired_deleted_records.py`（削除済みレコードの自動物理削除
  バッチ、日次実行想定）。
- `static/js/common.js`（削除済みバナー文言をxlsx表記に統一、完全削除の確認ダイアログ分岐を削除）。

### 設計判断の記録
- **既存データの部署未設定(NULL)への対応**：`Group`/`Category.department`はnull許容とし、
  非管理者の閲覧・編集スコープにも`department_id`未設定の行は含める
  （`masters.services.scope_queryset_by_department`のdocstring参照）。department列自体が
  今回新規追加のフィールドで、移行前の既存データ・テストデータは部署未設定になりうるため、
  非管理者から見えなくなる・編集できなくなる退行を避ける意図的な設計。
- **文書・契約書選択ポップアップの部署スコープは「選択可能な部署全体」で近似**：xlsx
  「部署を複数選択できる権限の場合は、選択した部署分の分類を選択出来るようにする」は文字通りには
  検索・保管フォームで現在選択中の部署の値に動的追従する必要があるが、popup-select側の新規JS
  連動が必要になるため、今回は「その職員が選択可能な部署全体の和集合」を常時候補にする簡略化に
  留めた（`permissions.services.department_ids_for_group_scope`のdocstring参照）。業務上
  問題があれば動的追従への拡張を別途検討する。
- **CategoryRegistView/EditView/DeleteViewはSettingsMenuAccessMixin未使用のまま**：xlsx上
  カテゴリー管理は全ロール(管理者/所属長/一般)アクセス可のため、既存の設計方針を維持し、
  部署スコープの追加のみ行った（GroupRegistView等と異なりmenu_key制限は付けていない）。

### テスト
`masters.tests.DepartmentScopingTests`（6件）・`permissions.tests.
ContractVisibleDepartmentsAdminOnlyTests`（3件）・`PermissionServicesTests`の`can_edit_contract`
系（3件）・`core.tests.PurgeExpiredDeletedRecordsCommandTests`（6件）・`core.tests.
NoticeCountsTests.test_contract_counted_independently_of_document`・`documents/contracts.tests.
BulkButtonsHiddenForRecentlyDeletedNoticeTests`（各2件）を新規追加。既存テストのうち
「ゴミ箱保管中の削除ボタンで完全削除」を前提にしていたもの（`documents/contracts.tests.
DeleteViewAjaxTests`・`DetailAPIViewTests`の一部）は新しい「削除済みは常に拒否・delete_urlは
Noneになる」仕様に合わせて書き換えた。`python manage.py test`（全401件）・
`manage.py check`・`makemigrations --check`（本改訂分については差分無し）で確認済み。

### 自動物理削除バッチの起動用batファイル追加漏れ（2026-08-24追記）

ユーザーから「自動物理削除・1週間削除不可の実装状況を確認して」と指摘を受けて再点検した際、
`core.management.commands.purge_expired_deleted_records`本体は実装済みだったが、
`extract_pending_pdf_text`/`cleanup_temp_uploads`に既にある起動用batファイル
（`ja_system/bat/*.bat`、Windowsタスクスケジューラ登録前提）がこのコマンドには無いことに
気付いた。同じ様式で[bat/purge_expired_deleted_records.bat](../../bat/purge_expired_deleted_records.bat)
を追加した（物理削除は取り消せないため、5分間隔のOCRバッチより低頻度な日次実行を想定）。
コマンド自体は自動実行されないため、実際の運用ではこの.batをタスクスケジューラへ登録する
作業が別途必要（コード側の対応はここまで）。

### 画像モックのみの変更点の見落としと修正（2026-08-24追記）

ユーザーから「Rev1.2 画面変更の記述ありの画面は変更されているか確認して」と指摘を受けて、
「画面変更」マーカーが付いた11箇所（メイン画面・権限管理[1][2]・分類管理[1]〜[4]・
カテゴリー管理[1]〜[4]）を再点検した。分類管理[4]・カテゴリー管理[4]（削除画面）は
セルのテキスト内容自体は無変更（行シフトのみ）と確認したが、**埋め込み画像そのものが
差し替わっている箇所がありopenpyxlのセル単位diffだけでは検出できない**ことが判明したため、
画像をMD5ハッシュで突き合わせ直したところ、メイン画面・権限管理・分類管理・カテゴリー管理の
4シートで実際に画像が差し替わっていた（検索・閲覧・変更・保管の2シートは画像も含めて無変更を
確認済み）。差し替わった画像を全て抽出・目視確認し、テキスト差分だけでは分からなかった以下の
相見落としを発見・修正した：

1. **分類管理一覧・カテゴリー管理一覧の列順**：モック画像は「部署」列が一番左（分類/
   カテゴリーコード列より前）。実装は分類/カテゴリーコード列の直後に配置していたため、
   `templates/masters/class_list.html`・`cat_list.html`で列順を修正。
2. **分類管理削除・カテゴリー管理削除画面**：テキストは無変更だったが画像だけ「部署」の
   表示行が追加されていた。`templates/masters/class_delete.html`・`cat_delete.html`に
   部署表示行を追加（`GroupDeleteView`/`CategoryDeleteView`は元々`select_related("department")`
   済みのためビュー側の変更は不要）。
3. **権限管理一覧の「操作」列位置**：モック画像は「操作」（編集ボタン）列が「権限」列の
   直後（フラグ列群より前、スクロール無しで見える位置）。実装はフラグ列群の後、一番右の
   ままだったため、`templates/permissions/authority_list.html`で列順を修正
   （sticky-col化は行っていない、単純な列順の入れ替えのみ）。
4. **メイン画面お知らせのレイアウト**：モック画像は文書3項目・契約書3項目を左右に完全に
   分けたブロック構成。当初はこの画像を確認できていなかったため「1行を2件数+2リンクに
   分割」する案をユーザーに確認して実装していたが、実際のモックと異なると判明。ユーザーに
   再確認の上、モック画像通りの左右2列ブロック構成（`<ul>`を2つ横並び、各3項目）に
   `templates/core/menu.html`を書き換えた。`core.notice_services.NoticeCounts`
   （文書/契約書別カウント）自体は変更不要だった。

**教訓**：xlsxのセル単位diffは文言変更の検出には有効だが、「セルには埋め込まれた画像で
実際の画面レイアウトを示し、セルのテキスト自体は変えない」改訂を見逃す。今後同種の
改訂を受領した際は、対象シートの画像をMD5ハッシュ突き合わせで比較し、差分があれば
必ず目視確認する（本ファイル冒頭の「画像埋め込み表」に関する過去の教訓と同種）。

新規テスト：`core.tests.MenuNoticeTwoColumnLayoutTests`（2件）・`masters.tests.
DepartmentScopingTests.test_admin_list_department_column_is_leftmost`・
`test_delete_confirmation_shows_department`・`permissions.tests.
AuthorityListOperationColumnPositionTests`（1件）。`python manage.py test`（全406件）・
`manage.py check`で確認済み。

## 簡易設計指示書 Rev1.3改訂の反映（2026-08-27）

`HTML/文書管理システム_簡易設計指示書_Rev1_2.xlsx`→`Rev1_3.xlsx`への改訂（印刷枠外の
"Rev1.3"表記で変更箇所を明示、担当:原田、改訂日2026-08-26、表紙J27「権限管理 画面変更
及び 誤記修正」）。html4からのHTML側の改訂は無く、xlsx（指示書）のみの改訂。
Rev1.1/Rev1.2の時と同じくopenpyxlでのセル単位比較＋`xl/media`配下画像のバイト比較で
機械的に差分抽出してから反映した。

### 差分の内容（openpyxlセル単位diff＋画像バイト比較、対象3シート）
- **表紙**：Rev1.3の版数・改訂日（2026-08-26）・担当者・改訂概要の記録のみ。
- **権限管理**：AI10（[1]権限管理一覧）とAI89（[2]権限管理編集）に「Rev1.3 画面変更」
  マーカー。テキストセルの変更は無く、埋め込みスクショ（drawing6のimage19=一覧／
  image20=編集）が差し替わっている。
  - **image20（権限管理編集）＝実装対象**：「文書管理-分類-表示」「契約書-部門間閲覧設定」
    「契約書-分類-表示」の3欄の表示用要素が、1行の`<input type="text" readonly>`から
    複数行の`<textarea readonly>`（4行程度＋リサイズ可）に変更された。選択済みの分類・部署が
    カンマ区切りで長くなっても全件見えるようにする意図。「選択」ボタンはtextarea上端に揃う。
  - **image19（権限管理一覧）＝行内「編集」ボタンの背景色変更**：カラム構成・見出し・データは
    OLD/NEWで一致するが、行内の「編集」ボタンの背景色が既定(白)から**ピンク`#FFCCFF`**に
    変更されている（ボーダー`#D1C7BD`・角丸4pxは既定のまま）。他ボタン（設定メニューへ戻る／
    検索／CSV出力）や権限管理編集画面のボタンは変更なし。当初この差分を「表示倍率違いの
    再取得のみ」と誤判定して見落とし、ユーザー指摘で修正（下記「編集ボタンの背景色変更の
    見落とし」参照）。
- **保管**：B194-201（保存期間プルダウン／削除ボタン／登録ボタンの説明文）を削除。
  AI194「Rev1.3 不要文言削除」。これらの機能自体は実装済みで存続しており、指示書上の
  重複記述を整理しただけ。実装影響なし。保管シートの埋め込み画像も無変更。

### 反映した変更ファイル
- **core**：`widgets.py`の`PopupSelectWidget`に`display_multiline`引数を追加。Trueのとき
  表示用要素を`<textarea rows="4" readonly>`で描画する（値は属性ではなくタグ内容として持つ）。
  既定値Falseのため他画面（検索フォーム・保管画面2等）の見た目は不変。`common.js`の
  popup-select確定処理・`authority_edit.html`の`toggleAllCheckboxesForAuth()`はいずれも
  `.value`の読み書きで、`<input>`/`<textarea>`とも同一に動作するためJS側の変更は不要。
- **permissions**：`forms.py`の`AuthorityEditForm.Meta.widgets`で上記3ウィジェットに
  `display_multiline=True`を指定、`display_attrs`に`vertical-align:top`を追加（「選択」
  ボタンをtextarea上端に揃える）。
- **編集ボタンの背景色**（下記「見落とし」節参照）：`templates/permissions/authority_list.html`
  の行内「編集」`<button>`に`class="btn-edit-auth"`を付与、`static/css/style.css`に
  `.data-table-auth td .btn-edit-auth { background-color: #FFCCFF; }`を追加。他一覧画面の
  編集ボタンには波及させない（Rev1.3でモック差し替えがあったのは権限管理一覧のみ）。

### 実機確認
dev serverで権限管理編集画面を開き、3欄が`<textarea>`（rows=4, readonly, width:200px,
vertical-align:top）で描画されること、「選択」ポップアップ→「確定」でtextareaに
ラベルがセットされること、「一括無許可」で3欄がクリアされることをブラウザで確認。
権限管理一覧では「編集」ボタンの`background-color`が`rgb(255,204,255)`＝`#FFCCFF`で
描画されることをブラウザで確認。

### テスト
`core.tests.PopupSelectWidgetTamperResistanceTests`に
`test_display_element_is_single_line_input_by_default`・
`test_display_multiline_renders_readonly_textarea_with_value_as_content`、
`permissions.tests.AuthorityEditFormTests`に
`test_multi_select_display_fields_render_as_textarea`、
`permissions.tests.AuthorityListEditButtonStyleTests`（クラス付与＋CSS定義の2件）を追加。
`manage.py test permissions core.tests.PopupSelectWidgetTamperResistanceTests`で確認済み。

### 編集ボタンの背景色変更の見落とし（ユーザー指摘で修正）
Rev1.3反映の初回対応時、権限管理一覧（image19）のOLD/NEWをカラム・見出し・データ行まで
突き合わせて「表示倍率違いの再取得のみ、内容不変」と誤判定し、行内「編集」ボタンの
背景色変更（白→`#FFCCFF`）を見落とした。ユーザーから「権限管理の一覧画面、ボタン色変更は
実装した？」と指摘を受けて再確認。ボタン塗り色をピクセル単位でサンプリングし
（全行・全ボタンが一様に`#FFCCFF`＝スタイル定義による変更で、hover等の一時状態ではない）
確定、上記の通り修正した。**教訓**：「Rev1.x 画面変更」マーカーが付いた画像は、
レイアウト・文言・データだけでなく、ボタン/セルの色・装飾といった見た目の属性まで
OLD/NEWで突き合わせる（本ファイル冒頭「画像埋め込み表」の教訓に色の観点を追加）。

## 論理削除した文書・契約書の復元機能：不要と最終確定（2026-08-24）

`doc/文書管理システム_残項目_本番リリース手順書.xlsx`②要ユーザー判断事項（xlsx番号なし・
詳細ポップアップ）／①残項目・未解決事項一覧No.2、および`doc/文書管理システム_実装と原本の
差異一覧.xlsx`「5_未実装_保留事項」No.5で「復元機能が業務上必要かどうか確認してください」
として未解決（🔴）のまま残っていた事項について、ユーザーへ確認したところ「復元機能は
不要ということで対応してください」と回答があり、最終確定した。

- **結論**：論理削除した文書・契約書を元に戻す（復元する）機能は実装しない。UI・ビュー・APIの
  いずれにも復元手段を追加しない。
- **現状の挙動（変更なし）**：ゴミ箱保管中（`is_deleted=True`）の文書・契約書は、
  `settings.NOTICE_DELETED_THRESHOLD_MONTHS`（既定1ヶ月）経過後に
  `core.management.commands.purge_expired_deleted_records`（日次バッチ想定）で自動的に
  完全削除される（Rev1.2反映時に実装済み、[HTML_REIMPL_CHECKLIST.md](HTML_REIMPL_CHECKLIST.md)
  「簡易設計指示書 Rev1.2改訂の反映」参照）。個別レコードを手動で完全削除する手段は
  2026-08-12に追加後、2026-08-24のRev1.2反映で既に廃止済み（同上参照）。
- **コード変更は無し**：復元機能はそもそも実装されていなかったため、この確定を受けての
  追加のコード変更は発生しない（「実装しない」という仕様を確定させただけ）。

### 更新したドキュメント
- [CLAUDE.md](../CLAUDE.md)「既知の未実装・保留事項」：復元機能の要否確認待ちだった記述を、
  「不要と最終確定」の記述に更新。
- `doc/文書管理システム_残項目_本番リリース手順書.xlsx`：
  - ①残項目・未解決事項一覧 No.2（行7）：状態を🔴未解決→🟢解消済みに更新、対応区分「要業務
    判断」→「要業務判断（解消済み）」、現状・内容/影響・リスク/備考を現状（Rev1.2反映後の
    自動物理削除バッチのみ）に合わせて更新。
  - ②要ユーザー判断事項 行10：状態を🔴未解決→🟢解消済みに更新、現状の実装状況・リリースへの
    影響を更新、回答欄（H列）に「不要。現状のまま（復元機能なし、自動物理削除バッチのみ）で
    クローズ。（2026-08-24回答）」を記入。
  - 表紙の改訂履歴ログ（B6）に本解消を追記。①②とも🔴未解決が0件になった。
- `doc/文書管理システム_実装と原本の差異一覧.xlsx`「5_未実装_保留事項」No.5（行6）：項目名に
  既存の解消済み項目（No.1・No.4）と同じ「（削除・解消済み：…）」プレフィックスを付与し、
  状態を🔴未解決→🟢解消済みに更新。

### 補足：xlsx編集時の環境制約
この2ファイルはopenpyxlでセル値・状態バッジのスタイル（既存の🟢セルからfill/font/border/
alignmentをコピー）を直接編集する方式で更新した。ステータス列以外の集計（K〜M列・H〜J列の
`COUNTIF`式）は数式文字列としてそのまま保持されており破損は無いが、本Windows環境には
xlsxスキルのrecalc.py（LibreOffice経由での再計算）が要求する`AF_UNIX`ソケットが無く
再計算を実行できなかった。Excelは既定で自動計算のため、次にExcelで開いた時点で
COUNTIF集計は正しい値に更新される（一時的にキャッシュ値が古いままの状態でファイルが
保存されている点のみ留意）。

## 権限管理画面：Rev1.2モックの2行見出し列に合わせて修正（2026-08-24）

ユーザーから「権限管理の画面でRev1_2モックで列タイトルが2行になっている列はそれに合わせて
変更して」と指摘を受けて、埋め込み画像モック（`new_権限管理_row6_2.png`＝一覧画面、
`new_権限管理_row86_3.png`＝編集画面、上記「画像モックのみの変更点の見落としと修正」で
抽出済みのもの）をズームして見出し行を1セルずつ突き合わせた。

- **一覧画面**（`templates/permissions/authority_list.html`）：「保存満了日変更」→
  「保存満了日<br>変更」、「契約書情報変更」→「契約書情報<br>変更」に修正（Rev1.1時点の
  モックでは「保存満了日変更」は1行だったため、Rev1.2で新たに2行化されたと判明）。
  「部門間閲覧設定」「書類毎の閲覧設定」は元々2行実装済みで変更不要。
- **編集画面**（`templates/permissions/authority_edit.html`）：同じく「保存満了日変更」
  「契約書情報変更」を2行化。加えて「書類毎の閲覧設定」も編集画面モックでは2行
  （「書類毎の」／「閲覧設定」）だったため`<br>`を追加。「部門間閲覧設定」は編集画面モックでは
  **1行のまま**（一覧画面とは異なる）だったため変更しなかった——同じ項目名でも画面ごとに
  折り返しが異なる箇所がある点に注意。

`python manage.py test`（全406件）・`manage.py check`で確認済み（見た目のみの変更のためテスト
追加は無し）。

## 検索結果詳細ポップアップ：ダウンロードボタンの削除済み非表示漏れを修正（2026-08-24追記）

ユーザーから「文書・契約書の編集画面（検索結果詳細ポップアップ）でダウンロード／変更／削除の
3ボタンとも削除済みなら非表示のはずが反映されていない」と指摘を受けて再点検した。

xlsx 検索・閲覧・変更!B327-342（screen-doc-detail、契約書側はB655-668）を確認すると、
ダウンロード・変更・削除の3ボタンいずれにも「※削除されている(削除フラグがTrue)文書は、
ボタンを非表示とする」の注記があり、Rev1.2で3ボタンとも対象になっていた。しかし前回
（[[簡易設計指示書 Rev1.2改訂の反映]]）の実装・監査では「変更」「削除」の2ボタンのみ
`is_deleted`をgatingに含め、「ダウンロード」ボタンだけ`permissions.services.can_download`
の権限判定のみで`is_deleted`を見ていなかった（`documents/tests.py`
`test_deleted_document_yields_null_edit_and_delete_urls`のコメントに「download_urlは
is_deletedに関わらず参照可能な仕様のためNoneにしない」という誤った説明が残っており、これが
見落としの原因だった）。

### 修正内容
- `documents/api.py`・`contracts/api.py`の`DetailAPIView`：`download_url`の算出条件に
  `not document.is_deleted`（契約書は`not contract.is_deleted`）を追加。
- `documents/views.py`・`contracts/views.py`の`DownloadView`：URL直打ち対策として
  `get_object_or_404(..., is_deleted=False)`に変更（`DocumentEditView.get_object()`と
  同じパターン）。以前は削除済みでもファイル実体を直接ダウンロードできてしまっていた。
- `static/js/common.js`側は`data.can_download && data.download_url`でボタン表示を判定して
  おり、`download_url`がNoneになれば自動的に非表示になるため変更不要。

### テスト
`documents/contracts.tests.DetailAPIViewTests`の削除済みケースに`download_url`のアサーションを
追加、非削除ケースにも`download_url`の期待値を追加。`DownloadViewTests`に削除済み文書/契約書へ
のダウンロード試行が404になることを確認するテストを追加。`python manage.py test`（全408件）・
`manage.py check`で確認済み。

**教訓**：xlsxの「※削除されている場合はボタンを非表示」という注記は同一画面内の複数ボタンに
繰り返し付くことがあり、1ボタンだけ対応して他を見落とすと機械diff（セル単位比較）はパスして
しまう（diffツール自体はテキスト変更を正しく検出していたが、実装側で該当ボタンを1つ
取りこぼした）。同種の注記が複数ボタンに付いている箇所は、実装時にボタン単位でチェックリスト化
して抜け漏れを防ぐ。

## 契約書削除のサーバー側権限チェック漏れを追加修正（2026-08-24再監査）

上記のダウンロードボタン見落としを受け、ユーザーから「ほかに見落としはないか」と再点検を
依頼された。openpyxlでAI列（変更種別マーカー）に`Rev1.2`を含む全セルを7シート分機械的に
列挙し（表紙除く6シートで計46箇所）、1件ずつ実装と突き合わせる方式で再監査した。

その過程で、xlsx 権限管理!B198(Rev1.2)「契約書-契約書-契約書情報変更がOFFの場合、編集不可…
検索・閲覧画面の検索結果一覧の明細ダブルクリック後に開く契約書詳細画面の「編集」「削除」
ボタンを非表示にする」について、**「編集」側（`ContractEditView`, `BulkEditStartView`,
`BulkEditView`, `UploadStep1View`, `UploadStep2View`）はいずれも`dispatch()`で
`can_edit_contract`をサーバー側強制していたが、「削除」側（`contracts.views.DeleteView.post`）
だけ`can_delete(contract)`（削除済み・1週間経過のみを見る）しか呼んでおらず、
`can_edit_contract`の検証が抜けていた**ことを発見した。

`DetailAPIView`の`delete_url`は`can_delete(contract) and can_edit`で判定しボタン自体は
正しく隠していたため、通常操作では気づけない。しかし`contract_edit`権限が無い職員でも
対象契約書のpkさえ分かれば`/contracts/<pk>/delete/`へ直接POSTすることで削除できてしまう
状態だった（ボタン非表示だけでURL直打ちを防げていなかった、他画面で徹底している
「サーバー側でも強制する」方針からの逸脱）。

### 修正内容
- `contracts/views.py`の`DeleteView.post`冒頭で`can_edit_contract(request.user)`を検証し、
  NGなら403（AJAX時はJsonResponse、非AJAX時はPermissionDenied）を返すよう追加。
- 既存の`DeleteViewAjaxTests`・`DeleteViewWindowTests`は`PermissionProfile`を作成せず
  テストしていたため（＝旧仕様では権限を問わず削除できていたことの裏返し）、
  `contract_edit=True`を付与するよう`setUp`を修正。
- 新規`DeleteViewRequiresContractEditPermissionTests`（4件）：権限プロファイル未設定／
  `contract_edit=False`／`contract_edit=True`／管理者、の4パターンで削除可否を確認。

### 再監査で確認した範囲（見落とし以外）
機械列挙した46箇所（メイン画面5・権限管理7・分類管理9・カテゴリー管理9・検索閲覧変更19・
保管4→[[簡易設計指示書 Rev1.2改訂の反映]]で一部集計)は全て実装済みと確認した。特に「同一の
※注記が複数ボタン/複数画面に繰り返し付く」パターン（分類・カテゴリー管理の部署列4画面×2、
検索・保管フォームの分類/カテゴリー「自部署」表記4箇所、一括選択/一括ダウンロード/一括編集の
3ボタン、メイン画面お知らせの文書/契約書6件数）は、繰り返し箇所を1つずつ個別に開いて
突き合わせた。文書・契約書の通常検索（`notice`未指定）は`is_deleted=False`固定
（`documents/contracts.search_services.build_queryset`）のため、削除済みレコードが一括操作の
対象に紛れ込む余地が無いことも確認した。

`python manage.py test`（全412件）・`manage.py check`で確認済み。

**教訓（追加）**：ボタンの表示/非表示（クライアント側・APIのURL生成）と、そのボタンが叩く
エンドポイントのサーバー側権限チェックは別物であり、片方を直したら必ずもう片方も
（POSTで直接叩いて）確認する。「詳細ポップアップのdelete_urlがNoneになる」ことは
「DeleteView.postが権限を検証している」ことを保証しない。

## 検索結果詳細ポップアップ：変更ボタンが「非表示」ではなく「disabled」のままだった不具合を修正（2026-08-24再々追記）

ユーザーから「変更ボタンの『削除済みなら非表示』も見落としているのでは」と指摘を受けて
`static/js/common.js`の`renderDetailPopup()`を再確認したところ、指摘通りだった。

xlsx 検索・閲覧・変更!B331,B337,B342,B659,B663,B668(Rev1.2)はダウンロード・変更・削除の
3ボタンいずれも「ボタンを**非表示**とする」という同一の文言だが、`renderDetailPopup()`内の
実装は各ボタンで方式が食い違っていた：
- ダウンロードボタン・削除ボタン：`style.display = "none"`で完全に隠す（Rev1.1で「押下不可
  (disabled)」から明示的に変更済み、ダウンロードボタンのコード上のコメントにもその経緯が
  残っていた）。
- 変更ボタン：`disabled = true` + `title`属性でグレーアウト表示するだけで、ボタン自体は
  画面に残ったまま（削除済みでも「変更」ボタンが見え、クリックできないだけの状態）。

さらに契約書側は`edit_url`が`is_deleted`だけでなく`can_edit_contract`（xlsx 権限管理!B198
「契約書-契約書-契約書情報変更」がOFF）でもNoneになるが、旧実装は両ケースとも一律
「削除済みのため変更できません」というtitleを表示しており、権限不足が理由のケースでは
文言自体も不正確だった。

### 修正内容
- `static/js/common.js`の`editBtn`表示ロジックを`dlBtn`/`deleteBtn`と同じ
  `data.edit_url`の有無で`style.display`を切り替える方式に統一（`disabled`/`title`は廃止）。

### 検証
Pythonの自動テストでは`edit_url`の値（None/URL文字列）は元々検証済みだったが、JS側の
表示切替はテスト対象外（本プロジェクトにJSテスト基盤は無い）のため、開発DBに一時的な
職員・削除済み文書・通常文書を作成しブラウザで直接確認した（確認後は作成したレコードのみ
削除して原状回復、他の既存データには触れていない）：
- 削除済み文書：ダウンロード・変更・削除の3ボタンとも`style.display === "none"`
- 通常文書：3ボタンとも表示され、変更ボタンもクリック可能（`onclick`が関数として設定される）

`python manage.py test`（全412件、JS変更のためテスト数は増減なし）・`manage.py check`で
確認済み。

**教訓（さらに追加）**：同じxlsx注記文言（「ボタンを非表示とする」）が複数ボタンに付く場合、
実装方式（`display:none`か`disabled`か）も揃っているか確認すること。1つのボタンで先に
`disabled`から`display:none`への変更経緯があっても、隣のボタンに同じ注記が後から追加された際に
その変更が横展開されず古い実装方式のまま残ることがある。

## audit/coreアプリ CLAUDE.mdコーディング規約準拠監査（2026-08-25〜26集約後の再監査、2026-08-26）

`review_rule_audit_core.txt`にてaudit/coreアプリ全体（models/views/services/forms/urls/admin/
tests、および2026-08-25〜26のdocuments/contracts間重複ロジック集約で新設された
core.record_views/master_views/upload_views/scoping_services/deletion_services/zip_services/
bulk_edit_services/csv_services/search_services/storage_paths/double_submit/form_services等）
を対象にCLAUDE.md「コーディング規約」の各項目ごとに突き合わせた。

### 結果：重大な規約違反なし、高・中優先度の指摘は0件
ビューのCBV限定、verbose_name/help_text/エラーメッセージの日本語統一、設定のbase.py集約、
アップロードファイル本体の分離、Argon2優先、監査ログの一元化、core相当への重複排除、
「なぜ」重視のコメント、ログ整備、例外処理の完成度、Paginator使用、disabled+title、
ファイル役割分担、Djangoテンプレート複数行コメントの罠、いずれも遵守を確認。
`manage.py makemigrations --check --dry-run audit core`（差分無し）・
`manage.py test audit core`（115件PASS）も確認済み。指摘は低優先度2件のみだった
ため、ユーザー指示（「低優先度は修正せず、理由付きで記録だけ残して」）に基づき
いずれも意図的に未修正。

### 見送った低優先度（2件、ドキュメントのみ・修正なし）
- `.env.example`への記載漏れ3件：`SESSION_IDLE_TIMEOUT_MINUTES`
  （`config/settings/base.py:158`、`core.middleware.SessionIdleTimeoutMiddleware`が
  `masters.SystemSetting`未設定・DB未接続時のフォールバック値として参照）・`MEDIA_ROOT`
  （`base.py:123`）・`LOG_DIR`（`base.py:204`）。他の設定値は全て`.env.example`にコメント付きで
  記載済みなのに対しこの3つだけ抜けている。既定値で動作するため実害は無いが、運用担当者が
  「変更可能な設定値の一覧」として参照した際にこの3項目の存在に気づけない状態。将来
  `.env.example`を更新する機会に、他の設定値と同じ形式（コメント＋既定値をコメントアウトで
  例示）で追記するのが望ましい。
- `core/notice_services.py`のimportに理由不明な非対称性：`get_notice_counts()`は
  `from documents.models import Document`をモジュール冒頭でトップレベルimportする一方、
  `from contracts.models import Contract`（および`organizations.services`/`permissions.services`の
  各関数）は関数内での遅延importにしている。documents/contracts双方のmodels.pyは
  `core.models`のみに依存しており循環import回避という他の遅延importと同じ理由が
  Document側には成立しないように見えるが、動作上の不具合ではなく将来この関数を読む際に
  「なぜ片方だけトップレベルか」を確認する手間が生じる程度の影響に留まる。対応するなら
  意図的な理由をコメントで明記するか、4つとも同じimport方式に揃えて非対称性を解消する。

## audit/coreアプリ テストカバレッジ棚卸しの反映（2026-08-26）

`review_test_audit_core.txt`（audit/coreアプリのテストカバレッジ棚卸し、優先度高4件・中7件・
低6件）のうち、ユーザー指示（「優先度「高」「中」の不足テストを1件ずつ順番に追加して。
python manage.py test audit coreで確認してから次に進んで。低優先度は追加せず、理由付きで
記録だけ残して」）に基づき、高・中優先度の指摘に対応するテストを1件ずつ追加し、都度
`manage.py test audit core`で確認しながら進めた。

### 追加したテスト（高優先度4件）
1. `core/tests.py` `SessionIdleTimeoutMiddlewareTests`（3件）：自動ログアウト本体
   （アイドル判定・ログアウト実行・`SystemSetting`未設定時の`settings.SESSION_IDLE_TIMEOUT_MINUTES`
   フォールバック）。テストクライアントのセッションに`last_activity_ts`を直接書き込み、
   経過時間を模擬した。
2. `core/tests.py` `OtherViewsDoubleSubmitTokenTests`（3件）：`OtherSettingsView.post`/
   `OtherMainEditView.post`/`OtherLogoutEditView.post`の二重送信トークン不正時分岐。
3. `audit/tests.py` `AuditLogListViewTests.test_filter_by_date_range`（1件）：
   `filter_audit_log_queryset`の`date_start`/`date_end`。`timestamp`が`auto_now_add`のため、
   作成後に`queryset.update()`で日時を書き換えて検証した。
4. `masters/tests.py` `MasterDeleteDatabaseErrorFallbackTests`（1件）：
   `BaseScopedMasterDeleteView.post`の`obj.save()`が`DBError`を送出した場合のフォールバック
   （2026-08-26に品質レビューで発見・追加されたばかりの例外処理）。既存の
   `MasterDoubleSubmitTokenTests`docstringの判断（GroupDeleteView/CategoryDeleteViewは
   `core.master_views.BaseScopedMasterDeleteView`の共通実装を完全共有するためGroup側のみで
   十分）を踏襲し、Group側のみ追加、Category側は重複として省略した。

### 追加したテスト（中優先度、6件対応・1件は既存判断を踏襲し見送り）
5. `core/tests.py` `NoticeCountsTests`に2件追加：契約書側の`expiring_soon_contracts`/
   `recently_deleted_contracts`、および`contract_searchable_department_ids`による部署スコープ
   （`test_other_department_document_not_counted_for_staff`の契約書版）。
6. `core/tests.py` `OtherViewsDatabaseWriteFailureTests`（2件）：`OtherSettingsView.post`
   （パスワード保存）/`OtherMainEditView.post`（メイン画面項目設定保存）のDB書き込み失敗
   （`DatabaseError`）分岐。高優先度2の`OtherViewsDoubleSubmitTokenTests`と合わせて
   `core/views.py`の3画面の例外系をまとめて手当てした。
7. `core/tests.py` `AddMonthsClampTests`（4件）：`add_months`/`_days_in_month`の月末日クランプ
   （1/31→2/28・うるう年2/29）・年またぎ。
8. `documents/tests.py` `SearchFormRadioDefaultsInitialAccessTests`（1件）：
   `apply_radio_defaults`/`InlineRadioSelect`の「初回アクセス時（GETに`title_match`等の
   キーが無い状態）にchecked状態で表示される」分岐。`SearchForm(data={})`で検証した
   （documents側のみ追加。contracts.forms.SearchFormも同じ`core.forms.apply_radio_defaults`を
   共有する完全同一実装のため、指摘4・7と同様の理由で重複テストとして省略）。
9. `documents/tests.py` `DownloadViewTests.test_download_audit_log_records_document_privacy_flag_value`
   （1件）：`BaseFileServeView.audit_extra_kwargs()`が`Document.privacy_flag`の値を
   ハードコードせずそのまま渡すことを、既定値(True)ではなくFalseを明示設定して確認した。
10. `documents/tests.py`・`contracts/tests.py`の`DownloadViewTests`にそれぞれ
    `test_display_name_strips_uuid_prefix`を追加（2件）：`UuidPrefixedFilenameMixin.display_name`
    がDocument/Contract本体側でもUUIDプレフィックス除去後の元ファイル名を返すことを直接確認した。

11については追加せず見送った（次節参照）。

### 見送った中優先度1件（既存の低優先度判断を踏襲）
- `core/master_views.py` `CategoryListView.apply_special_sort`の"group"列desc方向は、
  `review_test_organizations_masters.txt`の棚卸し時点で既に低優先度No.18として発見済みで
  「見送り済み」と記録されていた同一の指摘が、共有実装であるため本棚卸し（audit/core側）にも
  再掲されたもの。既に一度なされた判断を覆す新しい事情は無いため、本対応でもテストを追加せず
  一貫して見送った。

### 見送った低優先度（6件、ドキュメントのみ・修正なし）
- `audit/models.py` `AuditLog.__str__`、GinIndex定義自体（DB制約と同様、実害の乏しいインフラ
  設定として他レポートでも低優先度扱い）。
- `audit/forms.py` `AuditLogSearchForm`の`date_start`/`date_end` widget自体の単体テスト
  （優先度高3で対応したView/services経由の検証が既にあるため、フォーム単体の直接テストは
  重複性が高く見送った）。
- `core/double_submit.py` `issue_token`/`consume_token`/`reject_if_resubmitted`自体の直接単体
  テストが無い（他アプリのView経由で広く間接カバー済みのため、他レポートと同様に低優先度）。
- `core/text_normalization.py` `normalize_for_search`の直接単体テスト（NFKC正規化の入出力）が
  無い（View経由で実質カバー済み）。
- `core/bulk_edit_services.py` `resolve_ordered_pks`の部署スコープ外pk除外だけを狙った
  専用テストが無い（`BaseBulkDownloadView`の同種フィルタで間接カバー済み）。
- `core/upload_views.py` `BaseChunkUploadAPIView`・`core/record_views.py` `BaseBulkDownloadView`の
  一部分岐がcontracts側テストのみ欠けている（`review_test_doc_contract.txt`指摘5・9として
  既出、完全共有コードのため見送り済み）。

### 検証
高・中優先度の各指摘を1件ずつ追加するたびに`manage.py test audit core`を実行し、都度
全件PASSを確認しながら進めた。最終的に`manage.py test audit core`は130件PASS（棚卸し時点の
115件から15件純増）、影響範囲を含めた`manage.py test audit core documents contracts masters`は
467件全件PASSで完了。

## メイン画面ボタン制御をMenuItemSettingへ再連動（2026-08-26）

xlsx メイン画面!B55「設定メニュー『その他設定』の『メイン画面項目』にて部署ごとに設定された
内容でボタンの押下可不可を制御する」について、2026-08-19に一度`organizations.MenuItemSetting`
を`core.views.MenuView`へ連動させたが、未設定部署でボタンが全て消え原本HTML（常時表示の
静的モック）の見た目から乖離するとして撤回していた（本ファイル1130〜1143行目「Rev1.1反映の
過剰実装を原本一致に戻す・見落とし修正」参照）。

ユーザーから改めて「原本フィデリティより実データ連動を優先する」方針変更の指示があったため、
再度連動させた。

- [x] `core/views.py` `MenuView.get_context_data`：`request.user.department`の
  `menu_item_setting`（`getattr`でNone許容、未設定部署はNone＝xlsx その他設定!B73
  「デフォルトは全項目OFF」通り全非表示）から`show_search_document`/`show_search_contract`/
  `show_storage_document`/`show_storage_contract`をcontextに追加。
- [x] `templates/core/menu.html`：検索・閲覧・変更／保管の文書・契約書4ボタンをそれぞれ
  `{% if %}`で囲み表示/非表示化（disabledではなく非表示。2026-08-19時点の「×は押下不可
  →×は非表示」の判断を踏襲）。電子決裁ボタンは実画面が無いため従来通り恒久的に
  disabled+titleのまま変更なし。
- [x] 保管枠内「契約書」ボタンは`show_storage_contract`（部署設定）と`can_edit_contract`
  （権限管理、Rev1.2 xlsx 権限管理!B196-197）をANDで判定。両者は独立した制御軸のため、
  どちらか一方でもOFFなら非表示にする。
- [x] `core/tests.py` `MenuButtonVisibilityTests`を「常時表示」前提から「部署設定に連動」
  前提へ全面書き換え。未設定部署で全非表示になること、各ボタンが部署設定ONで個別に表示
  されること、契約書保管ボタンが部署設定・権限の両方を満たした時のみ表示されることを
  それぞれ検証する7ケースに拡充。
- [x] `manage.py test core`（115件）・`manage.py test core organizations documents contracts
  permissions audit masters accounts`（645件）で全件PASSを確認。

## 「保存期間設定」シートの行単位フル監査・retention_permanent_years の.env移行（2026-08-27）

ユーザー依頼により、xlsx「保存期間設定」シートを行単位（[1]〜[7]の全画面・全annotation）で
機械的に再監査した。Rev1.0/Rev1.1/Rev1.2間でこのシートのセルテキスト・埋め込み画像（8枚、
ハッシュ一致）に差分が無いことをまず確認済み（本シートはRev1.0時点の内容がそのまま確定）。

一覧・新規登録・編集・削除（文書/電子決裁とも）の全項目は実装済みで、原本HTML
（`html4/index.html:3079-3261`）とも一致を確認。`handlePermanent()`はxlsx文言が
"(readonly)"だが原本HTML自体のJS実装が`disabled`のため、HTML優先の既存方針通り`disabled`で
正しい（乖離ではない）。

- [x] 唯一の齟齬として、`masters.SystemSetting.retention_permanent_years`（「永年」の実年数、
  既定50年、xlsx B74「設定ファイル等で定義し、先方より変更依頼を受けた際に容易に変更できる
  こと」）を変更する手段がDB直接操作以外に存在しないことを発見した。同じ理由・同じxlsx文言
  パターンで`notice_threshold_months`/`contract_retention_years`は2026-08-13に
  `.env`経由（`NOTICE_EXPIRING_THRESHOLD_MONTHS`等）へ既に移行済みだったにもかかわらず、
  この項目だけ移行漏れになっていた。
- [x] `config/settings/base.py`に`RETENTION_PERMANENT_YEARS`（`.env`経由、既定50）を追加し、
  `.env.example`にも追記。`masters.SystemSetting`から`retention_permanent_years`フィールドを
  削除し、開発中マイグレーション0001整理の方針（本ファイル直前セクション「開発中の
  マイグレーションをアプリごとに0001のみへ整理」）に揃えて`masters/migrations/0001_initial.py`
  を直接編集（新規マイグレーション追加ではない）。
- [x] `documents/services.py` `calculate_expiry_date`を`SystemSetting.objects.first()`参照から
  `settings.RETENTION_PERMANENT_YEARS`参照に変更（`CONTRACT_RETENTION_YEARS`と同じ形）。
- [x] `documents/tests.py`の`test_permanent_respects_custom_system_setting`を
  `test_permanent_respects_custom_setting`に改名し、DBレコード作成から`@override_settings
  (RETENTION_PERMANENT_YEARS=30)`に変更。未使用になった`SystemSetting`importも削除。
- [x] `manage.py makemigrations --check --dry-run masters documents`で差分無しを確認したうえで
  `manage.py test masters documents`（213件）で全件PASSを確認。
- [ ] 注記：この修正前に一度`manage.py migrate`済みの開発DB（`ja_db`）には
  `retention_permanent_years`列が実列として残存している（Django側は列の存在を認識しないだけで
  実害は無い）。次回の開発DBリセット・マイグレーション再作成のタイミングで自然に解消される想定。

なお、xlsx B77/B191「保存期間や表示順の重複登録は出来ないように制御」は表示順(display_order)
のみを一意制約の対象とする実装（`RetentionPeriodFormTests.test_duplicate_display_order_
within_same_kbn_rejected`で明記済み）。保存期間の値自体（例：「1年」を複数行登録）は制約して
いないが、これは新規発見ではなく既存の意識的な解釈のため今回は変更しなかった。

## 操作履歴ログの行単位全数監査・記録漏れ修正（2026-08-27）

xlsx「操作履歴ログ」シート（Rev1.2、B6〜B76全セル＋Rev1.1改訂注記4箇所）を1行ずつ現行コード
（`audit`アプリ、および各アプリの`audit_services.log()`呼び出し箇所全件）と突き合わせ、
一次情報源の`index.html`の`screen-log-list`セクション（サンプルデータ行含む、
`index.html:3263-3320`）とも照合した。

### 実装済み・仕様通りと確認できた項目
職員番号完全一致検索・職員名全角スペース区切りフルネーム検索（Rev1.1）・イベントメッセージ
スペース区切りAND検索（Rev1.1）・個人情報書類チェックボックス絞り込み・初期ソート順（操作日時
降順）・ページャー（1ページ100件、Rev1.1で50→100件）・総件数表示・内部スクロール・CSV出力・
分類/カテゴリー管理の新規登録イベントメッセージ形式。

### 既に意図的な乖離と確定済みだった項目（対応不要、再確認のみ）
- 保存件数上限／CSV出力最大対象期間（B48-52）：2026-08-19にユーザー確認済みで実装見送りが
  確定済み（本ファイル「実装とxlsx Rev1.1全文の突合監査・実装漏れ修正」節参照）。
  `masters.SystemSetting.audit_log_retention_months`フィールドのみ存在し未使用のまま。
- パスワード更新：原本サンプルは新旧パスワードを平文diffで表示するが、CLAUDE.mdのマスキング
  方針によりあえて含めていない（`core/views.py`に理由コメント済み）。
- 権限管理更新：原本サンプルはフラグ単位の差分形式だが、フラグ数が多いため対象職員のみ記録する
  方針が既に確定・理由コメント済み（`permissions/views.py`）。

### 新たに発見し、ユーザー確認の上で対応した3件
1. **検索操作自体の記録漏れ**：文書検索・契約書検索とも「検索開始」ボタン押下がAuditLogに
   一度も記録されていなかった。ユーザー判断により文書・契約書検索のみ対応（他マスタ検索は
   対象外）。`core/search_services.py`に`is_search_form_submission()`（ページャー/ソートの
   再アクセスと実際の検索送信を`page`/`sort`パラメータの有無で区別）・
   `build_search_audit_message()`（フォームで実際に値が入力されたフィールドのみ「ラベル：値」で
   列挙、`(条件指定なし)`は全欄空欄時のフォールバック）を追加し、
   `documents/views.py`・`contracts/views.py`の`SearchView.get()`から呼ぶ。
   実装中に、空のQuerySet（`department`等のModelMultipleChoiceField）がDjangoの`__eq__`
   未定義により`value in (None, "", [], ())`のようなタプル比較では検出できず「部署：」という
   空ラベルが漏れる不具合を発見し、`bool(value)`判定に修正した
   （`documents.tests.SearchAuditLogTests.test_search_submission_with_department_multiselect_field`
   で回帰確認）。
2. **ダウンロード/プレビュー/登録のメッセージ形式が原本と不一致**：原本サンプル
   （`index.html:3310,3312,3316,3317,3320`）は全て「ファイル名：{実ファイル名}」形式だが、
   `core/record_views.py` `BaseFileServeView`は「{文書|契約書}「{タイトル}」を{ダウンロード
   しました|プレビュー表示しました}。」という原本に無い独自形式で、しかも実ファイル名
   (`display_name`)ではなくタイトル(`title`)を使っていた（2026-08-12追加のダウンロード監査
   ログ自体は原本に無い機能追加だったため、原本のメッセージ書式との突き合わせが漏れていた）。
   `documents/views.py`・`contracts/views.py`の登録(保管)イベントも同様に修正。
3. **更新イベントに変更前後の差分が記録されていない**：xlsx B69-70＜職員マスタ更新　例＞
   「職員：職員名(職員番号),更新した項目名：更新前データ -> 更新後データ,………」に対し、
   `accounts.views.StaffEditView`（職員マスタ更新）・`masters/views.py`
   （分類/カテゴリー/保存期間設定の更新）はいずれも更新後の値のスナップショットのみを記録し、
   何がどう変わったか記録していなかった。`audit/services.py`に`build_diff_message()`
   （`(項目名, 更新前, 更新後)`のタプル列から差分メッセージを組み立てる共通ヘルパー）を追加し、
   `accounts/services.py`に`build_staff_edit_diff_message()`を追加（パスワード自体の値は
   含めず`(変更あり)`のみ記録、パスワード更新と同じマスキング方針）。
   `core/master_views.py` `BaseScopedMasterEditView`は`audit_event_message(obj)`を
   `audit_event_message(obj, before)`に変更し、`post()`でフォーム上書き前に`copy.copy(obj)`で
   スナップショットを取得するようにした。`masters.RetentionEditView`は
   `BaseScopedMasterEditView`を使わない独自実装のため、同じパターンを個別に適用した。

### 対応したテスト
`accounts/tests.py`（診断3件追加：差分内容・無変更時・パスワードマスキング）、
`masters/tests.py`（`test_group_edit_creates_audit_log_with_content`を実際に部署を変更する
シナリオへ強化）、`documents/tests.py`・`contracts/tests.py`（`SearchAuditLogTests`クラスを
新規追加、ダウンロードテストのメッセージ形式アサーションを更新）。
`manage.py test`（全660件）PASS確認済み、`manage.py makemigrations --check --dry-run`も
差分無しを確認済み（モデル変更を伴わない実装のため）。

## 検索結果一覧 一括編集：原本html4との挙動差異の修正（2026-08-27）

ユーザーから「xlsx 検索・閲覧・変更シートの一括編集の実装が原本html4の動作と違う」との指摘。
xlsx側（B269-272、契約書はB599「文書管理と同じ」）の文言は初版から実質不変
（「・選択チェックボックスがONの検索結果の文書の編集画面へ遷移する。」「※選択チェックボックスで
指定した複数の文書を一括編集。」）で、"一括" の語意からは「共通値を全選択文書へ一括適用」
とも読めるが、**一次情報源は原本HTMLの実挙動**（CLAUDE.md「xlsxのセル文言diffは手がかりに
過ぎない」）。原本html4のモックJS（`startBulkEdit`/`changeActiveDoc`/`updateBulkEditView`/
`startUpdateMock`、`index.html:1807-1921`）は「選択件数分の編集フォームをページャー ＜ ＞ で
1件ずつ巡回し、各レコードは自身の値で個別編集、最後に『更新』で全件を完了ポップアップに一覧」
という**順次ウィザード**であり、2026-08-20の実装（本ファイル「検索結果一覧 一括編集の実装」節）
でもこの方式を採っていた。差異は次の2点で、ユーザー確認のうえ原本html4に合わせた：

1. **未選択時の挙動**：原本`startBulkEdit()`は選択0件なら`alert("編集するデータが選択されて
   いません。")`して中断する純クライアント処理。実装はサーバー側(`BulkEditStartView`)へPOSTして
   messagesで「編集する文書/契約書を選択してください。」を出していた → ユーザー指示で原本どおり
   `alert()`に変更。`common.js`に`startBulkEdit()`（原本と同名。未選択ガードのみ担う。
   `alert()`自体が原本の最終仕様として機能している箇所のため文言も踏襲）を追加し、
   `templates/documents/search.html`・`templates/contracts/search.html`の「一括編集」ボタンに
   `onclick="return startBulkEdit();"`を付与。サーバー側の検証（`if not pks` /
   `if not ordered_pks`）はJS無効・URL直POST向けのフォールバックとして残し、文言のみ
   「編集するデータが選択されていません。」に合わせた。
2. **送信ボタン**：原本html4には「次へ」ボタンが存在せず（`storage-submit-btn`は常に「更新」、
   レコード間移動はページャー ＜ ＞ の`changeActiveDoc`のみ）、「更新」(`startUpdateMock`)は
   現在何件目を表示していても即座に選択全件を確定する。実装は`bulk.has_next`なら「次へ」・
   最終レコードのみ「更新」で、「更新」は最終ステップでしか押せなかった →
   `templates/documents/edit.html`・`templates/contracts/edit.html`の送信ボタンを常時「更新」に、
   `BulkEditView.post`のナビゲーション分岐を「`bulk_nav`が`prev`/`next`のときだけ移動、
   `bulk_nav`なし（＝更新ボタン）はどのページでも全件確定」に変更（ユーザー選択：「どの位置でも
   即座に全件確定（html4忠実）」）。save-as-you-go方式（ページャー移動時に表示中の1件を都度保存。
   ModelChoiceFieldをセッションに載せられないための2026-08-20からの既定の逸脱）自体は維持。
   結果として、更新ボタンを途中で押すと表示中の1件だけがDB更新され、未訪問レコードは既存値の
   まま完了ポップアップに一覧表示される（原本`startUpdateMock`のブラウザ内配列dump相当）。

### 対応したテスト
`documents/contracts.tests.BulkEditViewTests`：中間ステップの遷移を`bulk_nav="next"`
（ページャー＞）に変更、`test_start_without_selection_redirects_with_message`（＝JS無効時の
サーバー側フォールバック）のメッセージ文言アサーションを追加、
`test_update_button_finalizes_from_any_position`を新規追加（3件選択→1件目表示のまま「更新」→
全件が完了一覧・表示中の1件のみDB更新・AuditLog 1件）。クライアント側`startBulkEdit()`の
`alert()`はJSのため単体テスト対象外。`manage.py test documents contracts`（261件）
PASS確認済み。モデル変更なし。

## 保管画面２「削除」ボタンをメモ消去→レコード削除／アップロード取り消しへ変更（2026-08-27、ユーザー確定）

### 背景
簡易設計指示書（xlsx）保管シートの「削除　ボタン」は当初から「誤ってアップロードした文書／
不要な文書を削除する（本登録から除外する）」（Rev1.2 B197-198・B298-300・B487-488・B579-581。
Rev1.3で登録側B194-201は「不要文言削除」として整理されたが機能自体は存続、AI194）と定義されて
いた。しかし原本HTMLの当該ボタン（[4]メモ欄直下の赤ボタン）は`onclick`未設定の死んだモック
だったため、DOM位置からメモ欄クリア用と解釈し`static/js/common.js`の`clearMemo()`として実装し、
意図的逸脱として「見送った低優先度」に記録していた。

2026-08-27にユーザーと確認し、以下に確定した（原本にない動的制御の追加になるが、ユーザー明示
指示のため原本一致より指示を優先。CLAUDE.md「原本フィデリティに関する運用方針」）:

- **編集画面**（`edit.html`、単独編集＋一括編集）の削除ボタン = **レコードの論理削除**
  （`is_deleted=True`）。xlsx B300/B581 通り「初回登録（保存）から1週間以上経過・削除済みは
  ボタンを非表示」。削除後の遷移は **単独編集＝検索画面へ戻る／一括編集＝その1件を対象から
  外して次のレコードへ進む**（最後の1件なら検索画面へ）。
- **登録画面**（`storage2.html`、mode=create）の削除ボタン = **表示中のファイルのアップロード
  取り消し**（セッションの保留ファイル一覧から1件除外、他のファイルは登録処理を続行）。
  サーバー往復が必要なため入力途中の他項目は破棄する（確認ダイアログで警告）。

### 設計（既存実装の再利用を優先）
- **編集画面のレコード削除**：`core.record_views.BaseDeleteView`（詳細ポップアップの削除と共通）を
  再利用。非AJAX時の末尾を`_post_delete_redirect()`に抽出し、`documents/contracts.views.
  EditDeleteView`（既存`DeleteView`を継承）が (1)監査ログのaction名を「保管画面２ 削除」に、
  (2)`from_bulk` hidden の有無で単独／一括を判定して遷移先を分岐、だけをオーバーライドする。
  7日ウィンドウ・削除済み判定は`core.deletion_services.can_delete`（`save_date`から7日）を
  そのまま使い、`can_delete=False`ならテンプレートでボタンごと非表示＋`BaseDeleteView.post`で
  URL直POSTも拒否。契約書側は`DeleteView`継承で`extra_permission_check`（`can_edit_contract`）を
  引き継ぐ。
- **一括編集中の削除**：`core.bulk_edit_services.remove_bulk_edit_pk()`を新設。`state["pks"]`から
  当該pkを外し、除去位置が現在位置より前なら`index`を1詰め、末尾超過はクランプ（＝現在位置の
  要素を消すと次のレコードが同じindexに繰り上がる）。0件になったら`clear_bulk_edit_state`して
  `None`を返し、呼び出し側は検索画面へ。
- **登録画面のアップロード取り消し**：`core.upload_services.remove_pending_file()`（保留一覧から
  index指定で1件外し実体も`unlink`）＋`core.upload_views.BaseUploadStep2RemoveView`を新設。
  documents側は`LoginRequiredMixin`、contracts側は`RequiresContractEditMixin`を継承側で組み合わせ。
  除去後は保管画面２へredirect（GETがN-1件でフォーム再生成）、0件なら文書/契約書選択画面へ。
  レコード未生成のため監査ログ対象外（`logger.info`のみ）。JS側は`storage2.html`インライン
  スクリプトのIIFE（`activeDocIndex`保持）にクリックハンドラを足し、メインフォーム外の
  隠しフォームへ`index`を詰めてsubmitする。

### 変更ファイル
- `core/record_views.py`（`_post_delete_redirect`抽出）、`core/bulk_edit_services.py`
  （`remove_bulk_edit_pk`）、`core/upload_services.py`（`remove_pending_file`）、
  `core/upload_views.py`（`BaseUploadStep2RemoveView`）
- `documents/views.py`・`contracts/views.py`（`EditDeleteView`・`UploadStep2RemoveView`・
  `_edit_delete_context`ヘルパー・編集系renderコンテキストに`can_delete`/`delete_action_url`追加）
- `documents/urls.py`・`contracts/urls.py`（`edit_delete`・`upload_step2_remove`）
- `templates/documents/edit.html`・`templates/contracts/edit.html`
  （メモ欄下ボタン→`{% if can_delete %}`＋メインフォーム外の`record-delete-form`へsubmit）
- `templates/documents/storage2.html`・`templates/contracts/storage2.html`
  （ボタン→`btn-remove-upload`、隠し`remove-upload-form`、IIFEにハンドラ追加）
- `static/js/common.js`（`clearMemo()`削除。参照は上記4テンプレートのみで削除後未参照）

### 検証
- `manage.py check` 問題なし。`manage.py test` **693件PASS**（保管画面2削除関連で新規26件：
  `documents/contracts.tests.EditDeleteViewTests`・`UploadStep2RemoveViewTests`、
  `core.tests.RemoveBulkEditPkTests`・`UploadServicesErrorHandlingTests`に`remove_pending_file`分）。
- dev サーバーで手動確認：2件選択→保管画面2で1件目「削除」→2件目のみ残し登録／新規文書を
  編集画面で「削除」→検索一覧から消える／新規2件を一括編集→1件目「削除」→2件目へ進み
  N/M が 1/1／`save_date`を8日前にした文書で編集画面に削除ボタンが出ないこと。

