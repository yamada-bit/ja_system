# 画面棚卸し表（第三陣: 分類マスタ〜その他設定）

- 対象HTML: `C:\Users\yamad\Claude\JA\HTML\html1\index.html`（担当範囲 2663〜3437行目、実測で確認済み）
- 対応Excel: `C:\Users\yamad\Claude\JA\HTML\文書管理システム_簡易設計指示書_Rev1_0.xlsx`
- HTML分割ファイル格納先: `C:\Users\yamad\Claude\JA\HTML\html1\screens\`
- 本ドキュメントの記載内容はHTML/xlsxに実際に書かれている内容のみ。旧実装(`ja_pj_old`)からの類推は一切含めていない。不明点は「不明（要確認）」と明記。

## 重要な事前注意（構造上の発見）

作業指示で挙げられた20画面名のうち、以下の3つは **`class="screen"` を持つ独立した画面divではない**。実際のHTMLを確認した結果、`screen-retention-delete` 画面内部の `<tr>`/`<td>` 要素IDおよび `screen-other-main` 画面内部のページャー`<div>`のIDであることを確認した。誤って別画面として実装しないよう、下記に明記する。

- `screen-retention-delete-doc`: `screen-retention-delete`画面内の `<tr id="screen-retention-delete-doc" style="display:none;">`（書類名行、電子決裁選択時のみ表示）
- `screen-retention-delete-doc-txt`: 同じ行内の `<td id="screen-retention-delete-doc-txt">`（書類名の値を表示するセル）
- `screen-other-main-pager`: `screen-other-main`画面内の `<div id="screen-other-main-pager" class="pager-bottom">`（メイン画面項目タブ選択時のみ表示するページャー。`class="screen"`ではない）

したがって独立画面としてのHTML分割ファイルはこの3つについては作成していない（該当箇所は親画面のファイルに含まれている）。棚卸し表としては、指示に従い20項目分の見出しを用意し、上記3つには「画面ではない」旨を記載した。

---

## screen-class-list — 分類管理一覧

- **対応xlsxシート**: 分類管理（[1] 分類管理一覧、A6セル以降）
- **画面概要**: 分類マスタ（分類コード・分類名・書類管理区分）の一覧を表示する画面。設定メニューからの入口。
- **表示項目**: システム名、画面タイトル「- 分類管理一覧 -」、ログインユーザー情報（総務部｜菅 理太郎、デモ用固定表示）
- **入力項目**（検索条件欄。詳細は検索条件参照）: なし（一覧本体に入力項目はない）
- **一覧の列**: 分類コード / 分類名 / 書類管理区分 / 文書件数 / 操作
  - 分類コード・文書件数は右寄せ、分類名・書類管理区分は左寄せ（HTMLの`style="text-align:..."`指定より）
  - 操作列は「編集」ボタン（常に有効）と「削除」ボタン（xlsxのB68「文書件数が0件の分類のみ削除ボタンを有効化」に対応。HTML上でも文書件数0のデータ行のみ削除ボタンが`btn-danger`かつ有効、他行は`disabled`属性付き）
- **検索条件**: 分類名（プルダウン、選択肢は(全て)/分類Ａ〜Ｉの静的リスト）、書類管理区分（プルダウン、(全て)/文書管理/契約書管理）。AND/OR切替の記載やUIはHTML上に無し。検索ボタンあり（onclick未実装、押下時の挙動はHTML上に記載なし＝不明（要確認））
- **ボタン/アクション**:
  - 「設定メニューへ戻る」→ `transitionTo('screen-settings')`
  - 「＋ 新規登録」→ `transitionTo('screen-class-regist')`
  - 各行「編集」→ `transitionTo('screen-class-edit')`
  - 各行「削除」（0件の行のみ有効）→ `transitionTo('screen-class-delete')`
  - 「ログアウト」→ `transitionTo('screen-login')`
  - ページャー（«, ＜, 1, 2, 3, ＞, »）: 1ページ目のみ`active`、«と＜は`disabled`。クリック時の遷移onclickはHTML上に無し＝不明（要確認、xlsx B62「1ページあたり50件程度表示」の指示のみ）
- **JS挙動**: このdiv自体にインラインscriptは無し。表示切替等のロジックはこの画面には無い（静的な一覧表示のみ）。
- **画面遷移**: 
  - 遷移元: `screen-settings`の「分類管理」ボタン（`id="btn-class-manage"`）、および class-regist/class-edit/class-deleteの「キャンセル」「登録」「更新」「削除」ボタン
  - 遷移先: `screen-settings`（戻る）、`screen-class-regist`（新規登録）、`screen-class-edit`（編集）、`screen-class-delete`（削除、0件行のみ）、`screen-login`（ログアウト）
- **要再確認フラグ**: なし
- **HTML分割ファイル**: `HTML/html1/screens/screen-class-list.html`

---

## screen-class-regist — 分類管理登録

- **対応xlsxシート**: 分類管理（[2] 分類管理登録、A94セル以降）
- **画面概要**: 分類マスタの新規登録画面。
- **表示項目**: システム名、画面タイトル「- 分類管理登録 -」（この画面のヘッダーには`user-info`〈ログイン中ユーザー表示・ログアウトボタン〉が無い＝HTML上そのまま。他の一覧・削除画面と異なりヘッダーが簡略化されている点はそのまま記録）
- **入力項目**:
  - 分類コード: text input、初期値空、幅100px。必須/バリデーション規則はHTML上に記載なし。xlsx B119「分類コードの重複登録は出来ないように制御」の指示あり（フロント実装はHTML上に無し＝不明・要確認）
  - 分類名: text input、初期値空。バリデーション記載なし
  - 書類管理区分: select（文書管理／契約書管理）。xlsxでは「権限管理」の設定に応じて選択肢を出し分ける指示あり（B113〜116）が、HTML上は常に両方表示（デモのため固定と思われるが実装上は不明・要確認）
- **一覧の列**: 該当なし
- **検索条件**: 該当なし
- **ボタン/アクション**:
  - 「キャンセル」→ `transitionTo('screen-class-list')`
  - 「登録」→ `confirmInsert('screen-class-list')`（confirm('登録してよろしいですか？')後、screen-class-listへ遷移。実際のDB登録処理はHTML上になし＝デモのため）
- **JS挙動**: このdiv自体にインラインscriptは無し。共通scriptの`confirmInsert()`関数（index.html 3506〜3508行目、担当外の共通script部分）を利用。
- **画面遷移**: 遷移元は`screen-class-list`の「＋ 新規登録」。遷移先は`screen-class-list`のみ（キャンセル・登録とも）。
- **要再確認フラグ**: なし
- **HTML分割ファイル**: `HTML/html1/screens/screen-class-regist.html`

---

## screen-class-edit — 分類管理編集

- **対応xlsxシート**: 分類管理（[3] 分類管理編集、A139セル以降。B158「※新規登録画面と同様」）
- **画面概要**: 分類マスタの編集画面。登録画面と同じ入力構成に、既存データの初期値が入っている。
- **表示項目**: システム名、画面タイトル「- 分類管理編集 -」（登録画面と同様、user-info無し）
- **入力項目**:
  - 分類コード: text input、初期値`000`（デモデータ）、幅100px
  - 分類名: text input、初期値`分類Ａ`（デモデータ）
  - 書類管理区分: select（文書管理／契約書管理）
  - xlsx B161「分類コード変更時の重複更新は出来ないように制御」の指示あり（フロント実装はHTML上に無し＝不明・要確認）
- **一覧の列**: 該当なし
- **検索条件**: 該当なし
- **ボタン/アクション**:
  - 「キャンセル」→ `transitionTo('screen-class-list')`
  - 「更新」→ `confirmUpdate('screen-class-list')`
- **JS挙動**: インラインscript無し。共通の`confirmUpdate()`を利用。
- **画面遷移**: 遷移元は`screen-class-list`各行の「編集」ボタン（どの行から遷移してもデモデータは固定で`分類Ａ/000`が表示される＝HTMLがハードコードのため実データ連動なし）。遷移先は`screen-class-list`のみ。
- **要再確認フラグ**: なし
- **HTML分割ファイル**: `HTML/html1/screens/screen-class-edit.html`

---

## screen-class-delete — 分類管理削除

- **対応xlsxシート**: 分類管理（[4] 分類管理削除、A184セル以降）
- **画面概要**: 分類マスタの削除確認画面。
- **表示項目**: システム名、画面タイトル「- 分類管理削除 -」、user-info（ログイン中ユーザー・ログアウト、この画面には有り）、確認メッセージ「以下の分類を削除します。よろしいですか？」、対象データ（分類コード=188、分類名=分類Ｃ、書類管理区分=文書管理、いずれもデモ用固定値）
- **入力項目**: なし（表示のみ、編集不可）
- **一覧の列**: 該当なし
- **検索条件**: 該当なし
- **ボタン/アクション**:
  - 「キャンセル」→ `transitionTo('screen-class-list')`
  - 「削除」→ `confirmDelete('screen-class-list')`
- **JS挙動**: インラインscript無し。共通の`confirmDelete()`を利用。xlsx B204「分類マスタから論理削除とする。(保存済みデータに影響ない事)」の業務要件あり（実装はバックエンド側の話でHTML上には現れない）
- **画面遷移**: 遷移元は`screen-class-list`の「削除」ボタン（文書件数0件の行のみ有効）。遷移先は`screen-class-list`のみ。
- **要再確認フラグ**: なし
- **HTML分割ファイル**: `HTML/html1/screens/screen-class-delete.html`

---

## screen-cat-list — カテゴリー管理一覧

- **対応xlsxシート**: カテゴリー管理（[1] カテゴリー管理一覧、A6セル以降）
- **画面概要**: カテゴリーマスタ（カテゴリーコード・カテゴリー名・書類管理区分・分類）の一覧画面。
- **表示項目**: システム名、画面タイトル「- カテゴリー管理一覧 -」、user-info
- **入力項目**: なし（一覧本体）
- **一覧の列**: カテゴリーコード / カテゴリー名 / 書類管理区分 / 分類 / 文書件数 / 操作
  - カテゴリーコード・文書件数は右寄せ、カテゴリー名は左寄せ（`text-align`指定）
  - 削除ボタンは文書件数0件の行のみ有効（class-listと同様のパターン。xlsx B71と一致）
- **検索条件**: カテゴリー名（テキスト入力、placeholder「キーワード検索」。xlsx B36「カテゴリー名の部分一致検索とする。(スペース区切りの複合検索は考慮しない）」の指示あり）、分類名（プルダウン、(全て)/分類Ａ〜Ｅ）、書類管理区分（プルダウン、(全て)/文書管理/契約書管理）。検索ボタンあり（onclick未実装、AND/OR切替UIはHTML上に無し）
- **ボタン/アクション**:
  - 「設定メニューへ戻る」→ `transitionTo('screen-settings')`
  - 「＋ 新規登録」→ `transitionTo('screen-cat-regist')`
  - 各行「編集」→ `transitionTo('screen-cat-edit')`
  - 各行「削除」（0件行のみ）→ `transitionTo('screen-cat-delete')`
  - 「ログアウト」→ `transitionTo('screen-login')`
  - ページャー: class-listと同様、クリック時の遷移処理はHTML上に無し（不明・要確認）
- **JS挙動**: インラインscript無し
- **画面遷移**: 遷移元は`screen-settings`の「カテゴリー管理」ボタン（`id="btn-cat-manage"`）、および各下位画面のキャンセル/登録/更新/削除ボタン。遷移先は`screen-settings`、`screen-cat-regist`、`screen-cat-edit`、`screen-cat-delete`、`screen-login`
- **要再確認フラグ**: なし
- **HTML分割ファイル**: `HTML/html1/screens/screen-cat-list.html`

---

## screen-cat-regist — カテゴリー管理登録

- **対応xlsxシート**: カテゴリー管理（[2] カテゴリー管理登録、A91セル以降）
- **画面概要**: カテゴリーマスタの新規登録画面。
- **表示項目**: システム名、画面タイトル「- カテゴリー管理登録 -」、user-info（この画面にはヘッダーにuser-info有り、class-registとは構成が異なる点をそのまま記録）
- **入力項目**:
  - カテゴリーコード: text input、初期値空、幅100px
  - カテゴリー名: text input、初期値空
  - 分類: select（分類Ａ〜Ｅ）。xlsx B111「「分類管理」メニューで設定した分類名リストを表示する」に対応
  - 書類管理区分: select（文書管理／契約書管理）
  - xlsx B119「カテゴリーコードの重複登録は出来ないように制御」の指示あり（フロント実装はHTML上に無し・不明）
- **一覧の列**: 該当なし
- **検索条件**: 該当なし
- **ボタン/アクション**:
  - 「キャンセル」→ `transitionTo('screen-cat-list')`
  - 「登録」→ `confirmInsert('screen-cat-list')`
- **JS挙動**: インラインscript無し
- **画面遷移**: 遷移元は`screen-cat-list`の「＋ 新規登録」。遷移先は`screen-cat-list`のみ。
- **要再確認フラグ**: なし
- **HTML分割ファイル**: `HTML/html1/screens/screen-cat-regist.html`

---

## screen-cat-edit — カテゴリー管理編集

- **対応xlsxシート**: カテゴリー管理（[3] カテゴリー管理編集、A133セル以降。B152「※新規登録画面と同様」）
- **画面概要**: カテゴリーマスタの編集画面。
- **表示項目**: システム名、画面タイトル「- カテゴリー管理編集 -」、user-info
- **入力項目**:
  - カテゴリーコード: text input、初期値`001`（デモデータ）
  - カテゴリー名: text input、初期値`カテゴリーＡ`（デモデータ）
  - 分類: select（分類Ａ〜Ｅ）
  - 書類管理区分: select（文書管理／契約書管理）
  - xlsx B155「カテゴリーコード変更時の重複更新は出来ないように制御」の指示あり（フロント実装はHTML上に無し・不明）
- **一覧の列**: 該当なし
- **検索条件**: 該当なし
- **ボタン/アクション**:
  - 「キャンセル」→ `transitionTo('screen-cat-list')`
  - 「更新」→ `confirmInsert('screen-cat-list')` ※重要: HTMLソース上、この更新ボタンは`confirmUpdate`ではなく`confirmInsert('screen-cat-list')`を呼び出している（index.html 2954行目）。確認ダイアログの文言は「登録してよろしいですか？」になってしまう（`confirmInsert`の実装のため）。class-editでは同じ更新ボタンが正しく`confirmUpdate`を使っているのと対照的で、cat-editのみの実装差異。HTMLの記述をそのまま棚卸ししている。挙動として意図的なものか誤記かはHTML単体からは判断できない
- **JS挙動**: インラインscript無し。なお共通script内に`confirmCatUpdate()`/`confirmCatDelete()`という専用関数（3518〜3523行目）が定義されているが、cat-edit/cat-delete画面のどのボタンからも呼び出されておらず、未使用（デッドコード）。
- **画面遷移**: 遷移元は`screen-cat-list`各行の「編集」。遷移先は`screen-cat-list`のみ。
- **要再確認フラグ**: なし（新規発見の赤字箇所ではないが、上記「更新ボタンがconfirmInsertを呼ぶ」実装上の疑問点は完了報告で言及する）
- **HTML分割ファイル**: `HTML/html1/screens/screen-cat-edit.html`

---

## screen-cat-delete — カテゴリー管理削除

- **対応xlsxシート**: カテゴリー管理（[4] カテゴリー管理削除、A175セル以降）
- **画面概要**: カテゴリーマスタの削除確認画面。
- **表示項目**: システム名、画面タイトル「- カテゴリー管理削除 -」、user-info、確認メッセージ「以下のカテゴリーを削除します。よろしいですか？」、対象データ（カテゴリーコード=010、カテゴリー名=カテゴリーＤ、分類=分類Ａ、書類管理区分=契約書管理、デモ用固定値）
- **入力項目**: なし
- **一覧の列**: 該当なし
- **検索条件**: 該当なし
- **ボタン/アクション**:
  - 「キャンセル」→ `transitionTo('screen-cat-list')`
  - 「削除」→ `confirmDelete('screen-cat-list')`
- **JS挙動**: インラインscript無し。xlsx B196「カテゴリーマスタから論理削除とする。(保存済みデータに影響ない事)」の業務要件あり
- **画面遷移**: 遷移元は`screen-cat-list`の「削除」ボタン（文書件数0件の行のみ有効）。遷移先は`screen-cat-list`のみ。
- **要再確認フラグ**: なし
- **HTML分割ファイル**: `HTML/html1/screens/screen-cat-delete.html`

---

## screen-retention-doc — 保存期間設定（一覧）

- **対応xlsxシート**: 保存期間設定（[1] 保存期間設定一覧、A6セル以降）
- **画面概要**: 「文書」と「電子決裁」でラジオボタン切替できる保存期間マスタの一覧画面。電子決裁選択時はさらに書類名（稟議書／経費支出伺）のプルダウンで一覧を絞り込む。
- **表示項目**: システム名、画面タイトル「- 保存期間設定 -」、user-info
- **入力項目**（一覧絞り込み用）:
  - ラジオボタン「文書」（value=1、デフォルトchecked）／「電子決裁」（value=2）: `onchange="kbnSelectForDocSave(this.value)"`
  - 書類名プルダウン（電子決裁選択時のみ表示、`id="doc-select-pulldown"`が`display:none`⇔表示を切替）: 稟議書／経費支出伺、`onchange="kbnSelectForDocSave(this.value)"`
  - 「表示」ボタン（`master-search-panel`内、onclick未実装＝不明・要確認）
- **一覧の列**: No. / 保存期間 / 表示順 / 操作
  - `<tbody>`が3種類切替式で存在: `doc-save-table-tbody1`（文書用、6件: 1ヵ月〜永年）、`doc-save-table-tbody2`（電子決裁・稟議書用、4件）、`doc-save-table-tbody3`（電子決裁・経費支出伺用、3件）。ラジオ／プルダウンの選択に応じて`kbnSelectForDocSave()`がdisplay切替で表示するtbodyを決定
- **検索条件**: 該当なし（上記ラジオ・プルダウンが絞り込み条件）
- **ボタン/アクション**:
  - 「設定メニューへ戻る」→ `transitionTo('screen-settings')`
  - 「＋ 新規登録」→ `transitionTo('screen-retention-regist-doc')`
  - 各行「編集」→ `transitionTo('screen-retention-edit-doc')`
  - 各行「削除」→ `transitionTo('screen-retention-delete')`
  - 「ログアウト」→ `transitionTo('screen-login')`
- **JS挙動**:
  - `kbnSelectForDocSave(value)`（共通script、3550〜3618行目）: valueが'1'（文書）の場合、書類名プルダウン欄・書類名行を全て非表示にし、tbody1のみ表示、削除確認画面の書類名行(`screen-retention-delete-doc`)も非表示にする。valueが'1'以外（電子決裁）の場合、プルダウン欄・書類名行を表示し、選択された書類名（`doc-pulldown-select`の値）に応じてtbody2（稟議書）またはtbody3（経費支出伺以外）を表示する。あわせて`.retention-kbn`クラスを持つ全要素（登録・編集画面のタイトル内span、削除確認画面のtd等）のテキストを「文書」/「電子決裁」に、`.select-doc-name-str`クラスを持つ全要素のテキストを「稟議書」/「経費支出伺」に更新する（画面をまたいだ連動更新）。
  - このdiv内に別途`<script>`タグで`docAndAppJudge()`という空の関数（中身なし、3052〜3057行目）が定義されているが、呼び出し箇所が無く未使用（デッドコード）。このscriptはdivの外側（screen-retention-docの`</div>`の後、screen-retention-regist-docの前）に位置しており、厳密にはどちらのdivにも属さない独立したscriptブロックである。
  - 画面初期表示時（`screen-settings`から`transitionTo('screen-retention-doc')`で遷移した直後）は`kbnSelectForDocSave()`は呼ばれない。HTMLの初期状態（ラジオ「文書」checked、tbody1表示、プルダウン欄非表示）がそのままデフォルト表示となる。
- **画面遷移**: 遷移元は`screen-settings`の「保存期間設定」ボタン（`id="btn-retention-setting"`）、および regist/edit/deleteの各キャンセル・登録・更新・削除ボタン（すべて`screen-retention-doc`へ戻る）。遷移先は`screen-settings`、`screen-retention-regist-doc`、`screen-retention-edit-doc`、`screen-retention-delete`、`screen-login`
- **要再確認フラグ**: なし
- **HTML分割ファイル**: `HTML/html1/screens/screen-retention-doc.html`

---

## screen-retention-regist-doc — 保存期間設定登録（文書／電子決裁）

- **対応xlsxシート**: 保存期間設定（[2] 保存期間設定(文書)新規登録 A50〜、[5] 保存期間設定(電子決裁)新規登録 A168〜。B188「※他は、文書の新規登録画面と同様」との記載通りHTML上も1つのdivで両方を兼用）
- **画面概要**: 保存期間マスタの新規登録画面。文書／電子決裁の種別によりタイトルと書類名欄の表示が動的に変わる。
- **表示項目**: システム名、画面タイトル「- 保存期間設定登録(<span class="retention-kbn">文書</span>) -」（span部分はJSで「文書」⇔「電子決裁」に切替）、user-info
- **入力項目**:
  - 書類名（`id="doc-pulldown1"`の行、初期状態`display:none`。電子決裁選択時のみ表示）: `<span class="select-doc-name-str">`にJSで「稟議書」または「経費支出伺」を挿入する表示専用セル（入力コントロールではない）
  - 保存期間: text input（`id="save-period-txt1"`、初期値空、幅50px）＋ 単位select（ヵ月／年／永年、初期選択「ヵ月」、`onchange="handlePermanent(this)"`）
  - 表示順: text input（初期値空、幅50px）
  - xlsx B77「保存期間や表示順の重複登録は出来ないように制御」（文書）、B191「書類名毎の保存期間や表示順の重複登録は出来ないように制御」（電子決裁）の指示あり（フロント実装はHTML上に無し・不明）
  - xlsx B73「「永年」を選択した場合「保存期間」の数値をクリアし、数値を入力出来ないようにする(readonly)」、B74「※「永年」設定値は、初期値を50年とし、設定ファイル等で定義し、先方より変更依頼を受けた際に容易に変更できること」
- **一覧の列**: 該当なし
- **検索条件**: 該当なし
- **ボタン/アクション**:
  - 「キャンセル」→ `transitionTo('screen-retention-doc')`
  - 「登録」→ `confirmInsert('screen-retention-doc')`
- **JS挙動**: `handlePermanent(selectElement)`（共通script、3492〜3505行目）: 単位selectで「永年」を選択すると`save-period-txt1`（このdivの場合。edit画面では`save-period-txt2`も同時に対象になる実装）の値を空にしてdisabled化。それ以外を選択すると両方disabled解除。
- **画面遷移**: 遷移元は`screen-retention-doc`の「＋ 新規登録」。遷移先は`screen-retention-doc`のみ。
- **要再確認フラグ**: なし
- **HTML分割ファイル**: `HTML/html1/screens/screen-retention-regist-doc.html`

---

## screen-retention-edit-doc — 保存期間設定編集（文書／電子決裁）

- **対応xlsxシート**: 保存期間設定（[3] 保存期間設定(文書)編集 A85〜、[6] 保存期間設定(電子決裁)編集 A210〜。いずれも「※新規登録画面と同様」）
- **画面概要**: 保存期間マスタの編集画面。登録画面と同じ構成に既存値が入る。
- **表示項目**: システム名、画面タイトル「- 保存期間設定編集(<span class="retention-kbn">文書</span>) -」（JSで文書／電子決裁を切替）、user-info
- **入力項目**:
  - 書類名（`id="doc-pulldown2"`の行、初期`display:none`）: `select-doc-name-edit`セル内`<span class="select-doc-name-str">`にJSで表示更新
  - 保存期間: text input（`id="save-period-txt2"`、初期値`1`＝デモデータ、幅50px）＋ 単位select（ヵ月／年／永年、初期選択「ヵ月」、`onchange="handlePermanent(this)"`）
  - 表示順: text input（初期値`1`＝デモデータ、幅50px）
- **一覧の列**: 該当なし
- **検索条件**: 該当なし
- **ボタン/アクション**:
  - 「キャンセル」→ `transitionTo('screen-retention-doc')`
  - 「更新」→ `confirmUpdate('screen-retention-doc')`
- **JS挙動**: `handlePermanent()`は登録画面と共通（同じ関数がtxt1/txt2両方を制御）
- **画面遷移**: 遷移元は`screen-retention-doc`各行の「編集」。遷移先は`screen-retention-doc`のみ。
- **要再確認フラグ**: なし
- **HTML分割ファイル**: `HTML/html1/screens/screen-retention-edit-doc.html`

---

## screen-retention-delete — 保存期間設定削除

- **対応xlsxシート**: 保存期間設定（[4] 保存期間設定(文書)削除 A127〜、[7] 保存期間設定(電子決裁)削除 A251〜）
- **画面概要**: 保存期間マスタの削除確認画面。文書／電子決裁の種別により書類名行の表示有無が切り替わる。
- **表示項目**: システム名、画面タイトル「- 保存期間設定削除 -」、user-info、確認メッセージ「以下の設定を削除します。よろしいですか？」
- **表示データ**（すべて表示専用、デモ用固定値）:
  - No.: 1
  - 書類名（`<tr id="screen-retention-delete-doc" style="display:none;">`）: 初期は非表示。`kbnSelectForDocSave()`により電子決裁選択時のみ表示され、`<td id="screen-retention-delete-doc-txt">`にJSで書類名を挿入。**この`<tr>`と`<td>`は独立した画面ではなく、本画面(`screen-retention-delete`)内部の要素**（棚卸し表冒頭の「重要な事前注意」を参照）
  - 保存期間: 1ヵ月（固定）
  - 表示順: 1（固定）
- **入力項目**: なし
- **一覧の列**: 該当なし
- **検索条件**: 該当なし
- **ボタン/アクション**:
  - 「キャンセル」→ `transitionTo('screen-retention-doc')`
  - 「削除」→ `confirmDelete('screen-retention-doc')`
- **JS挙動**: 表示切替ロジックは`screen-retention-doc`側の`kbnSelectForDocSave()`が担っており、本画面固有のインラインscriptは無い。xlsx B146/B271「保存期間マスタから論理削除とする。(保存済みデータに影響ない事)」の業務要件あり
- **画面遷移**: 遷移元は`screen-retention-doc`各行の「削除」。遷移先は`screen-retention-doc`のみ。
- **要再確認フラグ**: なし
- **HTML分割ファイル**: 親画面`screen-retention-doc`ではなく`screen-retention-delete`が独立divのため`HTML/html1/screens/screen-retention-delete.html`に含まれる（内部の`<tr id="screen-retention-delete-doc">`もこのファイルに含まれる）

---

## screen-retention-delete-doc — （独立画面ではない：screen-retention-delete内部の`<tr>`要素）

- **対応xlsxシート**: 該当なし（独立画面ではないため）
- **画面概要**: 独立した画面ではない。`screen-retention-delete`画面内にある`<tr id="screen-retention-delete-doc" style="display:none;">`という行要素のID。電子決裁の保存期間削除時のみ「書類名」の行を表示するための表示制御用ID。詳細は`screen-retention-delete`の項を参照。
- **表示項目**: （上記参照）
- **入力項目**: 該当なし
- **一覧の列**: 該当なし
- **検索条件**: 該当なし
- **ボタン/アクション**: 該当なし
- **JS挙動**: `kbnSelectForDocSave()`関数（共通script 3550〜3618行目）内で`document.getElementById('screen-retention-delete-doc')`として参照され、`style.display`を`''`（表示）または`'none'`（非表示）に切り替えられる
- **画面遷移**: 該当なし（画面ではないため遷移の概念なし）
- **要再確認フラグ**: なし
- **HTML分割ファイル**: 独立ファイルなし。`HTML/html1/screens/screen-retention-delete.html`に含まれる

---

## screen-retention-delete-doc-txt — （独立画面ではない：screen-retention-delete内部の`<td>`要素）

- **対応xlsxシート**: 該当なし（独立画面ではないため）
- **画面概要**: 独立した画面ではない。`screen-retention-delete-doc`行の中の`<td id="screen-retention-delete-doc-txt"></td>`セル要素のID。書類名（稟議書／経費支出伺）の値をJSで挿入する表示先。
- **表示項目**: （上記参照）
- **入力項目**: 該当なし
- **一覧の列**: 該当なし
- **検索条件**: 該当なし
- **ボタン/アクション**: 該当なし
- **JS挙動**: `kbnSelectForDocSave()`内で`docDeleteTx.innerHTML = docSelectVal.value;`により、書類名プルダウンで選択された値（稟議書／経費支出伺の生の値）がそのまま挿入される
- **画面遷移**: 該当なし
- **要再確認フラグ**: なし
- **HTML分割ファイル**: 独立ファイルなし。`HTML/html1/screens/screen-retention-delete.html`に含まれる

---

## screen-log-list — 操作履歴ログ

- **対応xlsxシート**: 操作履歴ログ（[1] 操作履歴ログ、A6セル以降）
- **画面概要**: 全操作の履歴ログ一覧を検索・表示する画面。CSV出力ボタン（デモのため機能しない）あり。
- **表示項目**: システム名、画面タイトル「- 操作履歴ログ -」、user-info
- **入力項目**（検索条件欄。詳細は検索条件参照のみで、一覧本体に入力項目は無い）
- **一覧の列**: 操作日時 / 職員番号 / 部署名 / 職員名 / 操作内容 / イベントメッセージ / 個人情報
  - 部署名・職員名・イベントメッセージは左寄せ（style指定）
  - 個人情報列は「○」が入る行と空の行がある（xlsx B43「チェックを入れて検索すると、個人情報書類フラグがセットされている文書を扱ったイベントのみ抽出する」に対応するフラグ列）
  - デモデータ25件、操作内容の例: カテゴリー管理新規登録／権限管理更新／文書ダウンロード／ログイン／パスワード更新／ログアウト／契約書検索／文書閲覧／文書アップロード／文書削除／文書編集／文書検索 等
  - xlsx B63「操作内容は「画面名 ＋ □(全角スペース) ＋ ボタン名」とする」、B65以降にイベントメッセージの連結フォーマット例（職員マスタ更新例／文書検索例／文書閲覧・ダウンロード等例）の記載あり。デモデータの「イベントメッセージ」列の実データはこのフォーマット例に概ね沿っている
- **検索条件**:
  - 操作日（日付範囲、`<input type="date">` × 2、「〜」区切り、id=`search-ctrl-date-start`/`search-ctrl-date-end`）
  - 職員名（テキスト、placeholder「キーワード検索」。xlsx B37「職員名の部分一致検索とする。(スペース区切りの複合検索は考慮しない　※職員名に全角半角スペースが入っている為)」）
  - イベントメッセージ（テキスト、placeholder「キーワード検索」。xlsx B40「イベントメッセージの文字列　部分一致検索とする。(スペース区切りの複合検索を考慮した方がよい？)」＝xlsx上でも検討中の書きぶり）
  - 個人情報書類（チェックボックス、ラベル「個人情報書類」）
  - AND/OR切替のUIはHTML上に無し。検索ボタンあり（onclick未実装、不明・要確認）
- **ボタン/アクション**:
  - 「設定メニューへ戻る」→ `transitionTo('screen-settings')`
  - 「検索」→ onclick未実装（不明・要確認）
  - 「CSV出力」→ `alert('CSV出力はデモ機能のため動作しません')`（実際のCSV出力処理は無し）
  - 「ログアウト」→ `transitionTo('screen-login')`
  - ページャー（1〜9ページ分のボタンあり、1ページ目のみactive、«・＜はdisabled）: クリック時の遷移はHTML上に無し（不明・要確認）
- **JS挙動**: インラインscript無し
- **業務要件（xlsx記載、HTML未実装または画面外の要件）**:
  - B48〜49「操作履歴ログの最大保存件数(=CSV出力最大件数)設定値は、初期値を3ヵ月分とし、設定ファイル等で定義し、先方より変更依頼を受けた際に容易に変更できること」
- **画面遷移**: 遷移元は`screen-settings`の「操作履歴ログ」ボタン（`id="btn-history-log"`）。遷移先は`screen-settings`、`screen-login`のみ（他の下位画面には遷移しない、一覧のみの画面）
- **要再確認フラグ**: なし
- **HTML分割ファイル**: `HTML/html1/screens/screen-log-list.html`

---

## screen-other-pass — その他設定（パスワード編集）

- **対応xlsxシート**: その他設定（[4] その他設定-パスワード編集-　(権限：管理者以外)、A129セル以降）
- **画面概要**: 一般職員（管理者以外）向けの「その他設定」画面。パスワード変更のみを行う。HTML上のid名は`screen-other-pass`だが、xlsx上の名称は「その他設定　-パスワード編集-」。
- **表示項目**: システム名、画面タイトル「- その他設定 -」（xlsxの個別タイトルとはHTML表記がやや異なる点をそのまま記録）、user-info、ラジオボタン「パスワード」（value="pass"、checked、他の選択肢はこのdiv内には存在しない＝管理者以外はメイン画面項目タブが無いことに対応）、現在のパスワード（表示のみ、`<td>ja1111</td>`＝デモ用平文表示、inputではない）
- **入力項目**:
  - 変更後パスワード: `<input type="password" id="new-pass">`
  - 変更後パスワード(確認): `<input type="password" id="new-pass-confirm">`
  - 一致チェック等のバリデーション処理はHTML上に無し（不明・要確認。xlsx B150「入力した内容で職員マスタを更新する」の記載のみで、確認用パスワードとの一致チェックの明記はxlsx上にも無い）
- **一覧の列**: 該当なし
- **検索条件**: 該当なし
- **ボタン/アクション**:
  - 「クリア」→ `clearPassFields()`（`new-pass`・`new-pass-confirm`の値を空にする）
  - 「更新」→ `alert('更新しました')`（実際の更新処理・画面遷移は無し。他の画面のような`confirmUpdate()`は使われていない点に注意）
  - 「ログアウト」→ `transitionTo('screen-login')`
- **JS挙動**: `clearPassFields()`（共通script 3486〜3489行目）のみ。「設定メニューへ戻る」ボタンはこの画面には無い（他の設定系画面と異なる点をそのまま記録）
- **画面遷移**: 遷移元は`screen-settings`の「その他設定」ボタン（`id="btn-other-setting"`、`onclick="onEnterOtherSettings();"`）経由。`onEnterOtherSettings()`関数（共通script 3441〜3462行目）が、`id="login-user"`の値が`"2"`または`"3"`の場合にこの画面へ遷移させる（デフォルト値は`"1"`のため、初期状態では通常この画面には来ない）。遷移先は「更新」ボタン押下時はalertのみで画面遷移なし、「クリア」も画面内のみ、ログアウトのみ`screen-login`へ遷移。
- **要再確認フラグ**: なし
- **HTML分割ファイル**: `HTML/html1/screens/screen-other-pass.html`

---

## screen-other-main — その他設定（メイン画面項目／自動ログアウト時間）

- **対応xlsxシート**: その他設定（[1] その他設定　(権限：管理者のみ)、A6セル以降）
- **画面概要**: 管理者向けの「その他設定」画面。「メイン画面項目」（部署ごとのメニューボタン表示制御一覧）と「自動ログアウト時間」をラジオボタンで切替表示する。
- **表示項目**: システム名、画面タイトル「- その他設定 -」、user-info
- **入力項目**（表示切替用）: ラジオボタン「メイン画面項目」（value="main"、デフォルトchecked）／「自動ログアウト時間」（value="logout"）、`onchange="kbnSelectForOtherSettings(this.value)"`
- **一覧の列**（メイン画面項目タブ、`id="other-setting-menu"`テーブル。2段ヘッダー）:
  - 1段目: No.（rowspan2） / 部署（rowspan2） / 検索・閲覧・変更（colspan3） / 保管（colspan2） / 操作（rowspan2）
  - 2段目: 文書 / 契約書 / 電子決裁（検索・閲覧・変更配下）、文書 / 契約書（保管配下）
  - デモデータ12件（本店|理事〜ジャスポート広川）、各セルは〇／×で表示。xlsx B38「部署マスタとメニューボタン制御テーブルを結合した一覧を表示」に対応
- **一覧の列**（自動ログアウト時間タブ、`id="other-setting-logout"`テーブル、初期`display:none`）: 項目 / 設定値 / 操作。デモデータ1件（自動ログアウト時間＝60分）
- **検索条件**: 該当なし（検索欄はこの画面には無い）
- **ボタン/アクション**:
  - 「設定メニューへ戻る」→ `transitionTo('screen-settings')`
  - メイン画面項目タブ各行「編集」→ `transitionTo('screen-other-main-edit')`
  - 自動ログアウト時間タブの行「編集」→ `transitionTo('screen-other-logout-edit')`
  - 「ログアウト」→ `transitionTo('screen-login')`
  - ページャー（`id="screen-other-main-pager"`、メイン画面項目タブ選択時のみ表示。**独立画面ではなく本画面内のdiv**、「重要な事前注意」参照）
- **JS挙動**: `kbnSelectForOtherSettings(value)`（共通script 3621〜3636行目）: valueが'main'の場合、`other-setting-menu`テーブル表示・`other-setting-logout`テーブル非表示・ページャー表示。それ以外（'logout'）の場合は逆（メニューテーブル非表示・ログアウト時間テーブル表示・ページャー非表示）。
- **画面遷移**: 遷移元は`onEnterOtherSettings()`（`screen-settings`の「その他設定」ボタン経由）で、`login-user`が`"2"`/`"3"`以外（デフォルト`"1"`含む）の場合にこの画面へ遷移。また`screen-other-main-edit`・`screen-other-logout-edit`の「キャンセル」「更新」からも戻ってくる。遷移先は`screen-settings`、`screen-other-main-edit`、`screen-other-logout-edit`、`screen-login`
- **要再確認フラグ**: なし
- **HTML分割ファイル**: `HTML/html1/screens/screen-other-main.html`

---

## screen-other-main-pager — （独立画面ではない：screen-other-main内部のページャーdiv）

- **対応xlsxシート**: 該当なし（独立画面ではないため）
- **画面概要**: 独立した画面ではない。`screen-other-main`画面内の`<div id="screen-other-main-pager" class="pager-bottom">`。`class="screen"`は付与されておらず、画面遷移の対象ではない。メイン画面項目タブ選択時のみ表示され、自動ログアウト時間タブ選択時は非表示になるページャーUI。
- **表示項目**: ページャーボタン（«, ＜, 1, 2, 3, ＞, »。1ページ目のみactive、«・＜はdisabled）
- **入力項目**: 該当なし
- **一覧の列**: 該当なし
- **検索条件**: 該当なし
- **ボタン/アクション**: 各ページ番号ボタンのonclickはHTML上に無し（不明・要確認）
- **JS挙動**: `kbnSelectForOtherSettings()`内で`document.getElementById('screen-other-main-pager')`として参照され、`style.display`を切り替えられる
- **画面遷移**: 該当なし（画面ではないため）
- **要再確認フラグ**: なし
- **HTML分割ファイル**: 独立ファイルなし。`HTML/html1/screens/screen-other-main.html`に含まれる

---

## screen-other-main-edit — メイン画面項目編集

- **対応xlsxシート**: その他設定（[2] その他設定-メイン画面項目編集-　(権限：管理者のみ)、A51セル以降）
- **画面概要**: 部署ごとのメイン画面ボタン表示可否（検索・閲覧・変更／保管）を編集する画面。
- **表示項目**: システム名、画面タイトル「- メイン画面項目編集 -」、user-info、No.（表示のみ、デモ値9）、所属部署（表示のみ、デモ値「本　所|ＤＸ推進課」）
- **入力項目**:
  - 検索・閲覧・変更: チェックボックス3つ（文書／契約書／電子決裁、いずれもデモ値checked）
  - 保管: チェックボックス2つ（文書／契約書、いずれもデモ値checked）
  - xlsx B73「未設定の部署 及び 新規登録された部署のデフォルトは全てチェックボックスOFF状態とする」という初期値要件あり（このデモ編集画面は既存データ想定のため全てcheckedになっていると考えられる）
- **一覧の列**: 該当なし
- **検索条件**: 該当なし
- **ボタン/アクション**:
  - 「設定メニューへ戻る」→ `transitionTo('screen-settings')`
  - 「キャンセル」→ `transitionTo('screen-other-main')`
  - 「更新」→ `confirmUpdate('screen-other-main')`
- **JS挙動**: インラインscript無し
- **画面遷移**: 遷移元は`screen-other-main`のメイン画面項目タブ各行「編集」ボタン。遷移先は`screen-settings`、`screen-other-main`
- **要再確認フラグ**: なし
- **HTML分割ファイル**: `HTML/html1/screens/screen-other-main-edit.html`

---

## screen-other-logout-edit — 自動ログアウト時間編集

- **対応xlsxシート**: その他設定（[3] その他設定-自動ログアウト時間編集-　(権限：管理者のみ)、A88セル以降）
- **画面概要**: 自動ログアウトまでのアイドル時間（分）を編集する画面。
- **表示項目**: システム名、画面タイトル「- 自動ログアウト時間編集 -」、user-info（この画面には「設定メニューへ戻る」ボタンが無い点をそのまま記録＝他の設定編集系画面と異なる）
- **入力項目**:
  - 時間(分): text input（初期値`60`＝デモデータ、幅50px）、右に「分」の文字表示
  - xlsx B102「自動ログアウト(タイムアウト)の時間数値を入力」、B103「本設定値にて、ブラウザで何も操作していないアイドル時間経過後、自動ログアウト処理させること」の業務要件あり（実際のタイムアウト処理はHTML上に実装なし＝画面外の要件）
- **一覧の列**: 該当なし
- **検索条件**: 該当なし
- **ボタン/アクション**:
  - 「キャンセル」→ `transitionTo('screen-other-main')`
  - 「更新」→ `confirmUpdate('screen-other-main')`
- **JS挙動**: インラインscript無し
- **画面遷移**: 遷移元は`screen-other-main`の自動ログアウト時間タブの「編集」ボタン。遷移先は`screen-other-main`のみ
- **要再確認フラグ**: なし
- **HTML分割ファイル**: `HTML/html1/screens/screen-other-logout-edit.html`

---

## 担当範囲に関連する共通script（担当画面div外だが直接関わるため参考記載）

以下はindex.html内で担当20画面のいずれのdivにも属さない「共通script」ブロック（3439〜3637行目付近）に定義されている関数群で、担当画面の挙動を理解する上で必須のため参考として記載する。分割HTMLファイルには含めていない（指示通り、div外のためsplitの対象外）。

- `onEnterOtherSettings()`（3441〜3462行目）: 「その他設定」ボタン押下時に呼ばれる。`id="login-user"`の値が`"2"`または`"3"`なら`screen-other-pass`へ、それ以外（デフォルト`"1"`含む）なら`screen-other-main`へ遷移。内部で`document.getElementById('tab-main-items')`を参照しているが、**このID(`tab-main-items`)を持つ要素はindex.html全体を検索しても存在しない**（担当範囲・担当外含めて確認）。`if (mainItemsTab)`でnullガードされているため実害は無いが、意図された要素が実装されていない可能性がある＝要再確認候補（xlsxの赤字指定リストには含まれていないため「要再確認フラグ」としては起票しないが、完了報告で言及する）
- `onEnterOtherSettingsForRadio()`（3465〜3483行目）: 定義されているが、index.html全体を検索しても呼び出し箇所が無い＝未使用のデッドコード。加えて内部に`docSelectPd.style.disp;ay = 'none';`という記述があり（`display`の途中にセミコロンが入っている）、仮に呼び出されたとしても構文的に意図通り動作しない。呼ばれないため実害はないが記録しておく。
- `clearPassFields()`（3486〜3489行目）: `screen-other-pass`の「クリア」ボタンから使用
- `handlePermanent(selectElement)`（3492〜3505行目）: `screen-retention-regist-doc`・`screen-retention-edit-doc`の保存期間単位selectから使用
- `confirmInsert(targetScreen)` / `confirmUpdate(targetScreen)` / `confirmDelete(targetScreen)`（3506〜3514行目）: 汎用の確認ダイアログ→遷移関数。担当画面の大半のボタンで使用
- `confirmCatUpdate()` / `confirmCatDelete()`（3518〜3523行目）: カテゴリー管理専用として定義されているが、`screen-cat-edit`・`screen-cat-delete`のどのボタンからも呼び出されておらず未使用のデッドコード
- `kbnSelectForDocSave(value)`（3550〜3618行目）: `screen-retention-doc`のラジオ・プルダウンから使用。詳細は該当画面の項を参照
- `kbnSelectForOtherSettings(value)`（3621〜3636行目）: `screen-other-main`のラジオから使用。詳細は該当画面の項を参照

---

## Excel（xlsx）赤字セルの確認結果

作業指示に基づき、担当5シート（分類管理／カテゴリー管理／保存期間設定／操作履歴ログ／その他設定）の全セルをopenpyxlでフォント色チェックした。**フォント色がFFFF0000（赤）のセルは1件も見つからなかった**。したがって「要再確認フラグ: 新規発見」に該当する項目はなし。
