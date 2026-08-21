# 画面棚卸し表（担当: 共通画面 + 第一陣）

対象: `screen-login` / `screen-menu` / `screen-storage1` / `screen-storage2` / `screen-search`

出典:
- HTML本体: `C:\Users\yamad\Claude\JA\HTML\html1\index.html`（対象箇所の行番号は2026-08-07時点の実ファイルで確認済み）
- Excel設計指示書: `C:\Users\yamad\Claude\JA\HTML\文書管理システム_簡易設計指示書_Rev1_0.xlsx`（シート: `ログイン画面` / `メイン画面` / `検索・閲覧・変更` / `保管`）
- HTML分割ファイル格納先: `C:\Users\yamad\Claude\JA\HTML\html1\screens\`

補足: `screen-storage2` と `screen-search` は、文書管理／契約書管理の両方で共有される単一のDOMを持ち、JS（`transitionToStorage()` / `transitionToSearch()` / `triggerChangeFromDetail()` 等）がラベル文言・列構成・表示項目を動的に書き換える構造になっている。以下の記載では両モードの差分を明記する。

またポップアップ（`popup-detail` 文書詳細ポップアップ、`popup-select` 部署/分類/年/カテゴリー選択ポップアップ）とオーバーレイ（`overlay-progress` 進捗、`overlay-modal` 登録/更新完了モーダル）は `screen-storage2` と `screen-search` の双方から呼び出される共通コンポーネントとして、HTML上は独立したdiv（`index.html` 462〜565行目）だが、本棚卸し表では関連する画面のJS挙動欄に記載する。これらの共通コンポーネント自体を格納する専用の分割HTMLファイルは今回作成していない（担当5画面のdivのみを分割対象とする指示のため）。

---

## screen-login — ログイン画面

- **対応xlsxシート**: ログイン画面
- **画面概要**: 職員番号とパスワードを入力してログインする、システムの入口画面。
- **表示項目**:
  - システムサブタイトル「電帳法対応」
  - ログインタイトル「クラウド文書管理システム」
- **入力項目**:
  - 職員番号（`input#login-user`, type=text, 初期値 `1`, placeholder「例：123456」）※必須/バリデーション規則はHTML上に明記なし（不明・要確認）
  - パスワード（`input#login-pass`, type=password, 初期値 `password123`）※必須/バリデーション規則は不明（要確認）
    - パスワード表示切替アイコン（👁️、`span#pass-toggle-icon`）クリックでtype="password"⇔"text"をトグル
- **一覧の列**: 該当なし
- **検索条件**: 該当なし
- **ボタン/アクション**:
  - 「ログイン」ボタン（`btn-primary`）→ `onclick="transitionTo('screen-menu')"` で `screen-menu` へ遷移。HTML上は職員番号・パスワードの照合ロジックは実装されていない（モック、常に成功）。
- **JS挙動**:
  - `pass-toggle-icon` の `click` イベントでパスワード欄の `type` を `password` ⇔ `text` に切替（index.html 75-84行目）。
  - xlsx記載: 「パスワード目玉アイコン：クリックするとパスワードのマスク表示を解除。もう一度押すとマスク(*)を掛ける」（ログイン画面!B36-37）— HTML実装と一致。
  - xlsx記載: 「ログインボタン：職員番号とパスワードで照合し、ログイン処理を行う」「退職している職員はログイン不可とする」（ログイン画面!B39-42）— この照合・退職者チェックロジックはHTML/JSには実装されていない（モックのため）。不明（要確認、Django実装時に必要な業務ロジック）。
  - 職員番号の値（`login-user` の value）は、ログイン後 `transitionTo('screen-menu')` 内で参照され、`"1"` の場合のみ保管画面の部署選択欄・検索画面の部署選択ボタンが表示される権限判定に使われる（後述）。つまりこのプロトタイプでは職員番号 `1` を管理者ロールとして扱っている。
- **画面遷移**:
  - この画面へ来る経路: 初期表示（`class="screen active"` が最初から付与されている）、または `screen-menu` からの「ログアウト」ボタン、各画面ヘッダーの「ログアウト」ボタン。
  - この画面から行ける先: `screen-menu`（ログインボタン）。
- **要再確認フラグ**: なし
- **HTML分割ファイル**: `HTML/html1/screens/screen-login.html`

---

## screen-menu — メイン画面

- **対応xlsxシート**: メイン画面
- **画面概要**: ログイン後の起点となるメニュー画面。検索・閲覧・変更／保管の機能への入口ボタンと、お知らせ、設定画面への導線を持つ。
- **表示項目**:
  - ヘッダー: システムサブタイトル「クラウド文書管理システム」、見出し「-メイン画面-」
  - ユーザー情報表示「総務部｜菅 理太郎」（固定文言、ログインユーザー情報のプレースホルダ。動的にログインユーザー名を反映する実装はHTML上なし＝不明・要確認）
  - お知らせ欄（`notice-area`）: 見出し「お知らせ」+ 3件の固定文言リスト
    - 「有効期限切れの文書が 20 件 あります。」
    - 「有効期限切れまで X ヶ月以内の文書が 10 件 あります。」
    - 「直近 X ヶ月内で削除された文書が 5 件 あります。」
    - xlsx（メイン画面!B36,B38）: 「Xヵ月」設定値は初期値1とし設定ファイル等で定義、先方変更依頼で容易に変更可能なこと（HTMLでは固定文言のまま、動的化は不明・要確認）
    - xlsx（メイン画面!C42,K42）: 「有効期限切れの文書」＝保存期間が本日日付を過ぎた文書のみ（隠し検索パラメータ：有効期限日）
    - xlsx（メイン画面!C44,K44）: 「有効期限切れまでXヵ月以内の文書」＝本日日付よりXヵ月以内に保存期間を過ぎる予定の文書のみ（隠し検索パラメータ：有効期限日）
    - xlsx（メイン画面!C46,K46）: 「直近Xヵ月以内で削除された文書」＝本日日付よりXヵ月以内に削除された文書のみ（隠し検索パラメータ：削除日）
    - xlsx（メイン画面!B48）: 契約書の保存期限は固定で10年とし、設定ファイル等で定義し容易に変更可能なこと
- **入力項目**: なし
- **一覧の列**: 該当なし
- **検索条件**: 該当なし
- **ボタン/アクション**:
  - 検索・閲覧・変更ゾーン（`menu-box search-zone`）
    - 「文書」ボタン → `onclick="transitionToSearch('document')"` で `screen-search` へ（文書検索モード）
    - 「契約書」ボタン → `onclick="transitionToSearch('contract')"` で `screen-search` へ（契約書検索モード）
    - 「電子決裁」ボタン → `disabled`（未実装、押下不可）
  - 保管ゾーン（`menu-box storage-zone`）
    - 「文書」ボタン → `onclick="transitionToStorage('document')"` で `screen-storage1` へ（文書保管モード）
    - 「契約書」ボタン → `onclick="transitionToStorage('contract')"` で `screen-storage1` へ（契約書保管モード）
  - お知らせ内リンク
    - 「20 件」リンク → `onclick="clickNoticeLink(1)"` （有効期限切れ文書 → `screen-search` へ遷移し文書モードで擬似検索結果20件を表示）
    - 「10 件」リンク → `onclick="clickNoticeLink(2)"` （有効期限切れまでXヶ月以内 → `screen-search` へ遷移し契約書モードで擬似検索結果10件を表示）※実装上typeが2の場合 `transitionToSearch('contract')` が呼ばれる点に注意（後述JS挙動）
    - 「5 件」リンク → `onclick="clickNoticeLink(3)"` （直近Xヶ月内削除文書 → `screen-search` へ遷移し文書モードで擬似検索結果5件を表示）
  - フッター: 「⚙️ 設定」ボタン（`menu-btn`）→ `onclick="goToSettings()"` で職員番号に応じたメニュー出し分けを行い `screen-settings` へ遷移（設定画面は担当外）
  - ヘッダー右上「ログアウト」ボタン → `onclick="transitionTo('screen-login')"`
- **JS挙動**:
  - `goToSettings()`: `login-user` の値を取得し `configureSettingsMenu(userId)` を呼んでから `screen-settings` へ遷移。
  - `configureSettingsMenu(userId)`: 職員番号が `'1'`/`'2'`/`'3'` の場合にそれぞれ異なる設定メニューボタン群（`.settings-btn`）だけを表示する権限別出し分け処理（設定画面詳細は担当外のため深追いせず）。
  - `transitionTo('screen-menu')` 実行時、職員番号（`login-user`の値）が `"1"` 以外なら `select-dept-div`（保管画面の部署選択欄）を非表示にする分岐処理あり（index.html 602-609行目）。※このロジックは `screen-menu` 表示時ではなく「`screen-menu` に遷移する瞬間」に評価される汎用 `transitionTo()` 関数内の特別扱いであり、実質は保管画面側の権限制御。
  - `clickNoticeLink(type)`: `type=2` の場合のみ `transitionToSearch('contract')`、それ以外（1,3）は `transitionToSearch('document')` を呼び、`screen-search` の検索結果テーブルに固定件数（20/10/5件）の擬似データを直接生成して表示する。ダブルクリックで詳細ポップアップ（`popup-detail`）を開き、`type` に応じて警告バナー文言・配色を変える（有効期限切れ＝赤系、削除済み＝紫系）。
- **画面遷移**:
  - この画面へ来る経路: `screen-login`（ログインボタン）、`screen-storage2` の「メイン画面に戻る」（`closeModalAndGoMenu()`）、`screen-search`/`screen-storage1`等の「＜ 戻る」ボタン（`transitionTo('screen-menu')`）。
  - この画面から行ける先: `screen-search`（文書/契約書）、`screen-storage1`（文書/契約書）、`screen-settings`（担当外）、`screen-login`（ログアウト）。
- **要再確認フラグ**: なし（xlsxのメイン画面シートには本文中に赤字セルは見当たらなかった）
- **HTML分割ファイル**: `HTML/html1/screens/screen-menu.html`

---

## screen-storage1 — 保管画面（文書選択）

- **対応xlsxシート**: 保管（[1]保管画面(文書) 1)文書選択 / [2]保管画面(契約書) 1)文書選択 と対応。文書・契約書で同一のDOMを共有）
- **画面概要**: 保管対象のファイルをドラッグ＆ドロップまたはファイル選択ダイアログで複数選択し、アップロード（モック処理）を実行する画面。
- **表示項目**:
  - ヘッダー: システムサブタイトル（`storage1-system-sub`、初期値「クラウド文書管理システム -文書管理-」、契約書モードでは「-契約書管理-」に切替）、見出し（`storage1-title`、初期値「保管画面」、契約書モードでは「契約書 保管画面」）
  - 「＜ 戻る」ボタン → `screen-menu` へ
  - 見出し「【文書選択】」
  - ドロップゾーン（`drop-zone`）案内文「ファイルを選択するか、またはここにドラッグ＆ドロップしてください！」
  - 選択済みファイル一覧表示欄（`selected-file-list`、選択後にJSで動的表示）
- **入力項目**:
  - ファイル選択（`input#file-input`, type=file, `multiple`属性あり＝複数選択可、非表示でボタン経由）
- **一覧の列**: 該当なし
- **検索条件**: 該当なし
- **ボタン/アクション**:
  - 「ファイルを選択」ボタン → `document.getElementById('file-input').click()` でファイル選択ダイアログを開く
  - 「実行」ボタン（`btn-primary`）→ `onclick="startUploadMock()"` でアップロードのモック処理（進捗オーバーレイ表示後に `screen-storage2` へ遷移）
- **JS挙動**:
  - ドラッグ＆ドロップ対応（`dragover`/`dragleave`/`drop`イベント、`dragover`クラスでスタイル変化）。ドロップされたファイルは `handleSelectedFiles()` で処理。
  - `handleSelectedFiles(files)`: 選択ファイル名一覧を `mockFiles` 配列に格納し、`selected-file-list` に「選択されたファイル (N個):」+ファイル名一覧を表示。
  - `startUploadMock()`:
    - 「登録」ボタン（`storage-submit-btn`）の文言とonclickを一旦「登録」/`startRegisterMock()`に初期化（編集画面から遷移してきた際の表示崩れをリセットする意図と推測）。
    - 完了モーダル（`overlay-modal`）の下部ボタン群を「続けて別の文書を登録する」「登録した文書を確認する」「メイン画面に戻る」の3ボタン構成にリセット。
    - `mockFiles` が0件の場合は `showModal("ファイルが選択されていません。")` で警告し処理中断。※`showModal(text)`関数は`document.getElementById('modal-text')`を参照するが、`overlay-modal`内に`id="modal-text"`の要素が存在しないため、実際にはこの分岐でJSエラーが発生し警告表示が機能しない不具合がある（下記「未解決・要確認事項まとめ」参照）。
    - ファイルがあれば `showProgress("アップロード中...", callback)` で進捗オーバーレイを表示し、完了後 `activeDocIndex=0` にリセットして `setupStorageFormForActiveDoc()` を呼び `screen-storage2` へ遷移。
  - xlsx記載（保管!B24-25）: 「ファイルを選択：ドラッグ＆ドロップ又は『ファイルを選択』ボタンで、複数のファイルを同時に選択出来ること」— HTML実装（`multiple`属性、DnD対応）と一致。
  - xlsx記載（保管!B27-28）: 「実行ボタン：選択したファイルのアップロード処理を行う」— HTML実装と一致（モック処理として進捗表示のみ）。
- **画面遷移**:
  - この画面へ来る経路: `screen-menu`「保管」ゾーンの「文書」/「契約書」ボタン（`transitionToStorage('document'|'contract')`）、`screen-storage2` の「キャンセル」ボタン（`cancelStorageRegistration()`）、完了モーダルの「続けて別の文書を登録する」ボタン（`closeModalAndGoStorage1()`）。
  - この画面から行ける先: `screen-storage2`（「実行」ボタン経由、アップロード成功時）、`screen-menu`（「＜ 戻る」）。
- **要再確認フラグ**: なし
- **HTML分割ファイル**: `HTML/html1/screens/screen-storage1.html`

---

## screen-storage2 — 保管画面（登録／編集フォーム）

- **対応xlsxシート**: 保管（[1]保管画面(文書) 2)登録・4)編集、[2]保管画面(契約書) 2)登録・4)編集 と対応。文書・契約書、登録・編集の4パターンを同一DOM＋JS切替で共有）
- **画面概要**: アップロードしたファイルのPDFプレビューと、部署・分類・年・カテゴリー・タイトル等のメタデータ入力フォームを左右に並べた登録・編集画面。文書モードと契約書モードで入力項目群が切り替わり、`triggerChangeFromDetail()` 経由で来た場合は編集モード（タイトルが「編集画面」に変わり、登録ボタンが更新ボタンに変わる）になる。
- **表示項目**:
  - ヘッダー: システムサブタイトル（`storage2-system-sub`）、見出し（`storage2-title`、初期「保管画面」/契約書「契約書 保管画面」/編集時「編集画面」に書き換わる）、「＜ 戻る」ボタン（`screen-storage1`へ）
  - PDFプレビュー領域（`pdf-preview-container`）: 拡大（＋）/縮小（－）ボタン、擬似PDFページ（`storage-pdf-page`、タイトルはファイル名を表示）
  - ページャー（`doc-pager-text`、例「1 / 5」）＋前へ（＜）/次へ（＞）ボタン（複数ファイルアップロード時に文書を切替）
  - フォームセクション:
    - [1] 保管先: 部署（管理者のみ表示・選択可、`select-dept-div`）／分類／年（プルダウン、2021〜2026年）／カテゴリー
    - [2] 文書情報: 文書タイトル（契約書モードでは「契約書タイトル」）／保存期間（文書モードのみ表示、契約書モードでは非表示）／契約関連項目（契約書モードのみ表示: 契約日・契約期間(開始～終了)・契約更新日・契約金額・契約先名）
    - [3] 個人情報（文書モード）／関連書類（契約書モード）: 見出し文言・内容がモードで切替（`lbl-storage-section-3`）
    - [4] メモ欄（`textarea#storage-memo`）＋「削除」ボタン（赤背景、フォーム内の明細行削除用と推測、onclick未設定＝不明・要確認）
  - 下部固定アクション: 「登録」ボタン（`storage-submit-btn`、編集時は「更新」に変化）／「キャンセル」ボタン
- **入力項目**:
  - 部署（`input#storage-dept`, readonly, 「選択」ボタンでポップアップ選択。表示条件: xlsx保管!B79-82「権限管理」で権限が"管理者"のログインユーザのみ表示、初期値はログインユーザーの部署名をセット。HTML側では職員番号"1"以外で非表示になるよう `transitionTo()` 内で制御 — ただしこの制御は `screen-menu` 遷移時に評価される実装のため、実際に保管画面表示前に正しく反映されるかはロジック上の疑問点。不明（要確認、動作検証要）。なお保存期間プルダウンの初期値ログインユーザー部署名自動セットはHTML未実装＝不明・要確認）
  - 分類（`input#storage-classification`, readonly, 「選択」ボタン → ポップアップ選択）
  - 年（`select#storage-year`, 2021〜2026年、初期値2026年選択済み。この行には`id="storage-year-row"`が付与されているが、`index.html`全文検索の結果このidを参照するJSは存在せず、`transitionToStorage()`にも年行の表示/非表示制御が実装されていない。したがって現状のHTMLでは契約書モードでも年欄は常に表示されたままになる。xlsx（検索・閲覧・変更/保管シート）にも年欄が契約書モードで非表示になるべきという明記は見当たらず、意図的な仕様か実装漏れかは不明・要確認）
  - カテゴリー（`input#storage-category`, readonly, 「選択」ボタン → ポップアップ選択）
  - 文書タイトル/契約書タイトル（`input#storage-title`, type=text, 初期値例「出張 精算書_1」）
  - 保存期間（`select#storage-period`, 1ヵ月/1年/3年(初期選択)/5年/10年/永年。`onchange="calculateExpiryDate()"` で有効期限を自動計算・表示。文書モードのみ表示）
  - 契約日（`input[type=date]#storage-contract-date`、契約書モードのみ表示）
  - 契約期間 開始/終了（`input[type=date]` ×2、契約書モードのみ）
  - 契約更新日（`input[type=date]`、契約書モードのみ）
  - 契約金額（`input[type=text]`, `onblur="formatCurrency(this)"` で3桁カンマ区切りフォーマット、単位「円」表示、契約書モードのみ）
  - 契約先名（`input[type=text]`、契約書モードのみ）
  - 個人情報が含まれる/含まれない（ラジオボタン `privacy-radio`, 「含まれる」が初期選択、文書モードのみ表示）
  - 関連書類ファイル選択（`input[type=file]`, `onchange="handleRelatedFileChange(this)"`、契約書モードのみ表示。1ファイル選択毎に次行が自動追加される仕組み。行削除は×ボタン `removeRelatedFileRow()`）
  - メモ欄（`textarea#storage-memo`, rows=3, placeholder「備考・補足事項等を入力」）
  - バリデーション規則: HTML/JS上に必須チェック等の明示的なバリデーションは見当たらない（不明・要確認）
- **一覧の列**: 該当なし（登録完了モーダル内の明細テーブルは「分類／年／カテゴリー／文書タイトル」の4列。複数ファイル一括登録時は全ファイル分の行が生成される）
- **検索条件**: 該当なし
- **ボタン/アクション**:
  - PDFズームボタン「－」「＋」→ `zoomPdf('storage-pdf-page', -0.1 / 0.1)`（0.5〜3.0倍の範囲でスケール変更、1.0倍超でドラッグスクロール可能になる）
  - ページャー「＜」「＞」→ `changeActiveDoc(-1 / 1)`（複数アップロード時のアクティブ文書切替、フォーム内容が再セットされる）
  - 部署/分類/年/カテゴリー「選択」ボタン → `openPopupPopup(this, type, 'storage')` で共通選択ポップアップ（`popup-select`）を開く
  - 関連書類の×ボタン → `removeRelatedFileRow(this)`（行削除、契約書モードのみ）
  - メモ欄下の「削除」ボタン → onclick未設定（機能不明・要確認）
  - 「登録」ボタン（新規時）→ `onclick="startRegisterMock()"`。「更新」ボタン（編集時、`triggerChangeFromDetail()`経由で書き換え）→ `onclick="startUpdateMock()"`
  - 「キャンセル」ボタン → 新規時は `cancelStorageRegistration()`（`screen-storage1`へ）。編集時は `triggerChangeFromDetail()` 内で `onclick` が `closeModal(); transitionToSearch(activeModule); startSearchAnimation();` に書き換えられ、検索画面に戻る動作に変化する。
- **JS挙動**:
  - `transitionToStorage(moduleType)`（`screen-menu`から呼ばれる入口）: `activeModule` を設定し、モードに応じてヘッダー文言・ラベル文言・表示/非表示（`hidden-field`クラスの付け外し）を一括切替。文書モード: 保存期間行表示・契約項目非表示・個人情報行表示・関連書類行非表示。契約書モード: その逆。その後 `screen-storage1` へ遷移。
  - `setupStorageFormForActiveDoc()`: ページャー文言更新、ファイル名からタイトル自動セット（拡張子除去）、PDFモックタイトル更新、分類/年/カテゴリー/メモをリセット、関連書類入力欄をリセット、`calculateExpiryDate()`呼び出し、前へ/次へボタンのdisabled制御（先頭/末尾で無効化）。
    - 注: `index.html` 801-823行目と1567-1589行目の2箇所で同名関数が定義されている（JSの関数宣言は後勝ちのため、実際に使われるのは1567行目版）。801行目版は `document.getElementById('storage-group')` を参照するが、フォーム内に`id="storage-group"`の要素は存在せず（実際の分類入力欄は`id="storage-classification"`）、801行目版がもし使われた場合はエラーになる古いコードの残骸と判断できる。1567行目版は正しく`storage-classification`を参照しており実害はないが、デッドコードとして残っている点はHTML再実装時に整理対象。
  - `calculateExpiryDate()`: 契約書モードでは何もしない。文書モードで、選択年＋保存期間から有効期限を計算し `expiry-date-calc` に「（有効期限：YYYY年12月末日）」等の形式で表示。保存期間「永年」（value=99）の場合は「（有効期限：永年）」、「1ヵ月」（value=0.083）の場合は「（有効期限：翌年1月末日）」。
  - `handleRelatedFileChange(input)`: 選択されたファイル名を表示し削除×ボタンに差し替え、次の空行を自動追加（契約書の関連書類、複数ファイル対応）。
  - `formatCurrency(inputElement)`: 契約金額欄の数値以外を除去し3桁カンマ区切りに整形（`onblur`時）。
  - `cancelStorageRegistration()`: `screen-storage1` へ遷移。
  - `startRegisterMock()`（1603-1647行目版が有効）: `showProgress("登録中...", callback)` 後、フォーム入力値（分類・年・カテゴリー・タイトル、無入力時はデフォルト値「総務部」「2026」「一般文書」「文書タイトル」を使用）と現在日時から登録完了モーダルの明細テーブル（`register-complete-tbody`）を生成。`mockFiles`が複数あれば全ファイル分の行を生成（アクティブ文書のみ入力タイトルを反映、他はファイル名ベース）。モーダルタイトルに「登録が完了しました。(登録日時：YYYY-MM-DD HH:MM)」を表示し `overlay-modal` を表示。
  - `triggerChangeFromDetail()`（検索結果詳細ポップアップの「変更」ボタンから呼ばれる編集モード開始処理）: 詳細ポップアップを閉じ、見出しを「編集画面」に変更、モードに応じたフィールド表示切替、登録ボタンを「更新」ボタン（`startUpdateMock()`）に、キャンセルボタンを検索画面へ戻る動作に書き換えた上で `screen-storage2` を表示。
  - `startUpdateMock()`: 現在日時取得、モーダルタイトルを「更新が完了しました。」に、明細テーブルを分類/年/カテゴリー/タイトルの1行に差し替え、モーダル下部ボタンを「検索・閲覧画面に戻る」の1ボタン中央配置に書き換えて `overlay-modal` を表示。
  - PDFズーム・ドラッグスクロール共通処理（`zoomPdf()`, `initDragScroll('storage-pdf-view-box')`）。
  - `openPopupPopup()`/`renderPopupPopupItems()`/`submitPopupPopupSelection()`: 部署・分類・年・カテゴリーの選択ポップアップ共通ロジック（詳細はscreen-search側と共通のため下記に記載）。
  - xlsx記載（保管!B78-87, 保管!C81）: 部署名「選択」ボタンは「権限管理」で権限が"管理者"のログインユーザーのみ表示。初期値はログインユーザーの部署名をセット。ポップアップから選択しテキストエリアへ文字列セット（単一選択、検索画面の複数選択とは異なる）。
  - xlsx記載（保管!B194-195）: 保存期間プルダウンは設定メニュー「保存期間設定」の"文書"で設定した保存期間リストをプルダウン化し表示する（HTMLは固定選択肢1ヵ月/1年/3年/5年/10年/永年のハードコード。動的なマスタ連携は不明・要確認＝将来Django実装時の対応事項）。
  - xlsx記載（保管!B197-198）: 削除ボタンは「誤ってアップロードした文書、不要な文書を削除する（本登録から除外する）」用途。HTML上の削除ボタン（メモ欄下）はonclick未設定で機能未実装（要確認）。
  - xlsx記載（保管!B200-201）: 登録ボタンは「アップロードした文書を、入力項目と紐付けて登録（保管）する」— HTML実装（`startRegisterMock()`）と一致（モック）。
  - xlsx記載（保管!B228-235、登録完了ポップアップの3ボタン）: 「続けて別の文書を登録する」→1)文書選択画面へ、「登録した文書を確認する」→文書検索画面へ遷移し検索結果一覧に表示、「メイン画面に戻る」→メイン画面へ。HTML実装（`closeModalAndGoStorage1()`/`closeModalAndGoSearch()`/`closeModalAndGoMenu()`）と一致。
  - xlsx記載（保管!B298-300, 4)編集）: 削除ボタンは初回登録から1週間以上経過しているものは削除不可。ボタンを非表示又はDisabledにする。HTML上この経過日数判定ロジックは未実装（モックのため、要確認・将来実装事項）。
  - xlsx記載（保管!B302-303, 更新ボタン）: 各項目を編集した内容で更新する — HTML実装（`startUpdateMock()`）と一致。
  - xlsx記載（保管!B324-325, 更新完了ポップアップの「検索・閲覧画面に戻る」ボタン）: 「文書検索画面」に遷移し検索結果一覧を更新する — HTML実装と一致。
  - 契約書側（[2]保管画面(契約書)）はxlsx上「保管画面(文書)と同じ」との記載が大半（B349,B352,B399,B402,B413,B416,B562,B565,B568,B571,B577,B580,B583）で、分類「選択」ボタン・カテゴリー「選択」ボタンのみ書類管理区分が"契約書管理"の分類/カテゴリーである点が差分（保管!B419, P430-431, B454, P459-460）。関連書類「ファイルの選択」ボタン（保管!B479-485）: 関連する文書を選択（文書管理とは別のためAI-OCR処理は不要、物理ファイルのみ紐付け）。1ファイル選択毎に次行に同ボタンを表示し複数紐付け可能。(X)ボタンで紐付け取り止め（行削除）。
- **画面遷移**:
  - この画面へ来る経路: `screen-storage1`の「実行」ボタン（`startUploadMock()`成功時）、検索結果詳細ポップアップの「変更」ボタン（`triggerChangeFromDetail()`、編集モード）。
  - この画面から行ける先: `screen-storage1`（「＜ 戻る」／新規時キャンセル）、`overlay-modal`（登録/更新完了モーダル表示）経由で`screen-storage1`（続けて登録）/`screen-search`（登録した文書を確認する・更新完了時「検索・閲覧画面に戻る」）/`screen-menu`（メイン画面に戻る）、編集時キャンセルは`screen-search`へ。
- **要再確認フラグ**: No.23（保管!X496「※画面は開発中のものです」＝登録完了ポップアップの画像モックのみ未完成。ただしHTMLの登録完了モーダル自体はテキスト実装済み。契約書側の登録完了ポップアップに対する赤字コメント）、No.24（保管!AA592「※画面は開発中のものです」＝更新完了ポップアップの画像モックのみ未完成。契約書側の更新完了ポップアップに対する赤字コメント）
- **HTML分割ファイル**: `HTML/html1/screens/screen-storage2.html`

---

## screen-search — 検索・閲覧画面（文書／契約書）

- **対応xlsxシート**: 検索・閲覧・変更（[1] 検索・閲覧・変更 1)検索・閲覧画面(文書)、2)詳細/変更(文書)、3)検索・閲覧画面(契約書) など。HTML上は文書・契約書ともに単一の `screen-search` divをJSで動的に書き換えて共有。加えて `popup-detail`（詳細ポップアップ、xlsx上の「2)検索・閲覧画面(文書)」＝PDF詳細部分、「4)検索・閲覧画面(契約書)」に相当）も密接に関連）
- **画面概要**: 検索条件を指定して文書または契約書を検索し、一覧表示・プレビュー・詳細ポップアップ表示・一括操作（選択/ダウンロード/編集）を行う画面。`activeModule`（'document'/'contract'）によって見出し・列構成・検索条件（部署名以外）が切り替わる。
- **表示項目**:
  - ヘッダー: システムサブタイトル（`.system-sub-title`、`updateSearchHeaderTitle()`で「-文書管理-」/「-契約書管理-」を切替）、見出し（`search-title`、「文書 検索・閲覧画面」/「契約書 検索・閲覧画面」）、「＜ 戻る」ボタン（`screen-menu`へ）
  - 検索結果件数表示（`search-count-text`、例「0 件」→検索実行後は件数に更新）
  - 検索結果一覧テーブル（`result-table`）＋ページャー（見た目のみ、1/2/3ページ固定でJS未接続＝実際のページング処理は不明・要確認）
  - 文書イメージプレビュー欄（一覧行クリックでプレビュー文言が切替。実PDF表示ではなく📄アイコン＋案内文言のモック）
- **入力項目（検索条件）**:
  - 部署名（`input#search-dept`, readonly, 初期値「本　店|総務部」。「選択」ボタン（`search-button-dept`）は職員番号"1"（管理者）のときのみ表示、`transitionToSearch()`内で制御。xlsx（検索・閲覧・変更!B49-52）: 表示条件は「権限が"管理者"」または「文書管理-部門間閲覧設定がONになっているログインユーザ」— HTMLは職員番号"1"判定のみで、部門間閲覧設定ONユーザーの分岐は未実装＝**要再確認No.18**）
  - 分類（`input#search-group`, readonly, 「選択」ボタン → ポップアップで複数選択、カンマ区切りでセット）
  - 年（`input#search-year`, readonly, 「選択」ボタン → ポップアップ選択）
  - カテゴリー（`input#search-category`, readonly, 「選択」ボタン → ポップアップで複数選択）
  - 有効期限日／有効期限切れ（ラジオ：含まない/含む/有効期限切れのみ）／削除日／削除文書（ラジオ：含まない/含む/削除文書のみ）: いずれも `style="display:none;"` で非表示の隠しフィールド（xlsx記載の「隠し検索パラメータ」＝メイン画面のお知らせリンク遷移時に内部的に使う想定のフィールドと推測されるが、実際に`clickNoticeLink()`がこれらのinput値をセットする実装にはなっていない＝不明・要確認）
  - 文書/契約書タイトル（`input#search-title`, placeholder「タイトルを入力　キーワードスペース区切り」）＋ラジオ「いずれかを含む（OR、初期選択）」/「すべて含む（AND）」（`name="title-and-or"`）
  - フリーワード（`input#search-freeword`, placeholder「フリーワードを入力　キーワードスペース区切り」）＋ラジオ「いずれかを含む（OR、初期選択）」/「すべて含む（AND）」（`name="freeword-and-or"`）
  - 期間（`input[type=date]#search-save-date-start` ～ `#search-save-date-end`）＋ラジオ「保存日（初期選択）」/「保存満了日」（`name="save-day-kbn"`）
  - 保存期間プルダウン（`save-period-tr`行、選択肢は指定なし/1ヵ月/1年/3年/5年/10年/永年のハードコード固定。契約書モードでは行ごと非表示。xlsx（検索・閲覧・変更!B182-184）: 「保存済み全文書に紐付けられている保存期間を重複なしで抽出しプルダウン化する（日数の短い順昇順）。※『保存期間設定』で設定したデータは使用しない」＝**要再確認No.19**。HTMLはハードコード選択肢のため実データ抽出ロジックは未実装＝要確認）
- **一覧の列**（文書モード）: 選択（チェックボックス）／No.（ソート可）／文書タイトル（ソート可）／保存情報（ソート可）／保管・更新者（ソート可）／保存日（ソート可）／保存期間（ソート可）／保存満了日（ソート可）／更新日時（ソート可）
- **一覧の列**（契約書モード）: 選択／No.／契約書タイトル／保存情報／契約日／契約更新日／契約終了日／契約先名／保管・更新者／保存日／保存満了日／更新日時（いずれもソート可）
- **検索条件**: 上記入力項目群。文書タイトル／フリーワードはそれぞれ独立してAND/OR切替可能（xlsx: スペース区切りでOR＝いずれかを含む、AND＝すべて含む）。「検索開始」ボタンと「条件クリア」ボタンあり。
- **ボタン/アクション**:
  - 「検索開始」ボタン（`btn-primary`）→ `onclick="startSearchAnimation()"`（進捗オーバーレイ表示後、擬似検索結果50件を生成表示）
  - 「条件クリア」ボタン（`btn-cancel`）→ `onclick="clearSearchForm()"`（分類・年・カテゴリー・タイトル・フリーワード・期間開始/終了をクリア。部署名はクリア対象外）
  - 「一括選択」ボタン（`btn-toggle-all`）→ `toggleAllCheckboxes()`（全行チェックON/OFFトグル、文言も「一括選択」⇔「一括解除」で切替）
  - 「一括ダウンロード」ボタン → onclick未設定（機能未実装、モック。xlsx記載の権限制御も未実装＝**要再確認No.20/No.22関連**、下記参照）
  - 「一括編集」ボタン → onclick未設定（機能未実装、モック）
  - 列ソートボタン（各列見出しの▼/▲）→ `sortTable(colIndex, type, this)`（num/date/str型に応じた昇順・降順切替ソート、押下毎にトグル）
  - 一覧行クリック → プレビュー欄の文言を該当行タイトルに更新
  - 一覧行ダブルクリック → `openDetailPopup(docTitle)` で詳細ポップアップ（`popup-detail`）を表示
- **JS挙動**:
  - `transitionToSearch(moduleType)`: `activeModule`設定、ヘッダー文言切替、職員番号"1"以外なら部署「選択」ボタン非表示、契約書モードでは保存期間行を非表示・タイトルラベルを「契約書」に変更・一覧ヘッダーを契約書用12列に差し替え。文書モードではその逆（9列）。その後 `clearSearchForm()`・検索結果クリア・件数「0 件」表示・`screen-search`へ遷移・`updateSearchHeaderTitle()`呼び出し。
  - `startSearchAnimation()`: `showProgress("検索中...", callback)`後 `renderSearchResultTable()`を呼ぶ。
  - `renderSearchResultTable()`: 常に固定50件の擬似データを生成（ベース日2026-04-15から1日ずつ加算）。契約書モード・文書モードでそれぞれ列内容が異なる行HTMLを生成。偶数行は背景色`#E7E7E7`。各行にクリック（プレビュー更新）・ダブルクリック（`openDetailPopup()`）イベントを付与。
  - `toggleAllCheckboxes()`: `.row-checkbox`全チェックボックスの状態を一括トグル。
  - `openDetailPopup(docTitle)`: 詳細ポップアップのタイトル・PDFモックタイトルを設定、警告バナーを一旦非表示にし、`activeModule`に応じて文書用/契約書用のプロパティテーブル（部署・分類・年・カテゴリー・保存期間や契約情報等の固定モックデータ）を生成して表示。
  - `closeDetailPopup()`: ポップアップを非表示に。
  - 詳細ポップアップ内ボタン: 「ダウンロード」（onclick未設定、機能未実装＝**要再確認No.20/21/22関連**、下記参照）／「変更」→`triggerChangeFromDetail()`（`screen-storage2`へ編集モードで遷移）／「削除」→`triggerDeleteFromDetail()`（`confirm()`で確認後、`showModal("文書を削除しました。")`＋`renderSearchResultTable()`再描画。契約書判定分岐は無く文言は常に「文書」表記＝契約書時も同一文言。不明・要確認。なお`showModal()`自体に`modal-text`要素不在の不具合があり実際には正常動作しない、下記まとめ参照）
  - `clickNoticeLink(type)`: `screen-menu`から呼ばれるが、検索結果を直接生成する処理のため本画面のJS挙動としても記載（詳細は`screen-menu`の項参照）。type=1（期限切れ、赤系バナー）/type=2（契約書更新まもなく、契約書モード・赤系バナー）/type=3（削除済み、紫系バナー）。
  - 部署/分類/年/カテゴリー選択ポップアップ共通ロジック:
    - `openPopupPopup(btn, type, mode)`: `mode='search'`の場合、検索条件のポップアップとして開く。ポップアップタイトルを種別に応じて設定（分類選択/対象年選択/カテゴリー選択/部署選択）。`type='year'`の場合は検索キーワード入力欄を非表示にする。
    - `renderPopupPopupItems()`: `popupPopupMasterData`（ハードコードされたマスタ配列: group=分類A〜H、year=2026〜2020年、category=6種、dept=14部署）から一覧を描画。`mode='search'`かつ`type='group'`の場合のみ「全て選択／全て解除」チェックボックスを先頭行に追加し、全項目チェック済みなら自動的にチェック状態にする。`mode='search'`の場合は各項目をチェックボックス（複数選択）、それ以外（storage）はラジオボタン（単一選択）として描画。
    - `filterPopupPopupItems()`: 検索キーワード入力に応じて`renderPopupPopupItems()`を再実行（部分一致フィルタ）。
    - `submitPopupPopupSelection()`: `mode='search'`はチェック済み項目をカンマ区切りで対象inputにセット。それ以外はラジオ選択値をセット（`storage-year`の場合は`calculateExpiryDate()`も呼ぶ）。
    - ポップアップはドラッグ移動・リサイズ可能（`popup-select-header`のmousedown/mousemove、`popup-select-resize`ハンドル）。
  - `zoomPdf()` / `initDragScroll('detail-pdf-view-box')`: 詳細ポップアップ内PDFプレビューのズーム・ドラッグスクロール（`screen-storage2`と共通ロジック）。
  - `sortTable(colIndex, type, btnElement)`: 列ヘッダーの▼/▲切替、num/date/str型でソート、DOM上の行を並べ替えて再配置。
  - `formatCurrency()`は本画面では未使用（storage2専用）。
  - xlsx記載（検索・閲覧・変更!B189-192, 検索ボタン）: 「指定された検索条件で"文書"の検索処理を行う」「各検索条件に入力された文字は、数字の半角全角、カタカナの半角全角、アルファベットの半角全角を問わず検索できるようにする」— HTMLは検索処理自体が固定モックデータ生成のため、実際の全半角吸収検索ロジックは未実装（要確認、Django実装時の対応事項）。
  - xlsx記載（検索・閲覧・変更!B231-254, 一覧表示）: 初期ソート順「保存日・降順」（HTML初期表示では未ソート状態で描画、`sortTable()`呼び出しは行われていない＝不明・要確認）。ソート可能列は仕様通りHTMLに実装。「検索結果が1万件を超える場合はソートに時間が掛かる旨アラート表示」はHTML未実装（モックのため要確認）。「一覧表の明細部は内部スクロール」「ページャーは1ページ50件程度」「総件数表示」「明細クリックでプレビュー」「ダブルクリックで詳細ポップアップ」はHTML実装済み（ただしページャーは見た目のみでページング未接続）。
  - xlsx記載（検索・閲覧・変更!B257-268, 一括系ボタン）: 一括選択ボタンの挙動はHTML実装済み。一括ダウンロード（ZIP圧縮での複数ファイルDL）・一括編集（複数選択文書の編集画面遷移）はHTML未実装（onclick未設定のモック）。
  - xlsx記載（検索・閲覧・変更!B334-339, 契約書はB619-624）: 「変更」ボタン→編集画面遷移はHTML実装済み（`triggerChangeFromDetail()`）。「削除」ボタンは「文書/契約書保存から1週間以上経過しているものは削除不可、ボタンをdisabledにする」— HTMLの`triggerDeleteFromDetail()`にはこの経過日数判定は未実装（常に`confirm()`のみ、要確認）。
  - xlsx記載（検索・閲覧・変更!B341-342, 契約書はB626-628）: 「有効期限切れの場合、画面上部に『有効期限が切れています』のメッセージを表示」— HTML実装は`popup-detail`内`detail-alert-banner`で近い文言「この文書は有効期限切れです」等を表示する仕組みがあるが、通常検索結果からのダブルクリック（`openDetailPopup()`）時は毎回`alertBanner.style.display = "none"`にリセットされ、`clickNoticeLink()`経由（お知らせリンクからの遷移）時のみバナーが表示される実装になっている。通常検索結果一覧から有効期限切れ文書を開いた場合にバナーが出ない可能性があり、xlsx仕様（一覧表示条件下での自動バナー表示）と実装の整合性は不明・要確認。
- **要再確認フラグ（詳細）**:
  - No.18（検索・閲覧・変更!C52）: 部署名「選択」ボタンの表示条件「文書管理-部門間閲覧設定がONになっているログインユーザ」がHTML未実装（職員番号"1"判定のみ）。
  - No.19（検索・閲覧・変更!B184）: 保存期間プルダウンについて「保存期間設定」で設定したデータは使用しない旨の注記。HTMLはハードコード固定選択肢のため実データ抽出ロジック自体が未実装（今後の実装時に留意）。
  - No.20（検索・閲覧・変更!B263-264）: 一覧の「一括ダウンロード」ボタンは「権限管理」で文書管理-文書-ダウンロードがONのユーザのみ可、権限が無いユーザはボタンdisabled。HTMLは権限制御未実装（onclick自体も未設定）。
  - No.21（検索・閲覧・変更!B328-329）: 詳細ポップアップの「ダウンロード」ボタン（文書）も同様の権限制御が必要。HTML未実装（onclick未設定）。
  - No.22（検索・閲覧・変更!B616-617）: 契約書の詳細ポップアップ「ダウンロード」ボタンは「文書管理-契約書-ダウンロード」がONのユーザのみ可。HTML未実装（文書・契約書でダウンロードボタンのonclick処理自体が分岐しておらず共通で未設定）。
- **画面遷移**:
  - この画面へ来る経路: `screen-menu`「検索・閲覧・変更」ゾーンの「文書」/「契約書」ボタン（`transitionToSearch()`）、`screen-menu`お知らせリンク（`clickNoticeLink()`）、完了モーダルの「登録した文書を確認する」（`closeModalAndGoSearch()`）、更新完了モーダルの「検索・閲覧画面に戻る」、編集画面（`screen-storage2`）キャンセルボタン（編集時）。
  - この画面から行ける先: `screen-menu`（「＜ 戻る」／ログアウトで`screen-login`）、`screen-storage2`（詳細ポップアップ「変更」ボタン、編集モード）、詳細ポップアップ（`popup-detail`、同一画面上のオーバーレイ）、選択ポップアップ（`popup-select`、部署/分類/年/カテゴリー選択）。
- **要再確認フラグ**: No.18, No.19, No.20, No.21, No.22（詳細は上記「要再確認フラグ（詳細）」参照）
- **HTML分割ファイル**: `HTML/html1/screens/screen-search.html`

---

## 補足: 共通ポップアップ／オーバーレイ（参考情報）

担当5画面の分割対象ではないが、上記画面のJS挙動に密接に関わるため参考として記載する（`index.html` 462〜565行目、専用の分割HTMLファイルは今回作成していない）。

- **popup-detail**（文書/契約書 詳細プロパティポップアップ）: `screen-search`の一覧ダブルクリックおよび`clickNoticeLink()`から呼ばれる。有効期限切れ等の警告バナー、PDFプレビュー（ズーム/ドラッグスクロール対応）、プロパティ一覧、ダウンロード/変更/削除ボタンを持つ。
- **popup-select**（部署/分類/年/カテゴリー 選択ポップアップ）: `screen-storage2`と`screen-search`の両方から`openPopupPopup()`で呼ばれる共通コンポーネント。検索画面では複数選択（チェックボックス、分類のみ「全て選択」機能あり）、保管画面では単一選択（ラジオボタン）。ドラッグ移動・リサイズ可能。
- **overlay-progress**（進捗オーバーレイ）: `showProgress(msg, callback)`で表示。アップロード中/登録中/更新中/検索中の擬似プログレスバー（0→100%を10%刻みで自動進行、完了後コールバック実行）。
- **overlay-modal**（登録/更新完了モーダル）: `startRegisterMock()`/`startUpdateMock()`/`clickNoticeLink()`関連処理から`showModal()`または直接`style.display`操作で表示。分類/年/カテゴリー/タイトルの明細テーブルとアクションボタン（続けて登録する/確認する/メイン画面に戻る、または更新時は検索画面に戻るのみ）を持つ。No.23・No.24の「画面は開発中」赤字コメントは、xlsx上ではこのモーダルの契約書版（画像モック部分）に対する注記。

---

## 未解決・要確認事項まとめ（担当分）

- ログイン処理（職員番号・パスワード照合、退職者チェック）の実装はHTML上モックのみで、実際の認証ロジックは今回のHTMLからは判断不可（不明・要確認）。
- お知らせ欄の「Xヶ月」設定値の動的化（設定ファイル等での変更）はHTML上未実装（固定文言）。
- 保管画面フォームの「削除」ボタン（メモ欄下）はonclick未設定で機能不明。
- 保存期間プルダウン（保管・検索の両方）は仕様上マスタ連携が必要だがHTMLはハードコード。
- 検索画面の一括ダウンロード／一括編集ボタン、詳細ポップアップのダウンロードボタンは、権限制御（No.20〜22）を含めて機能未実装。
- 削除ボタンの「1週間以上経過で削除不可」制御（保管編集・検索詳細ポップアップ双方）はHTML未実装。
- ページャー（検索結果一覧下部の1/2/3ページ切替）はJS未接続で見た目のみ。
- `setupStorageFormForActiveDoc()`関数がHTML内で2回定義されており（801行目版・1567行目版）、参照フィールドIDが異なる（`storage-group` vs `storage-classification`）。後方定義が有効なため実害はないが、実装移行時に注意が必要。
- **バグ所見**: `showModal(text)`関数（index.html 1450-1453行目）は `document.getElementById('modal-text')` を参照するが、`overlay-modal`内には`id="modal-text"`の要素が存在しない（実在するのは`modal-title`）。そのため`showModal()`が呼ばれる箇所（`screen-storage1`のファイル未選択警告、`screen-search`詳細ポップアップの削除完了通知）では実際にはJSエラーが発生し、意図した警告/通知メッセージが表示されない不具合がHTMLプロトタイプ内に存在する。Django実装時はメッセージ表示の仕様（本来何と表示すべきだったか）を別途確認の上で実装する必要がある。
