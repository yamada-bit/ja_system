# HTML確定版への作り直し チェックリスト（アーカイブ：Rev1.4以降の詳細記録）

このファイルは[HTML_REIMPL_CHECKLIST.md](HTML_REIMPL_CHECKLIST.md)から、完了済み作業の詳細な
実装経緯・監査結果・バグ修正ログを切り出したアーカイブである（2026-08-24に分割、2026-09-07に
さらに初期分を[HTML_REIMPL_CHECKLIST_ARCHIVE2.md](HTML_REIMPL_CHECKLIST_ARCHIVE2.md)へ再分割。
方針は[[feedback_html_checklist_archive_split]]）。

**このファイルにはRev1.4改訂の反映（2026-08-28）以降の記録のみが入っている**。それより前
（Phase 0〜8の作り直し・原本フィデリティ監査・Rev1.1〜Rev1.3期）は
[HTML_REIMPL_CHECKLIST_ARCHIVE2.md](HTML_REIMPL_CHECKLIST_ARCHIVE2.md)を参照。

**新規セッションが通常参照すべきはHTML_REIMPL_CHECKLIST.mdのみ**。このアーカイブは特定の過去の
判断・バグ修正の詳しい経緯を掘り下げたい時にのみ参照する。一般化済みの運用ルールはCLAUDE.md
「原本フィデリティに関する運用方針」に集約済み。今後の新規記録はこのファイルの末尾に追記する。

---

## 原本HTML改訂差分の確認（html4→html5）・簡易設計指示書 Rev1.4改訂の反映（2026-08-28）

### 受領物と機械diffの結果
- `HTML/html5/index.html`（+ 同ディレクトリ`style.css`）、`HTML/文書管理システム_簡易設計指示書_Rev1_4.xlsx`。
- **xlsx（Rev1_3→Rev1_4 / Rev1_2→Rev1_4）のセル文言diff**：実質改訂は「保管」シートのみ。
  Rev1.3で「不要文言削除」として消していた説明文言（B194-195 保存期間プルダウン／B197-198 削除ボタン／
  B200-201 登録ボタン）を「Rev1.4 不要文言復活」として元に戻し（AI195）、「図1：スクロールの続き」の
  説明画像追加マーカー（V71/T395、AI71/AI395）が付いただけ。**新しい業務挙動の追加はゼロ**。
  復活した文言の挙動は「保管画面２『削除』ボタンをメモ消去→…へ変更（2026-08-27）」節で実装済み。
- **埋め込み画像のハッシュ突き合わせ**：Rev1_3→Rev1_4で`image69.png`/`image70.png`が新規追加
  （保管シートdrawing13、`srcRect`クロップあり・白塗りsp矩形なし）。内容は文書／契約書の登録
  フォームを下端までスクロールした状態の図で、[4]メモ欄ボックスの**外側**に赤い「削除」ボタンが
  独立配置されている（html5のHTML変更と対応、下記B項）。`image19`/`image20`（権限管理、Rev1.2→Rev1.3で
  差し替え済み）はRev1.4では無変更。
- **html4→html5のHTML実体diff**は大きいが、大半は**モックHTMLがRev1.2/Rev1.3の指示書内容に
  ようやく追いついたもの**で、ja_pj側は指示書ベースで先行実装済み（分類・カテゴリー管理の部署列、
  メイン画面お知らせの契約書対応、権限管理編集レイアウトのRev1.3化、権限管理一覧の契約書情報変更列・
  編集ボタンのピンク化）。html5で**新規に**発生した反映対象は下記A〜Eのみ。洗い出しの詳細は
  受領時レポート（scratchpad `html5_rev1_4_diff_report.md`）に記録。

### A. 権限管理一覧：「操作」列を横スクロール追従（固定）列にする
- **差分**：html5で`<th class="sticky-col col-6">操作</th>` ＋ 行セル`<td class="sticky-col-td col-td-6">`、
  style.cssに`.col-6 { left: 382px; z-index: 200 !important; }`・`.col-td-6 { left: 382px; }`を追加。
  「操作」列を権限付与フラグ群の前へ置く列順自体はRev1.2で反映済み、Rev1.3の画像で固定列化された分が
  html5でマークアップに現れた。原本style.cssは`th:nth-of-type(5)`の`box-shadow`（固定列右端の影）を
  移動していないため、ja_pj側もそのまま（影は権限列の右に出たまま）。
- **変更ファイル**：`templates/permissions/authority_list.html`（th/tdにクラス付与）、
  `static/css/style.css`（`.col-6`/`.col-td-6`定義追加、`.col-5`/`.col-td-5`の誤ったコメントを整理）、
  `static/js/common.js`（`fixAuthorityStickyOffsets`のループを`i <= 5`→`i <= 6`に拡張、下記）。
- **`fixAuthorityStickyOffsets`の拡張が必須**：この一覧の固定列left値は`common.js`が実描画幅から
  都度再計算している（`.col-1〜.col-5`のCSS固定値は原本モックの固定文言前提で実データとズレるため）。
  当初この関数のループが`i <= 5`のままだったため、追加した「操作」列（col-6）はCSSの`left: 382px`が
  そのまま効き、実データの1〜5列合計幅（約282px）と約100pxズレて「操作」列が権限付与（文書管理）の
  列に重なった（ユーザー報告で発覚）。ループを`i <= 6`にして解消。実プレビューで既定表示・横スクロール時
  とも col-5→操作→権限付与 がフラッシュに並ぶことを確認（seam ±1〜2px、opaque背景＋z-indexで被覆）。
- **テスト**：`permissions.tests.AuthorityListOperationColumnStickyTests`を新規追加（th/tdのクラス付与、
  style.cssの`left: 382px`定義、common.jsのループが`i <= 6`まで回ることをセットで検証。
  いずれか欠けると固定が効かない/列が重なるため全部まとめて確認）。関連3クラスとも PASS。

### B. 保管画面（登録）：「削除」ボタンの div を [4]メモ欄ボックスの外へ移動
- **差分**：html4では赤い「削除」ボタンの`<div style="text-align:right;margin-top:10px">`が`[4]メモ欄`の
  `<div class="form-section">`の内側にあったが、html5でその外（スクロール領域の末尾、`storage-outer-actions`
  の手前）へ移動。Rev1.4で追加された説明画像`image69.png`（文書）/`image70.png`（契約書）がこの配置を
  示している。ボタンのクラス・`id`・挙動（`btn-remove-upload`＝アップロード取り消し、
  2026-08-27確定分）は不変。
- **変更ファイル**：`templates/documents/storage2.html`・`templates/contracts/storage2.html`
  （`form-section`の閉じ`</div>`をボタン`div`の前へ移動しただけ。関連コメントもインデント調整）。
  `feedback_repeated_ui_notes_verification`の観点で文書・契約書の両テンプレートを個別に確認・修正。
  移動ついでに当該箇所の`{# … #}`が1行内で閉じているか（CLAUDE.md「Djangoテンプレートの複数行コメントの罠」）も確認済み。
- **テスト**：`documents.tests.UploadStep2RemoveViewTests` / `contracts.tests.UploadStep2RemoveViewTests`に
  `test_remove_button_div_is_outside_memo_form_section`を追加（`form.memo`はTextarea単体でdivを含まないため、
  「メモ欄見出し～削除ボタン」の間に`</div>`が出ること＝form-section外にあることで判定）。両クラス11件PASS。

### C. common.js `openPopupPopup`：ポップアップの縦位置反転を移植
- **差分**：原本 html5 で `openPopupPopup` が (1)先頭で `renderPopupPopupItems()` を呼んで中身の実寸を
  確定してから配置、(2)`rect.bottom + 5 + popRect.height > windowHeight`（下に置くと画面下端で切れる）なら
  ポップアップをボタンの**上**（`rect.top - popRect.height - 5`）へ反転、上にも入らなければ `scrollY + 10`、
  (3)右端はみ出しは再測してから補正、(4)`activePopupTargetInput = btn.previousElementSibling || btn.nextElementSibling`、
  に変更された。Rev1.3で権限管理編集の表示欄が rows=5 textarea になりポップアップが縦に伸びたことへの追随。
- **ja_pj への移植**：ja_pj は選択肢を非同期 `fetch` する場合があり、原本のように「先頭で render→即実寸測定」が
  できない。配置ロジックを `positionPopupPopup(btn)` に切り出し、キャッシュヒット側・fetch解決側の
  **両方で `renderPopupPopupItems()` の直後に呼ぶ**構成にした。縦反転・右端再測の式は原本 html5 と同一。
  `|| btn.nextElementSibling` は ja_pj のウィジェット構造（表示要素→hidden input→ボタン順）では発火しないが、
  原本との差異を残さないため移植（コメントで明記）。
- **変更ファイル**：`static/js/common.js`（`openPopupPopup` 改修、`positionPopupPopup` 追加）。
- **テスト**：本プロジェクトに JS 単体テストの仕組みは無い（クライアント JS は実プレビュー確認方針、
  過去の `startBulkEdit()` 等と同じ）。`core.tests.PopupSelectPositioningJsTests` を回帰ガードとして追加
  （静的ファイルを読み、`positionPopupPopup` 定義・縦反転式・両キャッシュ経路での呼び出し・`|| nextElementSibling`
  を検証）。2件PASS。実挙動は dev サーバーで確認（下記「検証」）。

### D. メイン画面お知らせ：ラッパを `.notice-columns` クラスに統一
- **差分**：原本 html5 で文書列／契約書列のラッパが `<div class="notice-columns">`（＋ `notice-columns > div > ul`
  構造）になり、style.css に `.notice-columns { display:flex; justify-content:space-between; gap:20px }`
  `.notice-columns > div { flex:1 }`、`.notice-area ul` に `margin:0` が追加された。お知らせを文書・契約書の
  2列にすること自体は Rev1.2 で反映済みで、html5 は**モックの見た目定義がマークアップに現れた**もの。
- **ja_pj の従来実装**：ラッパは `<div style="display:flex; gap:40px; flex-wrap:wrap;">`＋`<ul style="flex:1; min-width:280px;">`
  のインライン style だった。html5 に合わせクラス＋CSS へ寄せ、`<ul>` を `<div>` で1段包む構造に変更。
  件数集計と遷移先を一致させるため、**契約書側リンクは html5 の死んだリンク（`onclick="return false;"`）に
  合わせず実際の検索画面へ配線したまま**（2026-08-13 の不一致対応と同じ方針、テンプレートのコメントに明記）。
- **変更ファイル**：`templates/core/menu.html`（ラッパ構造）、`static/css/style.css`（`.notice-columns` 定義追加、
  `.notice-area ul` に `margin:0`）。
- **テスト**：`core.tests.MenuNoticeTwoColumnLayoutTests` に `test_notice_columns_wrapper_matches_html5` を追加
  （`<div class="notice-columns">` の存在、旧インライン flex style が消えたこと、style.css の定義をセットで検証）。
  既存の `test_notice_area_contains_two_ul_blocks`（`<ul` が2個）もそのままPASS。4件PASS。

### E. 権限管理編集の表示欄 textarea を `rows="5"` に
- **差分**：Rev1.3 で input→textarea 化した権限管理編集の3表示欄について、原本 index.html html5（Rev1.4時点の
  マークアップ）では `rows="5"`。ja_pj は `core/widgets.py` の `PopupSelectWidget`（`display_multiline=True`）で
  `rows="4"` を出していた。`rows="4"`→`"5"` の1箇所修正。
- **影響範囲**：`rows` リテラルは `if self.display_multiline:` ブロック内にあり、`display_multiline=True` は
  `permissions/forms.py` の `AuthorityEditForm` 3フィールドのみが指定（全数確認）。検索画面・保管画面2の
  `PopupSelectWidget` は `else` の `<input type="text">` 分岐のため**影響なし**。
- **変更ファイル**：`core/widgets.py`（`rows="4"`→`"5"`、コメントを html5/Rev1.4基準に更新）。
- **テスト**：`core.tests.PopupSelectWidgetTamperResistanceTests.test_display_multiline_renders_readonly_textarea_with_value_as_content`
  と `permissions.tests.AuthorityEditFormTests.test_multi_select_display_fields_render_as_textarea` に
  `rows="5"` のアサーションを追加。PASS。

### 検証
- `manage.py test`（全件）exit 0。`manage.py test permissions core documents contracts` = 475件 OK。
  `manage.py check` 問題なし。
- dev サーバー（`django-dev`、employee_no=9005 でログイン）で computed style / DOM 実測により確認：
  - A：権限管理一覧の「操作」th/td＝`position:sticky`（class `sticky-col col-6` / `sticky-col-td col-td-6`）、
    `common.js`が実測でleftを補正し、既定表示・横スクロール時とも col-5(R292)→操作(L293/R350)→
    権限付与(L348) がフラッシュに並ぶ（当初ループ`i<=5`のままで約100px重なっていたのを`i<=6`で解消）。
    編集ボタン背景＝`rgb(255,204,255)`。
  - C：権限管理編集で画面下部の「選択」ボタン押下 → viewport 460px では popup(高さ221px)が
    ボタンの**上**へ反転（popBottom 326 ≤ btnTop 331）、viewport 720px では従来どおり**下**に展開
    （popTop 363 ≥ btnBottom 358）。非同期 fetch 経路でも 3 件描画後に配置。コンソールエラーなし。
  - D：メイン画面お知らせ `.notice-columns`＝`display:flex; justify-content:space-between; gap:20px`、
    子 div 2つが `flex-grow:1`・各 604px・それぞれ `<ul>` 1本。
  - E：権限管理編集の3表示欄すべて `<textarea rows="5">`。
  - B：`documents/contracts.tests.UploadStep2RemoveViewTests` で step2 GET 後のマークアップ順
    （[4]メモ欄見出し → `</div>`（form-section 閉じ）→ 削除ボタン）を検証。

## 一括編集を「更新ボタンで全ページ一括確定」モデルへ改修（2026-08-28、ユーザー確定）

### 背景
前節（保管画面2の削除ボタン再定義）に続き、一括編集の挙動をユーザーが確定した。従来の一括編集は
**save-as-you-go**（ページャー ＜ ＞ で移動する都度、表示中の1件を即DB保存＋監査ログ）だった。
これは原本html4のモックJS（全件をブラウザ内配列に溜めて最後に一括保存）を、`ModelChoiceField`の
セッションJSON直列化を避けるため簡略化した実装（2026-08-20〜27の経緯は「検索結果一覧 一括編集の
実装」「〜原本html4との挙動差異の修正」各節）。ユーザーの想定は「更新で全ページ一括確定」で、
save-as-you-go は複数点で食い違っていた（訪問しただけのページが無変更でもUPDATE＋監査ログ／
保存満了日が素通りで再計算／削除が即時・取消不可）。

### 確定した仕様
- 一括編集の「更新」= **全ページ一括確定**。それまで一切DB未反映。
- **変更が無いページは更新しない**（「更新なし」）。判定は**更新押下時点のDB現在値との比較**
  （dirty check）。
- 完了ポップアップは**全件**を「更新／更新なし／削除」の3状態＋件数サマリで表示。
- 「削除」ボタンは**削除予定マーク**（即削除しない）。押すとボタンが「削除取消」に変わり、
  マーク中のページは入力欄を**disabled（グレーアウト）＋バナー表示**。「更新」でまとめて論理削除。
- 契約書の**関連書類の追加・削除も「更新」までステージ**（追加ファイルは`MEDIA_ROOT/tmp_uploads/`へ
  退避）。「キャンセル」で入力・削除マーク・関連書類すべて破棄（一時ファイルも実体削除）。
- 入力エラーが1ページでもあれば**全体を止め、最初のエラーページへジャンプ**して表示（未コミット）。
- **単独編集画面**（`DocumentEditView`/`ContractEditView`の削除＝`EditDeleteView`、即時論理削除→
  検索画面へ）と**登録画面**（`UploadStep2RemoveView`、表示中ファイルの即時アップロード取り消し）は
  **前節のまま据え置き**。

### 設計
- **セッション構造**（`core/bulk_edit_services.py`）を
  `{"pks", "index", "staged": {"<pk>": {生値dict}}, "to_delete": [pk], "staged_related": {"<pk>":
  {"add": [{temp_name, original_name}], "remove": [id]}}}` に拡張（全てJSON直列化可能）。
  新ヘルパー: `stage_page` / `staged_page_data` / `toggle_delete_mark` / `is_marked_for_delete` /
  `stage_related` / `staged_related_for` / `discard_staged_related_files` / `discard_bulk_edit`。
  前節で追加した `remove_bulk_edit_pk` は未使用化のため削除。
- **`BulkEditView`**（documents/contracts）を作り替え。GETは `staged` があれば bound フォームで
  ステージ値を表示、`marked_delete` なら全フィールド `disabled`。POSTは送信ボタンで分岐
  （`bulk_nav=prev/next`＝現ページをステージして移動／`bulk_action=toggle_delete`／
  `bulk_action=update`＝`_commit()`／`bulk_action=cancel`＝`discard_bulk_edit`）。
  `_commit()` は 検証パス（NGなら最初のエラーページへ）→ `transaction.atomic()` で
  to_delete は論理削除、staged は dirty のみ `apply_document_edit`/`apply_contract_edit`、
  それ以外は「更新なし」→ 一時ファイル整理 → 完了モーダル（`complete.mode="bulk"`,
  `rows=[{obj,status}]`, `counts`）。
- **dirty判定**: `documents.services.document_edit_is_dirty` / `contracts.services.contract_edit_is_dirty`
  （`apply_*_edit` と同じ department 正規化後に全コピー対象フィールドを比較。契約書は
  `related_changed` も条件。`expiry_date` は派生値のため比較対象外
  ※2026-08-28のレビュー指摘C-1対応で「保存期間変更時のみ引き直す」に整理。下記
  「documents/contractsコードレビューの反映」節参照）。
- **関連書類のステージ退避**: `core.upload_services.stash_files_to_tmp`（`save_pending_files` の
  書き込みロジック流用、セッション非依存で `[{temp_name, original_name}]` を返す）。確定時は
  `open_pending_file()` で開き直し `.name` を元ファイル名に戻して `apply_contract_edit` の
  `new_related_files` へ渡す。
- **テンプレート**: 共有 `edit.html` を `{% if bulk %}` で拡張（削除ボタン＝`toggle_delete` submit、
  「削除取消」トグル、`marked_delete` バナー、キャンセル/戻る＝`bulk_action=cancel` submit、
  契約書の関連書類は view が渡す `related_rows` をループ〈既存−staged remove ＋ staged add
  「追加予定」〉）。単独編集の外部 `record-delete-form` は `{% if can_delete and not bulk %}` に。
  `_complete_modal.html` に `complete.mode == "bulk"` 分岐（状態列＋件数サマリ）を追加。

### 変更ファイル
- `core/bulk_edit_services.py`（構造拡張・ヘルパー群・`remove_bulk_edit_pk`削除）
- `core/upload_services.py`（`stash_files_to_tmp`）
- `documents/services.py`・`contracts/services.py`（`*_edit_is_dirty`）
- `documents/views.py`・`contracts/views.py`（`BulkEditView` 作り替え、`EditDeleteView` を
  単独編集専用に簡素化＝`from_bulk`分岐撤去、`*_BULK_FORM_FIELDS` 定数）
- `templates/{documents,contracts}/edit.html`・`templates/{documents,contracts}/_complete_modal.html`
- `documents/tests.py`・`contracts/tests.py`（`BulkEditViewTests` 作り替え、`EditDeleteViewTests` の
  bulk 系テスト撤去）、`core/tests.py`（`RemoveBulkEditPkTests`→`BulkEditServicesStagingTests`）

### 検証
- `manage.py check` 問題なし。`manage.py test` **706件PASS**。
- dev サーバーで手動確認：5件一括編集→2件だけ編集して「更新」→完了モーダルに5件（更新×2・
  更新なし×3）、DBも編集2件のみ変更・監査ログ2件／削除マーク→「削除取消」で復帰→再マーク→
  「更新」で論理削除／編集して「キャンセル」→検索一覧が元のまま／必須項目を空にして「更新」→
  該当ページへジャンプしエラー表示／契約書：関連書類を追加→「キャンセル」で未反映。

## documents/contractsコードレビューの反映（2026-08-28）

`review_code_documents_contracts.txt`（`/code-review high`、対象：documents/・contracts/の
models/views/api/services/forms/storage_paths/urls＋両アプリが委譲しているcore側共通実装）の
指摘のうち、ユーザー指示（「優先度『高』『中』の指摘を1件ずつ順番に修正。`python manage.py
test documents contracts`で確認してから次へ。低優先度は修正せず理由付きで記録だけ残す」）に
基づき対応した。高＝0件。中＝C-1/C-2/C-3の3件、加えてC-4（低〜中、ユーザー判断で「修正する」）。

### C-1（中）保存満了日(expiry_date)の編集時再計算が三者三様
- **確定した仕様（ユーザー選択）**：「保存期間(retention_period)を変更した時だけ」今日基準で
  引き直す。文書の単体編集・一括編集・契約書の3経路で挙動を統一。
- `documents/services.py apply_document_edit`：無条件だった
  `doc.expiry_date = calculate_expiry_date(今日, retention_period)` を
  `retention_changed`（代入前の`doc.retention_period_id`と`cleaned_data`のpk比較）が真のときのみに
  変更。`doc_retention_edit`権限が無い職員はフォーム側で保存期間欄が実質固定されるため、
  他項目だけ編集しても満了日は動かなくなった。
- `document_edit_is_dirty` のdocstring修正：旧「保存期間が変わらない限り実質不変」は今日基準の
  派生値としては誤りだったが、新挙動では実際に「retention_period変更時のみ変化」する値になり、
  既存の`retention_period_id`比較でカバーされるため`expiry_date`自体を比較対象に含める必要が
  無い旨に書き換え。
- `contracts/services.py apply_contract_edit`：もともと`expiry_date`を触らない（契約書は保存期間が
  `settings.CONTRACT_RETENTION_YEARS`固定で編集要素が無い）。これがC-1の統一方針と一致することを
  docstringに明記。
- `templates/documents/edit.html`：保存期間欄の横に出る「（有効期限：…）」プレビューJSが常に
  今日+保存期間を表示していたため、保存期間が現在値のままなら保存済みの`expiry_date`をそのまま
  表示するよう変更（`#expiry-edit-config`のdata属性で現在の`retention_period_id`・`expiry_date`を
  渡す）。保存後の実値と表示が食い違わない。
- **見送り**：`document_edit_is_dirty`への`expiry_date`直接比較の追加は、上記のとおり
  `retention_period_id`比較で等価にカバーされるため不要と判断。

### C-2（中）契約書編集で関連書類(RelatedFile)保存が途中失敗すると物理ファイルが孤児化
- `contracts/services.py apply_contract_edit`：`RelatedFile.objects.create()`ループを
  `try/except (OSError, DBError)`で囲み、例外時は`created_related`に積んだ（＝save成功済みの）
  ファイル実体を`file.delete(save=False)`してから再raise。`transaction.atomic()`はDB行を
  ロールバックするがストレージ実体は戻さないため。`contracts/views.py`の「登録」経路
  （`UploadStep2View`）が既に持つ後始末と同型に揃えた。単体編集(`ContractEditView`)・
  一括編集(`BulkEditView._commit`)の両方に効く。
- `contracts/services.py`冒頭に`from django.db import Error as DBError`を追加。
- テスト追加：`contracts/tests.py ContractEditViewFileHandlingTests.
  test_related_file_partial_failure_cleans_up_orphan_files`（関連書類2件中2件目のcreateが
  OSErrorで失敗→1件目のファイル実体が`default_storage`から消えていること・本体タイトルも
  ロールバックされること）。

### C-3（中）一括ダウンロードのZIP構築がFileNotFoundErrorしか捕捉せず他のOSErrorで全滅
- `core/zip_services.py build_zip_archive`：`except FileNotFoundError` を `except OSError` に拡大
  （`PermissionError`・`IsADirectoryError`・ストレージI/Oエラー等も1件ずつ`missing_count`計上して
  継続）。単体ダウンロード`core/record_views.py BaseFileServeView`が既にOSError全般をHttp404へ
  変換しているのと整合。
- `core/record_views.py`：利用者向けmessages.warningの文言を「見つからなかった」→
  「取得できなかった」に微修正（欠損以外も含むため）。既存テストの文言アサーション2件
  （documents/contracts）も追随修正。
- テスト追加：`documents/tests.py BulkDownloadViewTests.
  test_non_filenotfound_oserror_is_skipped_not_500`（PermissionErrorでも500にならず該当1件のみ
  スキップ）。

### C-4（低〜中、ユーザー判断で修正）ZIP内ファイル名がUUID接頭辞付き内部名
- `core/zip_services.py`：ZIPエントリ名を`obj.file.name`の末尾（UUID付き）→`obj.display_name`
  （元名）に変更。単体ダウンロードのContent-Dispositionと揃えた。
- `display_name`は文書間で重複し得るため`_dedupe_entry_name()`ヘルパーを追加し、衝突時は
  拡張子の手前に" (2)", " (3)"…を付与（OSのファイルマネージャ慣習）。
- テスト追加：`documents/tests.py BulkDownloadViewTests.
  test_zip_entry_names_use_display_name_and_dedupe_collisions`（同名`dup.txt`2件→
  `["dup (2).txt", "dup.txt"]`）。

### 見送った低優先度（C-5〜C-9・R-1〜R-7の12件）
`review_pending.txt`「■ documents / contracts（追補：review_code_documents_contracts.txt、
2026-08-28）」に項番45〜56として理由付きで記録。要点：C-5（契約金額0円のfalsy-zero空表示）、
C-6（一括編集_commitの対象再取得にis_deleted/部署スコープ条件無し・TOCTOU）、
C-7（`_render_complete`の`rows[0]`無条件参照）、C-8（チャンク結合APIのtotal_chunks上限無し）、
C-9（複数ファイル一括登録でDB INSERT失敗ファイルの孤児化）、R-1（EditViewのUpdateView不使用）、
R-2（`combine_upload_chunks`のセッションリストin-place変更）、R-3（DetailAPIViewの部署スコープ
判定インライン重複）、R-4（一括DLのqueryset2回評価＋ZIP全量メモリ保持）、
R-5（`_post_delete_redirect` docstring乖離）、R-6（documents/services.pyにモジュールlogger無し）、
R-7（論理削除のたびに正規化カラム再計算）。

### 検証
中優先度3件＋C-4を1件ずつ修正し、都度 `manage.py test documents contracts` を実行
（287→288→290件、いずれも全件PASS）。最終 `manage.py test documents contracts` は
**290件PASS**（開始時287件から新規テスト3件純増）。


## セキュリティレビュー（review_security.txt）優先度「高」「中」の反映（2026-08-28）

`review_security.txt`（リポジトリ全体のセキュリティ精査）の指摘のうち、ユーザー指示で
優先度「高」3件・「中」2件を1件ずつ順番に修正した。低優先度（L-1〜L-3）は修正せず
`review_security.txt`冒頭「対応結果」節に理由付きで記録。詳細な指摘内容は同ファイル参照。

### H-1（高）格納型XSS：検索結果詳細ポップアップ renderDetailPopup の innerHTML 直組み立て
- `static/js/common.js`：`escapeHtml()` ヘルパーを新設（getCsrfToken の直後）。
  `renderDetailPopup()` のプロパティ表（`rows.map(...)`）は各値を `escapeHtml(value)` してから
  `<td>` に埋め込むよう変更。関連書類一覧（複数ファイル名を `<br>` 連結する行）は
  `{html: ...}` 形式で「整形済みHTML（各ファイル名は生成時に escapeHtml 済み）」であることを
  マークし、その行だけ二重エスケープしないようにした。
- 検証：ブラウザ実機（dev サーバー＋ログイン）で `renderDetailPopup()` に
  `<img src=x onerror=...>` を含む API 応答を流し、`window.__xss` が立たず `&lt;img` として
  エスケープ表示されること、関連書類行では `<br>` 区切りが維持されることを確認。JS 単体
  テストハーネスはリポジトリに無いため（package.json 不在）、検証はブラウザ実機で実施。

### H-2（高）格納型XSS：検索結果行クリックプレビュー showSearchPreview の innerHTML
- `static/js/common.js`：`showSearchPreview()` の3か所の `titleEl.innerHTML = \`<strong>${title}\`...`
  代入を廃止。`setSearchPreviewMessage(titleEl, title, message)` を新設し、タイトルを
  `<strong>` の `textContent` として、説明文を静的テキストノードとして DOM API で組み立てる。
  `|escapejs` は「JS文字列リテラルとして安全」なだけで innerHTML では `<` が復元される点への対応。
- 検証：ブラウザ実機で `showSearchPreview('<img src=x onerror=...>', '', ...)` を呼び、
  ペイロードが発火せず `<strong>` の textContent としてエスケープ表示されることを確認。

### H-3（高）アップロードファイルのMIME/拡張子未検証＋プレビューの同一オリジン inline 配信
2層で対応:
- **配信側**（`core/file_serving.py` 新設）：`SAFE_INLINE_EXTENSIONS`（PDF＋ラスター画像）以外は
  `PreviewView`/`PendingPreviewView`（本来 inline 意図）でも `as_attachment=True` へフォール
  バックする `resolve_as_attachment()`、および全配信レスポンスに
  `X-Content-Type-Options: nosniff` と `Content-Security-Policy: script-src 'none'; object-src 'none'`
  を付与する `apply_file_response_security_headers()` を用意。`core/record_views.py
  BaseFileServeView.get`・`core/upload_views.py BasePendingPreviewView.get` に適用。
  検索プレビュー機能は元々 `get_preview_kind` が image/pdf しか返さないため、フォールバックに
  よる画面上の機能低下は無い。`Content-Security-Policy: sandbox` や `default-src 'none'` は
  ブラウザ内蔵 PDF ビューアの表示に影響しうるため、あえて `script-src`/`object-src` のみに絞った。
- **アップロード側**（`core/upload_validation.py` 新設）：`BLOCKED_UPLOAD_EXTENSIONS`
  （html/htm/xhtml/shtml/mht/svg/svgz/js/mjs/htc/hta/swf）を拒否リスト方式で判定する
  `blocked_upload_message()`。`core/upload_views.py BaseUploadStep1View.post`（通常アップロード、
  documents/contracts 共通）と `BaseChunkUploadAPIView.post`（分割アップロード、`file_name` を検証）で
  拒否。Office 文書・PDF・画像・テキスト・圧縮ファイル等の通常業務形式には一切影響しない。
- **原本フィデリティ**：原本 HTML/xlsx はファイル種別を制限していないが、ユーザー依頼の
  セキュリティ修正に伴う意図的逸脱。`accounts/forms.py StaffCsvImportForm.clean_csv_file` が
  既に .csv を検証しているのと同じ考え方。
- **見送り**（H-3 推奨対応のうち中期対応）：アプリ全体への CSP 導入（テンプレートが原本由来の
  `onclick` 等インラインハンドラに全面依存しており段階的移行が必要）、MEDIA の別オリジン配信。
  `review_security.txt`「未対応」節に記録。
- テスト追加：`core/tests.py SafeInlineFileServingTests`（5）・`BlockedUploadValidationTests`（3）、
  `documents/tests.py PreviewViewTests.test_preview_adds_security_headers` /
  `test_html_file_is_never_served_inline_via_preview`、`UploadBlockedFileTypeTests`（2）。
  ブラウザ実機で PDF のインラインプレビュー（iframe）が CSP 付与後も維持されることを確認。

### M-1（中）一括編集のステージング型削除が can_delete() をサーバー側で検証しない
コミット 9358b6d の一括編集ステージング型改修で新規混入したリグレッション。
`toggle_delete` ハンドラと `_commit` の確定前検証は `deletion_services.can_delete()` を
呼んでおらず、`{% if can_delete %}` のクライアント側ゲートしか無かった。
- `documents/views.py`/`contracts/views.py BulkEditView`：
  - `toggle_delete` ハンドラ：削除マークを「付ける」操作のみ `can_delete()` を検証し、
    NG なら `deletion_denial_message` を出して `redirect`（マーク解除は常に許可）。
  - `_commit`：入力エラー検証パスの直後に「削除予定pkの `can_delete()` 検証パス」を追加。
    1件でも NG なら `set_bulk_edit_index` で該当ページへ飛ばし、削除マーク済み（disabled）
    フォームでエラー付き再描画してコミット全体を中断（既存の入力エラー時の扱いと同型）。
  部署スコープは既存の `scoped_get_object_or_404` ＋ `resolve_ordered_pks` で強制済みのため、
  欠落していた「削除済み／登録から7日以上経過」ルールのみを補った。
- テスト追加：`documents/tests.py BulkEditViewTests` /
  `contracts/tests.py BulkEditViewTests` に各2件
  （`test_toggle_delete_mark_rejected_for_*_past_delete_window`、
  `test_commit_rejects_smuggled_delete_mark_for_*_past_delete_window`。後者は
  `to_delete` をセッションへ直接注入して改ざん・API直叩きを模す）。

### M-2（中）SECRET_KEY に本番でも有効な安全でないハードコードデフォルト
- `config/settings/prod.py`：`SECRET_KEY = env("SECRET_KEY")`（デフォルト無し）を追加。
  `base.py` の `default="django-insecure-dev-key-change-me"` は dev 用に残し、prod では
  未設定なら django-environ が `ImproperlyConfigured` を送出して起動失敗させる。
- `.env.example`：`SECRET_KEY=change-me` → `<REQUIRED-generate-a-unique-50-char-random-key>` ＋
  生成コマンド例のコメントに変更。
- 検証：`.env` から SECRET_KEY を一時的に除いたサブプロセスで
  `DJANGO_SETTINGS_MODULE=config.settings.prod` を setup し、
  `ImproperlyConfigured: Set the SECRET_KEY environment variable` で停止することを確認
  （設定時は正常ロード）。

### 検証（全体）
高3件・中2件を1件ずつ修正し、都度関連テストを実行。最終 `manage.py test`（全アプリ）は
**752件PASS**（本修正で新規テスト14件純増）。


## チャンク分割アップロードのチャンクサイズを settings 化（2026-08-28）

ユーザーから「500MB等の大容量文書を5MBずつ分割アップロードしているが、このサイズで
妥当か」という問い合わせ。評価結果は「5MBは安全側で、そのままでも問題なし。大容量主体で
往復回数を減らしたいなら10MB程度まで可。5MB未満にはしない。上限は必ず
`MAX_UPLOAD_SIZE_BYTES`（1リクエストボディ上限）より十分小さく、かつ本番リバースプロキシの
ボディサイズ上限がこの値＋αを許可していること」。あわせてユーザー指示で、JSハードコードを
やめて settings 化した（過去に「テスト用1MBのまま戻し忘れ」事故があった箇所。同ファイル
「チャンク分割アップロードのチャンクサイズ食い違いを修正」節参照）。

- [x] `config/settings/base.py`：`CHUNK_UPLOAD_CHUNK_SIZE_BYTES`（`env.int`、既定 5 * 1024 * 1024）
  追加。推奨サイズ・下限/上限の制約・リバースプロキシ依存をコメントで明記。
- [x] `.env.example`：`CHUNK_UPLOAD_CHUNK_SIZE_BYTES` をコメントアウトで追記（推奨値の注記付き）。
- [x] `core/upload_views.py` `BaseUploadStep1View._context()`：`chunk_upload_chunk_size_bytes` を
  テンプレートコンテキストへ追加（documents/contracts 共通）。
- [x] `templates/{documents,contracts}/storage1.html`：`uploadFilesInChunks()` の第3引数へ
  `{{ chunk_upload_chunk_size_bytes }}` を渡す。
- [x] `static/js/chunk_upload.js`：`const CHUNK_UPLOAD_CHUNK_SIZE`（ハードコード）を廃止し、
  `uploadFilesInChunks(files, uploadUrl, chunkSize)` の引数で受け取る方式に変更。引数未指定・
  不正値（0以下・NaN）用に `CHUNK_UPLOAD_CHUNK_SIZE_FALLBACK`（5MB）を残す。推奨サイズを
  ファイル冒頭コメントに記載。サーバー側（`combine_upload_chunks`）はチャンクサイズを参照
  していないため変更不要。
- [x] テスト追加：`documents/tests.py ChunkUploadAPITests.
  test_step1_passes_configured_chunk_size_to_template`（settings 上書きが保管画面１の
  レンダリング結果に反映されること）。

### 検証
`manage.py test documents contracts` **332件PASS**（新規1件純増）。

## 保管画面２／編集画面のフィールドエラー表示位置を入力欄の下へ（2026-08-31）

ユーザー報告：保管画面２で分類・カテゴリーを空欄のまま「登録」すると
「このフィールドは必須です。」（Django必須エラーの日本語ロケール訳）が出るが、
`.form-row`（`display:flex; align-items:center;`）の中に素の `<div style="color:#c0392b;">`
で描画していたため、エラーが入力欄・「選択」ボタンの**右隣に横並び**で表示されていた。
入力欄の真下に出す方が自然、という指摘。原本モックはDjangoのエラー`<div>`を描画しないため
原本フィデリティ上の制約は無い。

- [x] `static/css/django_widgets.css`：`.form-row:has(.field-error) { flex-wrap: wrap; }` ＋
  `.form-row .field-error { flex-basis:100%; margin-left:100px; margin-top:2px;
  color:#c0392b; font-size:12px; }` を追加。`margin-left` は `.form-row label` の
  `width:100px` に合わせ、折り返したエラーを入力欄の左端に揃える。`.form-row` を使う
  テンプレートは保管／編集の4画面のみ（`grep` で確認済み）。
  ※当初は `.form-row { flex-wrap: wrap }`（全行）だったが、契約書 storage2 の
  「契約期間 [from]～[to]」行が折り返す副作用があり `:has(.field-error)` で
  エラー行のみに限定した（同日、下記「追補」参照）。
- [x] `templates/{documents,contracts}/storage2.html`：部署／分類／カテゴリー／文書タイトルの
  エラー `<div>` を `style="color:#c0392b;"` から `class="field-error"` へ。
- [x] `templates/{documents,contracts}/edit.html`：文書／契約書タイトルのエラー `<div>` も同様に
  変更（同じ `.form-row` 構造で同じ横並び不具合があるため）。edit.html は部署／分類／
  カテゴリーのエラー自体を描画していない（別件・今回はスコープ外）。

### 検証
実プレビューで管理者ログイン → `/documents/upload/step1/` にダミーPDFをPOST →
`/documents/upload/step2/` で空submit。分類・カテゴリー両方のエラーが
`getBoundingClientRect()` 実測で入力欄の直下（`err.y >= input.bottom`）かつ
左端一致（`err.x == input.x`）に表示されることを確認。

## 保管画面２：複数件登録のメタデータをファイルごとの個別入力へ（2026-08-31、ユーザー依頼）

ユーザー依頼：保管画面２（新規保管）で複数ファイルを一括選択したとき、メタデータ
（部署・分類・年・カテゴリー・保存期間・個人情報・メモ／契約書は契約日等）を「1回の入力で
バッチ全件へ共通適用」ではなく、**ページャーで表示中のファイルごとに個別入力**する。
未入力ファイルの初期値は「空欄・既定値スタート」（部署＝ログインユーザーの部署、個人情報＝
「含まれる」、年＝当年。直前ファイルからのコピーはしない）。

原本HTML確定版のJS（`startRegisterMock()`）はタイトル以外をバッチ共通適用しており、これは
**原本との意図的な差異**（ユーザー明示依頼のため原本一致よりユーザー指示を優先。CLAUDE.md
「原本フィデリティに関する運用方針」）。編集画面（`edit.html`＝単体編集・一括編集、常に
1ファイル）は挙動不変。

### 設計

- ページャーは従来どおり純JS（サーバー往復なし）。createモードではメタデータ欄を
  ファイル数ぶんDOMに展開し、`.doc-fieldset[data-doc-index]` をJSで表示/非表示切替、送信は全件同時。
- `documents/contracts.forms.UploadStep2Form`：`self.per_file_mode = not edit_mode`。createでは
  `PER_FILE_FIELDS`（クラス属性）を `copy.deepcopy` でファイル数ぶん複製して `{name}_{i}` に
  差し替える（1ファイルでも `_0`）。年choices・部署disable/初期値・分類/カテゴリー部署スコープ・
  （documents）保存期間widgetの `id`/`onchange` 添字化を、生成後の添字付きフィールド全てに適用。
  ヘルパー `file_data(i)`（保存する値の辞書、per_file_mode なら `{name}_{i}` を引く）と
  `first_error_file_index()` を追加。編集モードは無添字のまま（`_build_form` は `edit_mode=True`）。
- `core/upload_views.py`：`file_field_sets(form, pending, field_names)` を追加（ファイル単位の
  `{"item", "index", "fields": {...}}` をテンプレートへ）。`file_rows` は据え置き（JSのファイル名一覧用）。
- `documents/contracts.views.UploadStep2View`：保存ループを `form.file_data(i)` ベースへ。
  バリデーションエラー時は `messages.error("N件目に入力エラーがあります。")`（複数件時）＋
  context `active_doc_index = form.first_error_file_index()`。`_expiry_preview_context` は
  `retention_period` または `retention_period_0` の queryset を使うようガード。
- `templates/{documents,contracts}/storage2.html`：静的な [1]〜[4] ブロックを `file_field_sets`
  ループ（`.doc-fieldset`）へ。documents は保存満了日プレビューを `calculateExpiryDate(idx)` に
  引数化（`#storage-period-{idx}` / `#expiry-date-calc-{idx}`、previews マップは共通1個）。
  contracts は関連書類（`related_files_{index}`、以前から一括対応済み）も `.doc-fieldset` 内へ移設し、
  JSの個別切替（`.title-row`/`.related-files-row`）を `.doc-fieldset` 一括切替に統一。
  Djangoの `messages` を表示するブロックを追加（従来は `form.non_field_errors` のみ）。

### テスト

- 既存の単一ファイルPOSTテスト（`UploadStep2ViewValidationTests`、`UploadStep2FormDepartmentInitialTests`、
  `UploadStep2FormGroupCategoryScopeTests`、`UploadFileIOErrorTests`、`UploadStep2ImmediateExtractionTests`、
  `RelatedFilesMultiUploadTests`）のメタデータキーを `department` → `department_0` 等へ更新
  （documents/contracts 両方）。
- 追加（documents `UploadStep2PerFileMetadataTests`、contracts `UploadStep2ViewValidationTests`）：
  2ファイルを別々の分類/カテゴリー/年/保存期間/個人情報/メモで登録 → 各々が自分の値で保存され
  保存満了日もファイルごとに計算されること／2件目だけ分類欠落 → 200・`group_1` エラー・
  `active_doc_index==1`・messages「2件目」・レコード0件／`file_data()`・`first_error_file_index()`。

### 検証

- `manage.py test documents contracts` **336件PASS**（新規4件）。`manage.py test core` 134件PASS。
- 実プレビュー：管理者ログイン → step1へダミーPDF2件POST → step2。`.doc-fieldset` が2個・
  各フィールド名が `*_0`/`*_1`・`storage-period-{i}`/`expiry-date-calc-{i}` が個別・ページャーで
  表示切替。file0=(分類Ａ,一般文書,2025,1年,個人情報あり)、file1=(分類Ｂ,予算関係,2023,10年,なし)で
  登録 → DBで Document 2件が各々の値・別々の `expiry_date` を保持することを確認。
  2件目の分類を空にPOST → `activeDocIndex=1`・「2件目に入力エラーがあります。」・2件目の
  `.doc-fieldset` に `.field-error` 表示を確認。

### 追補（同日、ユーザー報告）

1. 契約書 storage2 の [3]関連書類の複数行 `{# … #}` コメントが画面に生表示されていた
   （CLAUDE.md「技術的な既知の落とし穴」＝複数行 `{# #}` は `.` が改行に不一致でコメントとして
   機能しない、の再発）。`{% comment %}…{% endcomment %}` に修正。
2. 「保管画面２／編集画面のフィールドエラー表示位置」節で `.form-row { flex-wrap: wrap }` を
   全 `.form-row` に付けたところ、契約書 storage2 の「契約期間 [from] ～ [to]」行が折り返して
   縦積みになった。`django_widgets.css` を `.form-row:has(.field-error) { flex-wrap: wrap }` に
   限定し、エラーを含む行だけ折り返す（`:has()` は対象4画面の利用ブラウザで可）。実プレビュー
   （幅1400）で契約期間の from～to が同一行、必須エラーは入力欄直下・左端一致を再確認。

### 追補（2026-08-31、ユーザー要望）：「削除」で他ファイルの入力を保持する

ファイルごと個別入力にしたことで、複数件登録中に「削除」（アップロード取り消し）を押すと
入力済みの全ファイルの内容がクリアされる問題が顕在化。**削除しても残るファイルの入力を保持**
するよう変更。

- 旧：「削除」は専用フォーム `#remove-upload-form`（`upload_step2_remove` URL、
  `BaseUploadStep2RemoveView`）を submit → セッションから1件外し **redirect**（PRG）→
  step2 の GET が空フォームを再描画。
- 新：「削除」は**メインフォームごと** submit（hidden `action=remove` ＋ `remove_index`）。
  `UploadStep2View._handle_remove`（documents/contracts）がセッションから1件外し、
  `core.upload_views.remap_step2_initial_after_remove` で残りファイルのPOST値を削除位置に
  合わせて詰め直し（後ろの `{name}_{i}` を1つ前へ）、**unbound**フォームの `initial` に載せて
  そのまま render（redirectしない＝バリデーションエラーも出さない）。全件外れたら step1 へ redirect。
- `UploadStep2Form.__init__` の部署初期値を `self.initial[...] =` から
  `self.initial.setdefault(...)` に変更（削除後再描画でview側が渡す保持済み部署を優先）。
- `templates/{documents,contracts}/storage2.html`：`#remove-upload-form` を廃止。メインフォームに
  `<input type="hidden" name="action">` `<input type="hidden" name="remove_index">` を追加。
  削除ボタンJSは `mainForm.requestSubmit()`。契約書は送信前に file input を `disabled` にして
  関連書類の無駄な二重アップロードを防ぐ（関連書類はブラウザ仕様で復元不可＝選び直し、と confirm 文言で明示）。
- `BaseUploadStep2RemoveView`・`documents/contracts.views.UploadStep2RemoveView`・
  `upload_step2_remove` URL を**削除**（UIから到達不能かつ redirect で入力を捨てる旧実装のため）。
  関連テスト（`UploadStep2RemoveViewTests`）は新方式（`action=remove` を step2 へ POST、
  200 render・入力保持・詰め直しを検証）に書き換え。

### 検証（追補分）

- `manage.py test documents contracts core` **470件PASS**。
- 実プレビュー：3ファイルに別々のタイトル・メモ・分類・年を入力 → 3件目を「削除」→ 2件が
  値保持（分類は表示ラベルも解決）。続けて1件目を「削除」→ 残り1件が `_0` へ詰め直されて表示。
  最後の1件を「削除」→ step1 へ redirect。通常の「登録」（action 空）は従来どおり動作。

## 保管画面２・詳細・編集画面の右側エリアが原本より狭い問題の修正（2026-08-31、ユーザー指摘）

### 症状

保管画面２・検索結果詳細ポップアップ（`popup-detail`）・編集画面（documents/contracts の
`edit`）で、右側の「情報表示・入力エリア」（`.meta-input-form-wrapper`、原本レイアウトでは
`.storage-layout` の 35%）が原本HTMLより約10px 狭く、左のPDFプレビュー（`.pdf-preview-container`
65%）が約10px 広くなっていた。

### 原因

これらの画面は原本の左右分割レイアウト（`.storage-layout` flex ＝ 左 `.pdf-preview-container`
`width:65%` ＋ 右 `.meta-input-form-wrapper` `width:35%`、`flex-shrink:1`）を共有している。
`.storage-layout` の合計幅では 65%+35%+gap がコンテナをオーバーするため、本来は両列が
flex-basis 比で少しずつ収縮して原本の 757.8 / 408.0px（詳細ポップアップ・幅1360時）に落ち着く。

ところが ja_pj では、ユーザー依頼（2026-08-12）で追加した実プレビューのドラッグスクロール／
ズーム用に、PDF枠の内側へ `.pdf-scroll-area`（`width:1140px; flex-shrink:0`。拡大後の最大
はみ出し幅を先取り確保するラッパー）を挟んでいる。この固定1140px幅が、`overflow:hidden` の
PDF枠を貫通して左列 `.pdf-preview-container`（`overflow:visible`・`min-width:auto`）の
**flex アイテム自動最小サイズ（min-width:auto = min-content）** として染み出し、左列が
`.storage-layout` の収縮時にほとんど縮まなくなっていた（実測：左列が本来より約10px 広いまま
＝収縮ぶんが全部右列に寄る）。原本HTMLには `.pdf-scroll-area` が無いため顕在化しなかった。

### 修正

`static/css/style.css` の `.pdf-preview-container` に **`min-width: 0`** を追加（理由コメント付き）。
flexbox で「コンテンツ幅を下回る収縮」を許可する定石。これで左右が原本どおり flex-basis 比で
収縮し、65/35 に復帰する。`.pdf-view-box{2}` の `overflow:hidden` と `.pdf-scroll-area` の
1140px はそのままなので、ドラッグスクロール／ズーム（`common.js` の `initDragScroll` /
`centerScrollArea` / `zoomPdf`）は影響なし。

### 検証

実プレビュー（Django dev、viewport 1360、`seed_test_data` の職員番号1でログイン）で
`getBoundingClientRect().width` を実測し、同条件の原本HTML（html5、簡易HTTPサーバ）と突き合わせ：

| 画面 | 箇所 | 修正前 | 修正後 | 原本 |
|------|------|--------|--------|------|
| 詳細ポップアップ | 右列 `.meta-input-form-wrapper` | 398.29 | **408.02** | 408.02 |
| 詳細ポップアップ | 左列 `.pdf-preview-container` | 767.51 | **757.78** | 757.78 |
| 詳細ポップアップ | `#detail-properties-view` | 366.69 | **376.43** | 376.43 |
| 編集画面（documents/edit） | 右列 | 446.x | **456.75** | 456.75 |

PDFプレビュー枠は幅848px・スクロール領域1140pxのままでドラッグスクロール可能を確認。

## PDFプレビューを PDF.js 自前描画へ（2026-08-31、ユーザー依頼）

### 経緯

保管画面２・編集画面・検索結果詳細ポップアップの実プレビュー（2026-08-12 追加）で、PDF を
ブラウザ内蔵 PDF ビューアの `<iframe>` に読み込ませていたが、原本の紙モック枠（`.pdf-mock-page`
380px＝実質 iframe 340px）が Chrome 内蔵ビューアの実用最小幅（約 460〜500px）を下回るため、
①ツールバーが右で見切れて水平スクロールバーが出る ②横長 PDF が過大描画で右が欠ける、という
問題があった。`#toolbar=0` 等の URL パラメータは現行 Chrome の `<iframe>` では無効。枠を広げる案・
先頭ページのみ画像化案（複数ページの下スクロールが失われる）・全ページ画像化案（500 ページ級で
非現実的）を検討の上、ユーザーが **PDF.js で各ページを枠幅ぴったりの canvas に自前描画** する
方針（①）を選択。「元に戻せるように」との指示で settings フラグ方式にした。

### 実装

- **`static/vendor/pdfjs/`**：PDF.js 3.11.174 の legacy(UMD) ビルド（`pdf.min.js` /
  `pdf.worker.min.js`、Apache-2.0、`LICENSE`＋取得手順を `README.md` に記載）。CDN 不使用・
  オフライン可。legacy ビルドを選んだのは庁内端末のブラウザ世代が不明なため。
- **`settings.PDF_JS_PREVIEW_ENABLED`**（`config/settings/base.py`、`env.bool`、既定 `True`、
  `.env.example` にも記載）。`False` で従来の `<iframe>` へ完全復帰し、PDF.js アセットも読み込まれ
  なくなる（テンプレート・JS 双方でこの値で分岐）。画像プレビュー（`<img>`）とモック文言は不変。
- **`core/context_processors.preview_settings`**（新規、`TEMPLATES` に登録）：全画面共通の
  base.html 詳細ポップアップへ `pdf_js_preview_enabled` を渡すため。
- **`static/js/pdf-preview.js`**（新規、`window.PdfPreview`）：`render(el,url)` / `clear(el)` /
  `zoom(el,factor)`。最初の `render()` 時のみ `pdf.min.js` を動的 `<script>` で遅延ロード。
  各ページの空プレースホルダ `<div>` を並べ、枠の `scroll` イベント（＋初回・`ResizeObserver`）で
  「表示付近のページだけ」canvas 描画、離れたら canvas 破棄 → 数百ページでも同時描画は数枚。
  `FileResponse` の Range 対応で必要バイトのみ転送。IntersectionObserver はタブ非表示時に
  発火しないため主機構にしない。レイアウトの要（`align-self:stretch` / `width:100%` /
  `overflow` / スクロール）は CSS の読み込み順・キャッシュに依存しないよう inline でも当てる。
- **`static/css/style.css`**：`.pdfjs-preview` / `.pdfjs-page` / `.pdfjs-message`（背景色・影・
  余白などの装飾のみ。幅・高さは JS が実測 px で設定）。
- **`static/js/common.js`**：`zoomPdf()` は枠内に表示中の `.pdfjs-preview` があれば
  `PdfPreview.zoom()` へ委譲（＋/− ボタン共有）。`renderDetailPopup()` / `closeDetailPopup()` に
  PDF.js の表示切替・破棄を追加。
- **テンプレート**：`base.html`（詳細ポップアップに `#detail-pdfjs-preview`、`<iframe>` を
  `{% if not pdf_js_preview_enabled %}` でガード、`window.PDFJS_LIB_URL`/`WORKER_URL`/
  `PDFJS_PREVIEW_ENABLED` を埋め込み `pdf-preview.js` を読み込み）、`{documents,contracts}/edit.html`
  （PDF＋can_download かつフラグ ON なら `.pdfjs-preview[data-pdf-url]` を直接出力、else 従来の
  `.pdf-scroll-area`＞`.pdf-mock-page`）、`{documents,contracts}/storage2.html`（`#pdf-preview-pdfjs`
  枠を追加、`setupActiveDoc()` がページャーのファイル種別で `.pdfjs-preview` / `.pdf-scroll-area`
  を排他表示）。

### 検証

- `manage.py test` **全766件PASS**（`ImagePreviewTests` にフラグ ON/OFF 両方のテストを追加）。
- `collectstatic`（prod, `CompressedManifestStaticFilesStorage`）で pdfjs アセットのハッシュ化・
  gzip 生成がエラー無く完了。
- 実プレビュー（Django dev, viewport 1440, 職員番号1）：
  - 編集画面（縦長 PDF）：枠幅約830pxの canvas、水平スクロールバー無し、ツールバー無し。
  - 保管画面２（横長A4 3ページ）：各ページ 831×587 で枠幅にフィット、右端の欠け無し、
    下スクロールで2・3ページ目も描画、水平スクロールバー無し。
  - 詳細ポップアップ（縦長 PDF）：枠幅約787pxで描画、縦スクロールで全体、水平バー無し。
  - ＋/− ボタン：`PdfPreview.zoom` に委譲。起点は「今表示している枠の中央」（変更前に中央に
    あった文書上の点を縦横の割合で覚え、リサイズ後に同じ点が中央へ来るよう scroll 復元。
    原本 zoomPdf の transform-origin:top center 固定と違い、拡大した箇所を見続けられる）。
    拡大でページが枠より広くなると横スクロール可。
  - 移動操作：縦スクロールバー／マウスホイールに加え、**枠内をマウスドラッグでパン**できる
    （縦＝複数ページ、横＝ズームで枠より広い時。原本 `.pdf-view-box` の initDragScroll と同じ操作感。
    はみ出している軸だけ動く、ネイティブのスクロールバー上のドラッグはブラウザに委ねる、
    カーソルは grab/grabbing）。
  - `PDF_JS_PREVIEW_ENABLED=False`：edit/storage2 とも `<iframe>` に戻り pdfjs アセット未読込を確認。

### 検索・閲覧画面「文書イメージ」欄も PDF.js へ（2026-08-31 追補、ユーザー依頼）

上記の PDF.js 化は保管画面2・編集画面・検索結果詳細ポップアップの3か所のみを対象とし、
**文書／契約書 検索・閲覧画面（screen-search）の「文書イメージ」欄はブラウザ内蔵 PDF ビューアの
`<iframe>`（`#search-preview-frame`）のまま取り残されていた**。ユーザーから「メイン画面お知らせの
件数リンク経由と『検索・閲覧・変更』ボタン経由でプレビューの見え方が違う」と指摘があり調査した
結果、画面・iframe・PDF バイト列・サーバー応答はすべて同一で、差はブラウザ内蔵 PDF ビューアが
ズーム倍率・ツールバー表示をブラウザ側で保持し前回値を引き継ぐことによる（`notice` パラメータや
アプリ側の差ではない）ものと判明。狭い枠でのツールバー見切れ・横長 PDF の右端欠けという当初の
動機がこの欄にもそのまま当てはまるため、他3か所と同じ方式に揃えた。

- **`templates/{documents,contracts}/search.html`**：`.pdf-view-box`（`height:320px`）内に
  `{% if pdf_js_preview_enabled %}<div class="pdfjs-preview" id="search-pdfjs-preview" style="display:none;">`
  を追加。枠に `id="search-pdf-view-box"` を付与（命名を `detail-`/`storage-` に合わせる。現状
  ズームボタンは無いため参照はされないが、他3枠との一貫性のため）。既存の `#search-preview-frame`
  は画像フォールバック用・`PDF_JS_PREVIEW_ENABLED=False` 時の PDF 用に残す。
- **`static/js/common.js` `showSearchPreview()`**：行クリック時、`previewKind === "pdf"` かつ
  `window.PDFJS_PREVIEW_ENABLED` なら `#search-pdfjs-preview` を表示して `window.PdfPreview.render()`。
  画像、または PDF.js 無効時の PDF は従来どおり `<iframe>`。毎回まず `PdfPreview.clear()` で前回
  描画を破棄してから出し直す（`renderDetailPopup()` / `setupActiveDoc()` と同じ構造）。権限不足・
  非対応形式・削除済みの案内文言は不変。
- ズームボタン（`＋`/`−`）は原本の screen-search「文書イメージ」欄に無く、フィデリティ監査済みの
  ため今回も追加しない（edit/detail/storage2 は原本モックにボタンがあるため保持しているのと逆）。
- **`{documents,contracts}/tests.py`**：`SearchPreviewPaneTests`（既定でPDF.js枠を出力／
  `PDF_JS_PREVIEW_ENABLED=False` で非出力＋`#search-preview-frame` 残置）。

検証（Django dev, 職員番号9005, viewport 1280）：

- お知らせ「有効期限切れまで1ヶ月以内」経由（`?notice=expiring_soon`）と「検索・閲覧・変更＞文書」
  経由の両方で、同じ PDF（Book1・pk21）行クリック時に PDF.js が枠幅フィットで描画。ツールバー無し・
  水平スクロールバー無し。両ルートで見え方が一致することを確認。
- 複数ページ PDF（画面イメージ・pk24、6ページ）：全ページ縦積みで描画、下スクロールで各ページ canvas 化。
- 別行へ連続クリック：`clear()`→`render()` で canvas がリークせず入れ替わる（6→6、二重描画無し）。
- コンソールエラー無し。`manage.py test documents contracts` **全342件PASS**。

### 登録・編集フォームの「登録/更新」ボタンが必須エラー後に押せなくなる不具合の修正（2026-09-01、ユーザー報告）

**現象**：職員マスタの登録・編集で、未入力のまま「登録」/「更新」を押す→ブラウザの必須入力
バリデーション（「このフィールドを入力してください」等）でフォーム送信がブロックされる→
その後フィールドを修正してもボタンが `disabled` のままで二度と押せない。

**原因**：全登録・編集・削除フォームの送信ボタンに付いていた二重送信防止のインライン
`onclick="if (!confirm('…')) return false; setTimeout(() => { this.disabled = true; });"` が、
`confirm` OK 後に**フォームが実際に送信されたかに関わらず** `setTimeout` でボタンを無効化して
いた。サーバーへ POST が飛んだ場合はページ遷移するので問題にならないが、HTML5 の
クライアント側必須バリデーションで送信がブロックされた場合はページが遷移せず、無効化だけが
残る。職員マスタは `職員番号`/`氏名`（必須テキスト）・`職階`/`役職`（必須 `<select>`、先頭
`(選択してください)` = 値空）があるため踏みやすい。

**修正**：`onclick` の先頭に `if (!this.form.reportValidity()) return false;` を追加。
フォームが不正なら（ネイティブのバリデーション吹き出しを出したうえで）`return false` して
`confirm` も `setTimeout` も実行しない。正常時のみ従来どおり confirm→送信→ボタン無効化。
`core.double_submit`（トークン方式のサーバー側二重送信対策）は不変で、ボタン無効化は
あくまで UX 補助。

- 対象16ファイル（同一スニペットのため一括置換）：`accounts/staff_regist.html`・
  `accounts/staff_edit.html`・`organizations/dept_regist.html`・`organizations/dept_edit.html`・
  `permissions/authority_edit.html`・`masters/{class,cat,retention}_{regist,edit,delete}.html`・
  `core/other_main_edit.html`・`core/other_logout_edit.html`。`*_delete.html` は検証対象
  フィールドが無く `reportValidity()` は常に true（実質無変更）だが、スニペットを全画面で
  揃えるため同じく適用。

**検証**（Django dev, 職員番号1, viewport 1280）：

- 職員マスタ登録：空フォームで「登録」→ボタンは `disabled` にならず、confirm も出ない
  （不正フォームで無駄な確認ダイアログを出さない副次効果）。必須項目を全部埋めてから
  「登録」→ confirm 1回・`submit` 発火・ボタン `disabled`（二重送信防止は維持）。
- 職員マスタ編集：`氏名` を空にして「更新」→ボタン無効化されず、修正後そのまま押下可能。
- `manage.py check` 問題なし。`manage.py test accounts masters organizations` **211件PASS**。

### 職員マスタ登録・編集：部課が1つだけの本支所で部課が表示・選択できない不具合の修正（2026-09-01、ユーザー報告）

**現象**：職員マスタの登録・編集で、部課が1つしかない本支所（例: 本支所コード 011 / 100 / 101）を
選ぶと、部課プルダウンが無効化されたまま何も表示されず、部課を選べない。

**原因**：`staff_regist.html` / `staff_edit.html` の `updateSections()` が、原本モック
`updateCode()`（「部課区分を持つのは本店(000)のみ」という固定サンプル前提）をそのまま移植して
おり、`if (branchCode && branchCode !== '000')` の場合は無条件で部課selectを無効化していた。
上記「職員マスタの本支所→部課連動プルダウン無効化ロジックを復元」で入れた分岐がまさにこれ。
実データでは本店以外にも実在の部課を持つ本支所があるため、本店決め打ちが誤りだった。

**修正**：判定を「本支所コードが000か」から「その本支所が実在する部課
（`section_code` が空でないレコード）を持つか」に変更。
- 実在部課が1件以上 → 部課selectを有効化し、その部課だけを選択肢に出す（本店に限らない）。
- 実在部課が0件（＝「本支所コード＋空の部課コード」のレコードが1件だけの物流センター等）→
  従来どおり部課selectを無効化し、そのレコードのpkを直接 hidden `department` へ入れる。

`static/js/common.js` の検索パネル側（`staff_list.html` / `dept_list.html` の
`updateSectionOptions()`）は元から `d.section_code` 真偽で絞り込んでおり影響なし。

**検証**（Django dev, 職員番号1, ブラウザ実操作）：

- 登録：本支所 000（3部課）→ 3件表示・有効。011 / 100 / 101（各1部課）→ その1部課が表示・有効
  （従来は無効・空）。900（物流センター, 空部課）→ 無効・プレースホルダのみ・hidden department に
  当該レコードpkが入る。部課を選ぶと部課コード表示欄も追従。
- 編集：本支所 101 / 部課 04「業務4課」の職員 → 初期表示で部課selectに「業務4課」が選択済みで
  表示される（従来は無効・空）。本店へ切替→3部課表示、101へ戻す→「業務4課」表示。
- `manage.py test accounts` 77件PASS。

## 「操作履歴ログ」シートの行単位全数監査（2026-09-03、ユーザー依頼）

### 監査範囲・方法
xlsx「操作履歴ログ」シート（Rev1.4）を openpyxl で全セル抽出し、B6〜B76 の全行＋Rev1.1改訂注記
4箇所（AI8「画面変更」、AI40/AI43「仕様変更」、AI62「表示件数変更」）＋埋め込み画像1枚
（screen-log-list モック、row6 アンカー）を1行ずつ、`audit` アプリおよび各アプリの
`audit_services.log()` / `log_raw()` 呼び出し全箇所（約40リテラル）、テンプレート
`templates/audit/log_list.html`、原本 `index.html:3323-3399` の screen-log-list（サンプル
データ行含む）と突き合わせた。Rev1.3→Rev1.4 でこのシートは無改訂（セルテキスト・画像とも
ハッシュ一致）。シート本体は Rev1.1 で確定済み。

### 実装済み・仕様通りと確認した項目
- 職員番号の完全一致検索（B36-37）、職員名の全角スペース区切りフルネーム検索
  （B39-40、`core.text_normalization.filter_by_full_name`）、イベントメッセージの部分一致＋
  スペース区切りAND検索（B42-43）、個人情報書類チェックボックス絞り込み（B45-46）。
- 初期ソート＝操作日時 降順（B57-58、`order_by("-timestamp")`）、明細部の内部スクロール（B60）、
  ページャー1ページ100件（B62、Rev1.1で50→100）、一覧右上の総件数表示（B64）。
- CSV出力（B49-50、原本 alert() を超えるユーザー依頼実装、既記録）。
- イベントメッセージ連結形式（B68-76）：職員マスタ更新の差分形式（B69-70、
  `audit.services.build_diff_message`）、検索の項目列挙（B72-73、
  `core.search_services.build_search_audit_message`）、閲覧・DL 等の「ファイル名：…」（B75-76）。
- イベント記録の網羅性（ログイン/ログアウト/ログイン失敗、職員・部署・分類・カテゴリー・
  保存期間・権限・メイン画面項目・自動ログアウト設定の各登録/更新/削除、パスワード更新、
  CSV出力/取込、検索、DL/プレビュー、保管画面２の登録/更新/削除、権限自動リセット、
  物理削除バッチ）はすべて `audit_services.log()` / `log_raw()` 経由で記録済み。

### 発見・修正した乖離1件：操作内容の区切りが半角スペース（B66）
B66「操作内容は『画面名 ＋ □(全角スペース) ＋ ボタン名』とする」に対し、`action` 引数の全リテラル
（"分類管理 新規登録" 等）が**半角スペース(U+0020)区切り**だった。原本モックのサンプルデータは
一貫して全角（"カテゴリー管理　新規登録"、"文書　ダウンロード" 等）で、`audit/models.py` の
`help_text`・`audit/services.py` の docstring 自身も「全角スペース」と記載しており、コードだけが
不一致だった。2026-08-27 の行単位監査はイベントメッセージ連結形式（B68-76）を検証したが B66 の
区切り文字幅は突き合わせ対象外だった。

**修正**：`action` の「画面名／ボタン名」境界の区切りを全角スペースへ統一（`views.py`・
`master_views.py`・`record_views.py`・`services.py`・`csv_import_services.py`・
`purge_expired_deleted_records.py` の計約40リテラル＋対応するテスト assertion、20ファイル
125行）。`職員マスタ　CSV取込 所属長昇格` の内側の半角スペースは画面名境界ではなく
複合ラベル内の区切りのため据え置き（B66 が求めるのは画面名の後の1つ）。
`検索・閲覧画面 完全削除`（2026-08-24廃止の旧 DeleteView action 名を説明する core/tests.py の
docstring）は歴史的記述のため対象外。`manage.py test` 全780件PASS。`makemigrations --check`
差分なし。

### 原本モック 操作内容カラムとの差分監査（区切り修正後）
区切り修正後、B66 の書式（画面名＋全角スペース＋ボタン名）とは一致。ただし**画面名の粒度**が
モックのサンプルデータと異なる（既存の意図的差異、今回は変更せず）：
- モックは検索・閲覧・DL・編集・削除・アップロードいずれも画面名を素の「文書」「契約書」と
  しているが、実装は再実装時に採用した実画面名「文書検索」「契約書検索」「保管画面２」
  「検索・閲覧画面」を使う（例：モック「文書　検索」↔実装「文書検索　検索」）。
- モック「文書　閲覧」↔実装「文書検索　プレビュー」（ボタン名も閲覧→プレビュー）。
- モック「文書　アップロード」↔実装「保管画面２　登録」。
- モック自体もサンプル行内で不整合（"文書ダウンロード" のみ区切りなし）。
CLAUDE.md「xlsx/HTML のサンプル文言は手がかりに過ぎず、実装の要否・粒度は原本の実マークアップと
突き合わせて判断」に従い、正規の書式要件（B66）を満たすことを優先し、画面名は実画面名のまま
維持した。

### 対応不要（既確認済みの意図的乖離、再確認のみ）
- パスワード更新イベントの新旧パスワード平文 diff、権限管理更新のフラグ単位 diff：いずれも
  マスキング方針・記録粒度の既確定判断（`core/views.py`・`permissions/views.py` に理由コメント）。

## 操作履歴ログの最大保存件数／CSV出力最大件数（B51-52）の実装（2026-09-03、ユーザー依頼）

上記行単位監査時点では「2026-08-19 ユーザー確認済みで実装見送り確定」だった B51-52
「※操作履歴ログの最大保存件数(=CSV出力最大件数)設定値は、初期値を 3ヵ月分 とし、設定ファイル等で
定義し、先方より変更依頼を受けた際に容易に変更できること」を、ユーザー指示により実装した。

### 方針
「3ヵ月分」を月数（`settings.AUDIT_LOG_RETENTION_MONTHS`、`.env` 経由、既定3）で表現する。
`CONTRACT_RETENTION_YEARS`／`RETENTION_PERMANENT_YEARS`（xlsx 保存期間設定!B74、同じ「設定ファイル
等で定義し容易に変更」文言）が `masters.SystemSetting`（DB）から `.env` 経由の設定値へ移行済み
だった前例に合わせ、未使用のまま残っていた `SystemSetting.audit_log_retention_months` フィールドは
**削除**し（`models.py` ＋ `migrations/0001_initial.py` から。開発中のため新規マイグレーションは
作らず 0001 に畳み込み、`makemigrations --check` クリーンを確認）、`.env` 経由の設定値へ一本化した。
これで `SystemSetting` で実際に使うのは `session_idle_timeout_minutes` のみ。

### 実装
- `config/settings/base.py`：`AUDIT_LOG_RETENTION_MONTHS = env.int(..., default=3)` を追加、
  `.env.example` にも追記。
- `audit/services.py`：`retention_cutoff_date()` を追加（`core.notice_services.add_months` で
  今日から −N ヵ月。auditは下位アプリのため documents/contracts モデルを巻き込む
  notice_services のモジュールロード時結合を避けて関数内 import）。`filter_audit_log_queryset()`
  の基底 QuerySet に `timestamp__date__gte=retention_cutoff_date()` を追加し、**一覧表示・CSV出力の
  両方**で保持下限より古いログを除外（＝「最大保存件数＝CSV出力最大件数」をバッチ未実行・遅延時
  でも厳密に満たす）。検索フォームの操作日(開始)にそれより前を入れてもヒットしない。
- `core/management/commands/purge_expired_audit_logs.py`（新規）：保持下限より古い `AuditLog` を
  バルク `delete()`（ファイル実体を伴わず部分失敗要因が無いため 1件ずつにしない）。この物理削除
  イベント自体は操作履歴ログに記録しない（次回パージ対象になって増えるだけ、かつ「操作」ではなく
  保守バッチのため。`logger.info` で運用ログには残す）。`ja_system/bat/purge_expired_audit_logs.bat`
  （新規、`purge_expired_deleted_records.bat` と同じログローテーション付き、日次タスク想定）。
- `audit/tests.py`：`AuditLogRetentionTests`（一覧除外・設定値変更で下限が動く・パージが期限切れ
  のみ削除・パージが自己記録しない）＋ CSV除外テスト1件を追加。既存 `test_filter_by_date_range`
  の固定日付（2026-01）が保持下限より古くなったため、今日基準の相対日付へ書き換え。

### 検証
`manage.py test` 全**785件PASS**（新規5件）。`makemigrations --check` 差分なし、`manage.py check`
問題なし。`manage.py purge_expired_audit_logs` を開発DBで実行し `cutoff=2026-06-03 削除=0件` を確認。

### 運用面の申し送り
本番リリース時、`ja_system/bat/purge_expired_audit_logs.bat` を Windows タスクスケジューラに
日次で登録する（`purge_expired_deleted_records.bat` と同様）。保持期間の変更依頼を受けた際は
`.env` の `AUDIT_LOG_RETENTION_MONTHS` を書き換えるだけでよい。

## 「部署管理」シートの行単位全数監査・統合分割の設計確定・対象ポップアップからの自部署除外（2026-09-03）

ユーザー依頼で簡易設計指示書 Rev1.4「部署管理」シートを行単位で機械照合し、現行コードとのフル監査を実施した。

### 監査結果
- **シートは Rev1.1 で確定し、Rev1.1→Rev1.2→Rev1.3→Rev1.4 で無改訂**。セルテキスト・埋め込み画像
  6枚（image11〜16.png）とも全リビジョンでハッシュ一致。Rev1.0→1.1 の差分＝B210/B212 の統合・分割
  実処理が「対象部署を部署マスタから論理削除」→「閲覧部署範囲テーブルを更新」に仕様変更、J165・
  P195 の補足文言削除、AI178 誤記修正（統合→分割）——が最後の実体改訂。
- 一覧（B39-62）：本支所/部課連動プルダウン（B40/B42、`departments_list()` + `dept_list.html` の
  `updateSectionOptions()`）、部課プルダウンの退職99除外（B45、`section_choices()` /
  `departments_list(exclude_retired=True)`）、4列▲▼ソート（B52-56、`SORT_FIELDS`）、内部スクロール
  （B58）、ページャー無し（B60、`DeptListView` は Paginator 不使用）、総件数表示（B62）——実装済み。
- 新規登録（B82-88）：全欄空（B82）、本支所コード+部課コード重複エラー（B87、`UniqueConstraint`
  + `DeptRegistForm.clean` + IntegrityError 捕捉）、B88 の「本支所既存・部課のみ追加」は本支所を
  正規化しない設計上そのまま成立——実装済み。
- 編集（B107）：名称のみ可（`DeptEditForm.Meta.fields = ["branch_name","section_name"]`、コードは
  テンプレート表示のみ）——実装済み。
- 統合・分割（B109-212）：`DepartmentViewScope`（viewer_department／visible_department／action）＋
  `apply_dept_action`（merge=viewer:編集対象・visible:選択部署／split=viewer:選択部署・visible:編集
  対象）。`visible_department_ids(employee)` が「自部署＋自部署がviewerのスコープのvisible部署」を
  返し、`documents/contracts.search_services`・`core.notice_services`・保管フォームの部署絞り込み、
  検索フォームの部署欄初期値（検索・閲覧・変更!B46-48、`", ".join` でカンマ区切り自動表示）に反映。
  部署編集の「更新」ボタンは Employee を触らず、職員異動は職員マスタ CSV 取込
  （`_import_employee` の `department_changed`）側で行う——実装済み。`organizations` テスト45件PASS。

### 統合・分割の設計方針の確定（ユーザー確認）
実装是非を検討する過程でユーザーと設計を確認し、以下で確定：
- **文書に紐付いた部署情報は書き換えない**（付け替え案は不採用）。「閲覧部署範囲テーブル」
  （＝現行 `DepartmentViewScope`）に「部署Aの職員は部署Bのデータも見れる」を1行持たせる方式を正とする。
- 部署自体の統合（職員の一斉異動）は職員マスタ CSV 取込で行われ、そのタイミングで部署Bだった
  職員が部署Aへ異動する。異動後、検索画面の部署欄に「部署A,部署B」が自動表示され両方を検索・
  閲覧できる（B46-48）。＝現行実装のまま。
- 次の2点は本方式の想定挙動として**許容**（バグではない）と確認：
  1. 統合・分割後に部署Bが作る新規文書が部署A・Cから見える（スコープは無期限・部署単位のため）。
  2. 統合・分割時に部署A・Cへ「移った」旧・部署B文書が部署Bから見える（文書は実際には移動せず
     `department=B` のままのため）。
  いずれも標準フロー（CSV取込で部署Bが空になる）では顕在化しない。部署Bが存続し続ける運用に
  なった場合の締め付け（`Department.is_active` フラグ、文書単位可視性への変更等）は将来課題として
  ユーザーへ選択肢提示済み。

### 対象部署ポップアップからの「編集中の部署自体」除外（ユーザー依頼）
統合は存続部署Aの編集画面で吸収部署Bを、分割は分割元Bの編集画面で分割先を選ぶ運用のため、
どちらも編集中の部署自体を選択肢に出さないようにした。
- `organizations/forms.py` `DeptEditForm.__init__`（新規）：`self.instance.pk` があるとき
  `dept_action_target.queryset` を `Department.objects.exclude(pk=self.instance.pk)` に絞り、
  ウィジェットの `extra_query = {"exclude": self.instance.pk}` をセット。既存の `clean()` の自己参照
  チェックは API 直叩き・改ざんへの多重防御として残置。
- `organizations/api.py` `OptionListAPIView._department_items`：`request.GET.get("exclude")` を
  `int()` 変換して `qs.exclude(pk=...)`。非数値は 500 にせず全件返し `logger.warning`
  （`PopupSelectWidget` の非数値選択値ログと同じ方針）。
- 仕組みは permissions 側の `extra_query={"doc_kbn": ...}` と同一（`PopupSelectWidget.render` が
  `api_url` に `?exclude=<pk>` を付与 → `common.js openPopupPopup` が `&type=dept` を連結）。
- `organizations/tests.py`：API の exclude 動作・非数値無視、フォームの queryset 除外＋extra_query
  セットの3件を追加。`manage.py test organizations core permissions` PASS（organizations 48件）。

## 原本HTML改訂差分の確認（html5→html6）・簡易設計指示書 Rev1.5改訂の反映（2026-09-04）

原本改訂 Rev1.5（`../../HTML/html6/`、`文書管理システム_簡易設計指示書_Rev1_5.xlsx`、
表紙改訂履歴「1.5 / 2026-09-04 / その他設定 パスワード変更画面修正 他 / 原田」）を受領。
CLAUDE.md「原本改訂を受け取った時の手順」に従い機械diff→影響画面のみ反映。

**差分の全体像（洗い出しレポート scratchpad/Rev1_5_差分洗い出しレポート.md）**：
- html6/index.html の差分は 4 ハンクのみ、全て画面固有・パスワード表示の撤去。
  style.css はバイナリ一致、common.js / base.html への波及なし。
  - H-1 職員マスタ一覧：パスワード列を丸ごと削除
  - H-2 職員マスタ詳細：パスワード表示値 `ntarou1975`→`●●●●●●`（ja_pj は既にマスク済み）
  - H-3 職員マスタ編集：パスワード「目玉アイコン」👁️ と説明を削除
  - H-4 その他設定：パスワード変更画面の「現在のパスワード」行を削除
- 指示書のみ改訂（html6 に対応マークアップ無し）：
  - X-1 権限管理更新：システム権限"管理者"が0人になる更新を中止（B222-223）
  - X-2 職員CSV取込：所属長フラグでの管理者→所属長降格時の0人チェック（B127-128）
  - X-3 権限管理編集：システム権限プルダウン変更時に全項目リセット（B114）
  - X-4 部署統合・分割：更新前に対象部署名入りの確認メッセージ（B215-219）
  - X-5 部署統合・分割ポップアップから編集中部署を除外（B123）→ commit 727cdaf で実装済み
  - X-6 管理者はログイン者自身も編集可（B75）→ `can_manage_target` で実装済み
- 画像差分は4枚（H-1/H-3/H-4 に対応）。srcRect クロップ・白塗り sp 矩形なし。
- Rev1_3→Rev1_5 / Rev1_2→Rev1_5 クロスチェックで取りこぼし無しを確認。

以下、1件ずつ反映（各項目にテスト・チェックリスト更新まで含む）。

### H-1 職員マスタ一覧：パスワード列の削除（2026-09-04）

- 原本 html5→html6 diff：`<th>パスワード</th>` と全行 `<td>********</td>` を削除（13→12列）。
  xlsx 職員マスタ AI7「Rev1.5 画面変更」/ AI91「パスワード表示の文言削除」、B91 削除
  「・パスワードはセキュリティ上、空欄で出力すること。」。画像 image6→image8 で列消滅を確認。
- `templates/accounts/staff_list.html`：`<th>パスワード</th>`（78行付近）と `<td>********</td>`
  （96行付近）を削除。
- `accounts/views.py` `StaffCsvExportView`：削除された B91 は元々「CSV出力は空欄で」という
  CSV向け指示だったため、列廃止に合わせCSV出力のヘッダ「パスワード」と空値も削除
  （取込ヘッダ `CSV_HEADER` には元々パスワード列なし＝影響なし）。ユーザー確認済み（CSV出力列も削除）。
- テスト（`accounts/tests.py`）：
  - `StaffCsvExportViewTests.test_export_contains_header_and_row_without_password_column`
    （旧 `_with_blank_password` を改名）：ヘッダに「パスワード」を含まず「職員番号,氏名,本支所コード」で始まること。
  - `StaffSettingsMenuAccessControlTests.test_staff_list_has_no_password_column`（新規）：
    一覧レンダリング結果に `<th>パスワード</th>` / `<td>********</td>` が無いこと。
- `manage.py test accounts` 78件 PASS。

### H-2 職員マスタ詳細：パスワードのマスク文字を `●●●●●●` へ（2026-09-04）

- 原本 html5→html6 diff：職員マスタ詳細のパスワード表示値 `ntarou1975` → `●●●●●●`
  （原本がマスク表示に変更＝ja_pj のハッシュ運用に追いついた）。編集画面も同時に
  「目玉アイコン」削除（→ H-3）。
- ja_pj は元々ハッシュ化必須の規約で `********` マスク表示。**表記だけ原本に合わせ `●●●●●●` に統一**
  （ユーザー確認済み）。表示位置は `templates/accounts/staff_detail.html`（27-31行）のみ
  （一覧はH-1で列削除、その他設定「現在のパスワード」行はH-4で削除、staff_edit は入力欄で
  マスク文字列の表示なし、ログインはプリフィルなし）。`{% comment %}` の逸脱理由も更新。
- テスト（`accounts/tests.py`）：`StaffDetailViewTests.test_password_is_masked_not_shown_in_plaintext`
  に `assertContains(response, "●●●●●●")` を追加、docstring 更新。
- `manage.py test accounts.tests.StaffDetailViewTests accounts.tests.StaffCsvExportViewTests` 7件 PASS。
- 差異一覧xlsx シート「1_必然的な逸脱」No.2（職員マスタ詳細・編集のパスワード平文表示）は、
  原本詳細がマスク化されたことで詳細側の逸脱がほぼ解消。→ 末尾の「差異一覧xlsx更新」でまとめて反映。

### H-3 職員マスタ編集：目玉アイコン — 原本は削除したが ja_pj は意図的に保持（2026-09-04、ユーザー判断）

原本 html6 は職員マスタ編集画面から `<span class="password-toggle2" id="pass-toggle-icon2">👁️</span>
とその click ハンドラJS、xlsx の説明文（職員マスタ AI233「Rev1.5 パスワード目玉アイコン説明削除」）を
削除している（原本の 👁️ の本来の役目は「プリフィルされた平文 ntarou1975 を見る」ことで、
html6 は value を残したままアイコンだけ消した）。

**ja_pj は 👁️ トグルを保持する**（`templates/accounts/staff_edit.html` 53行の span、114-118行の
click ハンドラJS。現状のまま）。判断根拠（2026-09-04 ユーザーと確認）：
- ja_pj の当該欄は空欄ロード（プリフィルなし）。👁️ で見えるのは管理者がいま入力した値だけで、
  保存済みパスワードは露出しない＝原本が消した理由（プリフィル値の漏洩防止）は ja_pj に当てはまらない。
- 他人のパスワードを設定・リセットする画面のため入力確認の価値が高い。
- Chrome / Firefox には `type="password"` の汎用ネイティブ reveal 機能が無いため、独自トグルを消すと
  これらのブラウザでは確認手段がゼロになる（Edge/IE のみ `::-ms-reveal` でネイティブに出る）。
- ja_pj 内ではログイン画面（`.password-toggle`）と職員マスタ編集（`.password-toggle2`）で 👁️ を
  持っており、削除すると職員マスタ編集だけが原本と食い違う例外になる（保持すればログインと揃う）。

あわせて `static/css/style.css` に `::-ms-reveal` / `::-ms-clear` の抑制を追加：
```css
input[type="password"]::-ms-reveal,
input[type="password"]::-ms-clear { display: none; }
```
Edge で「独自 👁️ ＋ ネイティブ目玉」の二重表示になっていた（ログイン画面でも従来から発生）のを
独自トグルに一本化する。原本 style.css には無い ja_pj 独自の追加。

**その他設定 変更後パスワード欄にも同じトグルを追加**（2026-09-04 ユーザー依頼）。原本html6の
その他設定は `<input type="password">` 2つのみで 👁️ は無いが、変更後パスワード／確認欄の打ち間違い
確認のため、ログイン画面と同じ挙動の 👁️（`.password-toggle` ＋ `data-target` 属性で汎用ハンドラ）を
`templates/core/other_pass.html` に追加した。これで ja_pj のパスワード入力3画面（ログイン／
職員マスタ編集／その他設定）で表示切替 UX が揃う。

- テスト：
  - `accounts/tests.py` `StaffSettingsMenuAccessControlTests.test_staff_edit_keeps_password_reveal_toggle`
    （編集画面に `id="pass-toggle-icon2"` が描画され続けること＝原本追随で誤って消さない回帰ガード）
  - `core/tests.py` `OtherSettingsRoutingTests.test_password_change_fields_have_reveal_toggle`
    （その他設定に `data-target="id_new_password"` / `..._confirm"` が描画されること）
- 差異一覧xlsx シート4「見送った軽微差異」No.6 に理由付きで記録。

### H-4 その他設定：パスワード変更画面の「現在のパスワード」行を削除（2026-09-04）

- 原本 html5→html6 diff：`<tr><th>現在のパスワード</th><td>ja1111</td></tr>` を削除。
  表紙 J29「その他設定 パスワード変更画面修正 他」、その他設定 AI131「Rev1.5 画面変更」、image42 更新。
- `templates/core/other_pass.html`：`{% comment %}` ＋「現在のパスワード」`<tr>` を削除。
  「変更後パスワード」「変更後パスワード(確認)」の2行のみに。
- **サーバー側ロジックは維持**：`core/forms.py` `OtherPassForm.clean_new_password` の
  「変更後パスワードが現在のものと同一ならエラー」検証（xlsx その他設定!B150、Rev1_5 でも該当セル健在）は
  そのまま。docstring を「現在のパスワード欄はRev1.5で画面から削除、検証は維持」に更新。
- テスト（`core/tests.py` `OtherSettingsRoutingTests`）：
  - `test_password_change_has_no_current_password_row`（新規）：GET 画面に「現在のパスワード」文字列が無いこと。
  - 既存 `test_password_change_rejects_same_as_current`（B150 検証）はそのまま PASS。
- `manage.py test core.tests.OtherSettingsRoutingTests` 10件 PASS。
- 差異一覧xlsx シート「1_必然的な逸脱」No.3（その他設定 現在のパスワードの平文表示逸脱）は、
  行そのものが原本から消えたため逸脱解消 → 末尾の「差異一覧xlsx更新」でまとめて反映。

### X-1 権限管理 更新：システム権限"管理者"が0人になる更新を中止（2026-09-04）

- 指示書のみ改訂（html6 に対応マークアップ無し）：権限管理 B222「[重要]システム権限の"管理者"が
  0人にならないように、チェックを掛ける」＋ B223「管理者はシステム全体で1人以上必須の為、
  他の職員を先に"管理者"に設定する必要がある旨、メッセージを表示し更新を中止する」。AI222「Rev1.5 説明追加」。
- `permissions/services.py`：
  - `admin_count(exclude_profile_pk=None)`（新規）：role=ADMIN の PermissionProfile 件数。
    退職者は職員マスタ編集・CSV取込のどちらでも `reset_permission_profile_if_needed` で
    STAFF へリセットされるため、role=ADMIN のプロファイル＝現役管理者と一致する。
  - `would_orphan_admins(profile, new_role)`（新規）：現在 ADMIN の profile を ADMIN 以外へ
    下げる更新で、他に ADMIN が居なければ True。X-1（権限管理編集）と X-2（CSV取込の所属長降格）で共有。
- `permissions/forms.py` `AuthorityEditForm.clean_role`（新規）：`self.instance.role`（_post_clean 前＝
  DB の現在値）で判定し、orphan になるなら `ValidationError`
  「システム権限「管理者」はシステム全体で1人以上必須です。他の職員を先に「管理者」に設定してから
  変更してください。」。所属長のロール昇格阻止（既存 choices 絞り込み）とは独立。
- `templates/permissions/authority_edit.html`：システム権限セルに `{{ form.role.errors }}` の表示を追加
  （従来 non_field_errors しか出しておらず、role のフィールドエラーが画面に出なかった）。
- テスト（`permissions/tests.py`）：
  - `PermissionServicesTests.test_admin_count_and_would_orphan_admins`（新規）
  - `AuthorityEditViewTests.test_cannot_demote_last_admin` / `test_can_demote_admin_when_another_admin_exists`（新規）
- `manage.py test permissions` 68件 PASS。

### X-2 職員CSV取込：所属長フラグでの管理者→所属長降格を許容＋0人ガード（2026-09-04）

- 指示書のみ改訂：職員マスタ B127「・システム権限の"管理者"が所属長フラグによって"所属長"に
  変更になった際、システム側で管理者が0人にならないようにチェックを設ける」＋ B128「管理者が
  0人になる場合、メッセージを表示し、CSV取込による更新を中止すること」。AI127「Rev1.5 説明追加」。
- **既存の安全判断からの方針転換（ユーザー確認済み 2026-09-04、選択肢(b)）**：
  ja_pj は従来「CSV取込という間接経路で管理者権限を意図せず引き下げる事故を避ける」ため
  `_apply_manager_flag` で ADMIN を据え置いていた。Rev1.5 B127-128 が「降格前提の0人チェック」を
  明示的に要求したため、管理者→所属長の CSV 降格を許容する方向へ変更。
- `accounts/csv_import_services.py` `_apply_manager_flag` を書き換え：
  - STAFF → MANAGER：従来どおり昇格。
  - MANAGER：変更なし（早期 return）。
  - ADMIN → MANAGER：`permissions.services.would_orphan_admins(profile, MANAGER)` が True なら
    `ValueError`「所属長フラグにより管理者を所属長へ変更しようとしましたが、システムの管理者が
    0人になるため、この行の取込を中止しました。先に他の職員を管理者に設定してください。」を投げる。
    `import_staff_csv` の行単位 `transaction.atomic()` がロールバックされ `summary.errors` に集積
    （中止は**行単位**。1行のミスで取込全体を止めないという本モジュールの方針〈import_staff_csv
    docstring 明記〉に沿った解釈。B128「CSV取込による更新を中止」の粒度は指示書上曖昧なため
    行単位を採用）。orphan にならなければ降格し、監査ログの action を
    「職員マスタ　CSV取込 所属長降格」（昇格時は従来どおり「所属長昇格」）で記録。
  - 退職者は従来どおり昇格・降格とも行わない。
- `import` に `from permissions.services import would_orphan_admins` を追加（循環 import なし）。
- テスト（`accounts/tests.py` `ImportStaffCsvServiceTests`）：
  - `test_manager_flag_does_not_downgrade_admin`（旧・据え置き前提）を削除し、
    `test_manager_flag_demotes_admin_when_another_admin_exists`（他に管理者が居れば降格成立＋監査ログ）と
    `test_manager_flag_demotion_blocked_when_last_admin`（唯一の管理者なら行ロールバック・氏名変更も不発）に置換。
- `manage.py test accounts permissions core audit` 306件 PASS。

### X-3 権限管理編集：システム権限プルダウン変更時に全項目リセット（2026-09-04）

- 指示書のみ改訂（html6 に権限管理の動的制御追加なし、drawing6 画像も未変更）：
  権限管理 B114「[重要]現在の設定以外の権限を選択したタイミングで全ての項目をリセットする。
  (後述の「一括無許可」処理と同じ)」。AI114「Rev1.5 説明追加」。
  ユーザー合意済み（原本HTML未実装だが指示書 [重要] 指示のため実装、2026-09-04）。
- `templates/permissions/authority_edit.html` の `{% block extra_script %}`：
  - 「一括無許可」相当のクリア処理を `clearAllAuthoritySettings()` に切り出し
    （全チェックボックスOFF＋「選択」3項目〈doc_visible_groups / contract_visible_departments /
    contract_visible_groups〉の hidden・display 値クリア＋トグルボタン文言を「一括許可」へ戻す）。
    `toggleAllCheckboxesForAuth()` の「一括無許可」分岐はこれを呼ぶだけに簡約。
  - `initRoleChangeReset()`（IIFE）：`#id_role` の読み込み時の値を `originalRole` として保持し、
    `change` で値が `originalRole` 以外になったら `clearAllAuthoritySettings()` を実行。
- クライアント側JSのためユニットテストでは実挙動を検証できない。`permissions/tests.py`
  `AuthorityEditViewTests.test_edit_page_wires_role_change_reset` で
  `clearAllAuthoritySettings` / `initRoleChangeReset` / change リスナ登録が描画されることを確認
  （配線のみ）。実挙動はコードレビューで確認（`hidden.dataset.display` 参照は既存
  `toggleAllCheckboxesForAuth` と同一パターンで実績あり）。
- `manage.py test permissions` PASS（AuthorityEditView/Form 16件含む）。

### X-4 部署統合・分割：更新前の確認メッセージ（2026-09-04）

- 指示書のみ改訂（html6 に部署管理の動的制御追加なし、drawing5 画像も未変更）：
  部署管理 B215「※更新前に、統合と分割の確認がイメージできるようなメッセージを表示すること」、
  E217『部署A　に　部署Bの権限　が　統合されます。よろしいですか？』／
  E219『部署Cの権限　が　部署D、部署E　に　分割されます。よろしいですか？』、
  K126/K127（統合・分割の向きの注意書き）。AI215/AI126/AI127「Rev1.5 説明追加」。
  ユーザー合意済み（原本HTML未実装だが指示書指示のため実装、2026-09-04）。
- `templates/organizations/dept_edit.html`：
  - 「更新」ボタンの onclick を `confirm('更新してよろしいですか？')` から `confirmDeptUpdate()` へ。
    二重送信ガードの定型（先頭 `if (!this.form.reportValidity()) return false;`、末尾 `setTimeout`）は維持。
  - `confirmDeptUpdate()`（extra_script）：`dept_action` ラジオが merge/split のとき、編集中の部署名
    （`{{ department|escapejs }}` = `Department.__str__` ＝ 部課名）と対象部署の表示欄
    （`#id_dept_action_target_display` のカンマ区切り名称）を埋めた文言で `confirm()`。
    - merge：『{編集中} に {対象}の権限 が 統合されます。よろしいですか？』
    - split：『{編集中}の権限 が {対象} に 分割されます。よろしいですか？』
    向きは K126/K127（一覧で選択した＝編集中の部署を主語/目的語に）に一致。実処理の
    viewer/visible 対応（organizations/services.py apply_dept_action）とも整合。
  - 「通常(none)」のときは従来どおり『更新してよろしいですか？』。
- テスト（`organizations/tests.py` `DeptEditViewMergeSplitTests.test_edit_page_renders_dept_update_confirm_message`）：
  `confirmDeptUpdate` の定義・「更新」ボタンからの呼び出し・merge/split 文言・display 要素参照が
  描画されること（クライアントJSのため配線のみ。実挙動はコードレビューで確認）。
- `manage.py test organizations` 49件 PASS。

### X-1・X-2 追補：「管理者0人」ガードをリセット経路にも適用＋退職者除外（2026-09-04 ユーザー依頼）

Rev1.5 反映後の会話（2026-09-04）で、X-1/X-2 が「明示的なロール変更」2経路（権限管理編集の更新／
CSV所属長フラグ降格）しか塞いでおらず、**同じ Rev1.5 の 職員マスタ B245-248（Rev1.4 のまま）
＝本支所〜役職変更・退職に伴う `reset_permission_profile_if_needed`（role→STAFF）** には0人ガードが
無いことをユーザーへ指摘（①）。加えて `admin_count` が退職者を数えていた（③）。ユーザー依頼で両方修正。

- **① リセット経路のガード**：`accounts.services.reset_permission_profile_if_needed` が、role を STAFF へ
  落とす前に `permissions.services.would_orphan_admins(profile, STAFF)` を判定し、真なら新例外
  `accounts.services.LastAdminError`（`ValueError` サブクラス）を送出。これで下記2経路が塞がる：
  - **職員マスタ手動編集**（`accounts.views.StaffEditView.post`）：`form.save()` ＋
    `reset_permission_profile_if_needed()` を `transaction.atomic()` でラップし、`LastAdminError` を
    捕捉 → ロールバック → `employee.refresh_from_db()` → `messages.error` でフォーム再表示（`IntegrityError`
    分岐と同じ扱い）。「一切保存されない」状態にする。
  - **CSV取込**（`_import_row` は既に行単位 `transaction.atomic()`）：`import_staff_csv` の
    `except ValueError` がそのまま握り、当該行をロールバックして `summary.errors` へ集積（X-2 と同じ
    行単位中止）。`_apply_manager_flag` の所属長フラグ降格ガードも `ValueError` → `LastAdminError` に統一。
- **③ 退職者除外**：`permissions.services.admin_count` を
  `PermissionProfile.objects.filter(role=ADMIN, employee__is_retired=False)` に変更。退職者を後から
  権限管理編集で管理者化する経路（`AuthorityEditView` は is_retired を見ない）や Django admin 直接編集で
  ログイン不能な管理者が「1人」と数えられ0人ガードをすり抜けるのを防ぐ。
- Rev1.5 指示書はリセット経路自体のガードを明記していないが、X-1/X-2 と揃えないと「本支所を変えたら
  管理者が消えた」というサイレントな孤児化が残るため実装（ユーザー合意、2026-09-04）。②（CSV「中止」の
  粒度＝行単位か全ファイルか）と④（同時自己降格の競合）は現状の割り切りのまま（差異一覧へ記録）。
- テスト：
  - `permissions/tests.py`：`test_admin_count_excludes_retired`
  - `accounts/tests.py`：`ResetPermissionProfileTests.test_reset_blocked_when_it_would_orphan_admins` /
    `test_retired_keeper_admin_does_not_satisfy_the_guard`、
    `StaffEditViewResetPermissionIntegrationTests.test_editing_last_admins_own_position_is_blocked` /
    `_allowed_with_another_admin`、
    `ImportStaffCsvServiceTests.test_department_change_blocked_when_it_would_orphan_admins`。
  - 既存の「リセットされること」を検証するテストは、番人役の在職管理者を1名追加してガードに掛からない
    ようにした（`ResetPermissionProfileTests.setUp` / `test_department_change_resets_permissions`）。
- `manage.py test` 802件 PASS。

### 検索・閲覧・変更シート全行監査：削除済み一覧の行クリックプレビュー文言（2026-09-07 ユーザー依頼）

簡易設計指示書 Rev1.5「検索・閲覧・変更」シートの行単位機械監査（Rev1.1→1.5 の機械 diff で
**このシートは Rev1.2 以降 Rev1.5 まで無改訂**＝現行 Rev1.5 の全項目が実装済みであることを確認）中に
発見した軽微な不一致を修正。

- **症状**：`common.js showSearchPreview(title, previewUrl, kind, previewKind, isDeleted)` は第5引数
  `isDeleted`（"1"/""）で「本文書/本契約書は削除されているため、プレビューを表示できません。」を
  出し分ける作りだが、`templates/documents/search.html` / `templates/contracts/search.html` の行
  `onclick` が4引数しか渡しておらず、お知らせ「直近Xヵ月以内で削除された文書/契約書」一覧から
  行クリックした際に（削除済み専用文言ではなく）「ダウンロード権限が必要です」文言が出ていた。
  ※ 仕様項目そのもの（B347-348・B674-675 の詳細ポップアップ削除済みバナー「本文書は削除されています」）は
  `renderDetailPopup()` 側で正しく表示されるため、仕様は充足していた。ja_pj 独自のプレビュー補助文言のみの不一致。
- **修正**：両 search.html の行 `onclick` に第5引数 `'{% if document.is_deleted %}1{% endif %}'`
  （契約書側は `contract.is_deleted`）を追加。
- テスト：`documents/tests.py` `SearchPreviewPaneTests.test_row_click_passes_is_deleted_flag_to_showSearchPreview`、
  `contracts/tests.py` 同名（通常一覧は末尾 `', '')`、削除済み一覧〈notice=recently_deleted〉は末尾 `', '1')`）。
- `manage.py test documents contracts` 346件 PASS。

### 検索・閲覧・変更シート全行監査 追補：部署名の自動セットが管理者で効いていなかった（2026-09-08 ユーザー依頼）

「検索・閲覧・変更」B47（文書）／B417（契約書）「・ログインユーザーの部署を自動セットする。」を
管理者ケースで確認した結果、**検索画面の部署名欄が管理者だけ空**だった（一般・所属長は自部署が
プリフィル）。原本 html6 は `#search-dept value="総務部"`（`index.html:336`）でロールを問わず
プリフィルし、`transitionToSearch()` は「選択」ボタンの表示可否だけをロールで切り替える。保管画面
（B78-82）は ARCHIVE2「Rev1.1反映」項5 で同種の漏れ（管理者の部署欄が空）を修正済みだったが、
検索フォーム側へ横展開されていなかった。

- **原因**：`documents/contracts.forms.SearchForm.__init__` は非管理者分岐（`not
  can_select_department` / `allowed_ids is not None`）でしか `department` の初期値をセットして
  いなかった。かつ SearchForm は SearchView が常に `request.GET` でバインドするため、disabled で
  ない部署欄（＝「選択」ボタンを持つ管理者、契約書は部門間閲覧設定ありの職員も）は
  `field.initial` が描画に反映されない（`apply_radio_defaults` と同じ制約）。
- **修正**：`core.forms.apply_search_department_default(args, kwargs, department_ids)` を新設。
  `apply_radio_defaults` の直後に呼び、GET に `department` キーが無いときだけ
  `organizations.services.visible_department_ids(employee)`（自部署＋統合/分割スコープ、B48/B418）を
  カンマ区切りでバインド済み data に補完する。両 SearchForm で共通利用。非管理者の
  disabled＋`field.initial` は同じ id 集合で残す（disabled 経路は initial が使われるため）。
  契約書-部門間閲覧設定の部署は「選択」で追加する対象であって自動セット対象ではない（B421-423 は
  表示可否の規定）ため、自動セット値は `visible_department_ids` に限定（契約書非管理者の
  `field.initial` は従来どおり `contract_dept_ids` のままだが disabled 時のみ有効）。
- **副作用（意図的、ユーザー確認済み）**：管理者の既定の検索スコープが「全部署横断」から
  「自部署（＋統合/分割スコープ）」に変わる。他部署は「選択」で追加する。
- **操作履歴ログへの波及**：`core.search_services.build_search_audit_message(form, submitted_keys)`
  に `submitted_keys`（＝`request.GET.keys()`）引数を追加し、GET に実在するキーのフィールドだけを
  「検索した項目」に列挙するようにした（自動セットされた自部署は利用者入力ではないため除外。
  ラジオ既定値を `_SEARCH_AUDIT_EXCLUDED_FIELDS` で除くのと同じ考え方）。`documents/contracts.
  views.SearchView.get` の呼び出しを更新。
- テスト：`documents/tests.py` `SearchFormDepartmentAutoSetTests`（5件）、`contracts/tests.py`
  同名（5件、部門間閲覧設定ありの職員ケース含む）。既存 `SearchAuditLogTests` は
  submitted_keys 絞り込みで従来どおりの文言に戻ることを確認。`manage.py test` 全829件 PASS。

### 一括ダウンロードの未選択ガードをalert方式へ（一括編集と統一、2026-09-08 ユーザー依頼）

文書・契約書 検索・閲覧画面の「一括ダウンロード」ボタンを未選択で押したとき、サーバー側
`BaseBulkDownloadView.post` が `messages` で「ダウンロードする文書/契約書を選択してください。」を
出していた。ユーザー依頼で、一括編集ボタン（`startBulkEdit` の `alert`）と同じクライアント側
`alert` 方式に統一。

- `common.js` に `startBulkDownload()` を追加（`startBulkEdit()` と同型。選択0件なら
  `alert("ダウンロードするデータが選択されていません。")` して `return false`）。原本 html6 の
  当該ボタンは `onclick` 未設定のモックのため挙動の一次情報が無く、同じ「未選択ガード」を担う
  一括編集に揃えた（`alert` 文言も一括編集の「編集するデータが選択されていません。」と対にした）。
- `templates/{documents,contracts}/search.html` の「一括ダウンロード」ボタンに
  `onclick="return startBulkDownload();"` を付与。
- `core.record_views.BaseBulkDownloadView.post` の未選択時 `messages` 文言を
  「ダウンロードするデータが選択されていません。」に変更（URL直打ち・JS無効時の保険として
  サーバー側ガード自体は残す。`BulkEditStartView` の `messages` が `startBulkEdit` の `alert`
  文言に揃えてあるのと同じ扱い）。`entity_label`（文書/契約書）はこのメッセージでは不使用に。
- テスト：`documents/contracts.tests` の `BulkButtonsHiddenForRecentlyDeletedNoticeTests` に
  `test_bulk_download_button_has_client_side_unselected_guard`、`BulkDownloadViewTests` の
  `test_no_selection_redirects_with_message` を新文言でアサート（契約書側は新規追加）。
  `manage.py test documents contracts core` 495件 PASS。

### 検索・閲覧画面「文書イメージ」枠の初期プレースホルダが左寄せだった（2026-09-08 ユーザー報告）

文書／契約書 検索・閲覧画面の初期表示で、プレビュー枠の「一覧から行を選択すると／ここに
プレビューが表示されます」（＋📄）が中央でなく左寄りに表示されていた。

- **原因**：原本 style.css は `.pdf-view-box` 自体に `justify-content: center` があり中央表示
  だったが、ja_pj はズーム時のドラッグスクロールで左端に到達できるようにするため
  `justify-content` を外している（`.pdf-view-box` のコメント参照）。その結果、枠幅より狭い
  ブロックである `#search-preview-placeholder`（および権限不足文言）だけが主軸 flex-start＝
  左寄せになっていた。実プレビュー表示要素（`#search-preview-frame` は `width:100%`、
  `#search-pdfjs-preview` は `.pdfjs-preview` の `align-self:stretch`）は影響を受けない。
- **修正**：`static/css/style.css` に `#search-preview-placeholder { margin-left:auto;
  margin-right:auto; }` を追加（主軸方向のみ中央寄せを復元。cross 軸は `align-items:flex-start`
  のまま＝原本と同じ上寄せ）。文書・契約書 search.html が同一 id を使うため1ルールで両対応。
- **確認**：`seed_test_data` の管理者（9005）でログインし実プレビュー。枠 320px に対し
  左右の余白が 43px / 43px で一致（修正前は左 0 相当）。コンソールエラーなし。

## 簡易設計指示書 Rev1.6 改訂の反映（2026-09-09〜、ユーザー依頼）

原本HTMLの改訂は**なし**（html6 が最新のまま、style.css も無変更）。xlsx 単独改訂。差分の
洗い出しは作業用の差分レポート（反映完了後に削除。内容は本節に統合済み）で行った。変更は全16シート中
`表紙`／`保管`／`検索・閲覧・変更` の3シートのみで、すべて**契約書モード限定**。画像（スクショ）は
1枚も変化なし（`drawing13.xml` の差分は行挿入に伴うアンカー +2 シフトのみ）。

本質的な変更は「契約書の**関連書類**機能の仕様転換」：

| No. | シート | 内容 |
|---|---|---|
| R6-1 | 保管（契約書） | 関連書類を「物理ファイルのアップロード」→「既に保管済みの契約書をポップアップ検索して複数紐付け」へ転換 |
| R6-2 | 保管（契約書） | (X)ボタン説明文言：「選択したファイルの**紐付け**を取り止める」→「**関連付け**を取り止める」（文言修正のみ） |
| R6-3 | 検索・閲覧・変更（契約書） | 新規項目「関連資料」＝紐付けた契約書をファイル名リンク化しクリックでPDFを開く。削除済みは赤フォント＋「既に削除されている関連資料です」 |

ユーザー判断（2026-09-09、`AskUserQuestion`）：
- **R6-1 のモデル**：`RelatedFile`（物理ファイル）を**完全置換**（`t_contract_attachment` 廃止、
  契約書same-to-same の自己参照リンクへ）。本番リリース前のため既存アップロード済みデータは破棄。
- **R6-3 のリンク先**：紐付け先契約書の PDF を新規タブで開く（既存 `PreviewView`）。
- html6 が未改訂の点はユーザーが差分レポートを確認の上で反映を指示。

### R6-2 (X)ボタン説明文言の修正 — ja_pj では実装変更なし（2026-09-09）

xlsx 保管!（契約書）「関連書類「ファイルの選択」後の(X)ボタン」の説明文が Rev1.6 で
「選択したファイルの**紐付け**を取り止める。(行削除)」→「選択したファイルの**関連付け**を
取り止める。(行削除)」に変わった（AI注記「Rev1.6 文言修正」）。

- ja_pj の (X) ボタン（`btn-delete-file`）はキャプションが「×」のみで、xlsx の説明文に対応する
  ユーザー可視文字列を画面に持たない（原本 html6 も同様）。よって**コード変更は不要**。
- 「(行削除)」＝選択済み行をその場で取り消す挙動は、R6-1 の新モデル（紐付け先契約書のリスト
  から1行外す）でそのまま踏襲する。
- CLAUDE.md「ユーザー指示で意図的に見送った原本との差異…実装せず理由付きで記録」の方針に沿って
  ここに記録。テスト追加も無し（挙動変更が無いため）。

### R6-1 関連書類：物理ファイルアップロード → 既存契約書のポップアップ検索・複数紐付けへ（2026-09-09）

xlsx 保管!B478-484（契約書モード）：関連書類を「関連する(紐付ける)契約書を選択する。既に保存済みの
契約書を検索してセットする」「検索画面はポップアップ形式とし『契約書タイトル』『フリーワード』で
簡易的に検索」「検索範囲はログインユーザーの閲覧権限範囲と同等」「複数選択し、関連確定出来る」に
転換。原本 html6 は未改訂（file input のまま）だが、ユーザーが差分レポート確認の上で反映を指示。

**モデル（`AskUserQuestion` で「完全置換」を選択）**：
- `contracts.models.RelatedFile`（物理ファイル `FileField`、`t_contract_attachment`）を撤去し、
  `ContractRelation`（`contract` / `related_contract` の2FK＋`display_order`、`t_contract_relation`）を新設。
  両FKとも `on_delete=CASCADE`。`UniqueConstraint(contract, related_contract)` と
  `CheckConstraint(contract != related_contract)` を付与。
- **マイグレーション**：本番リリース前のため、旧 `RelatedFile`（`t_contract_attachment`）の履歴は
  残さず `0001_initial` の当該 `CreateModel` を `ContractRelation`（＋2つの `AddConstraint`）に
  直接置き換えて畳み込んだ（2026-09-09、ユーザー依頼「マイグレーションは0001_だけにして」）。
  contracts の運用マイグレーションは `0001_initial` の1本のみ。`contracts.storage_paths.
  related_file_upload_path` も撤去。フレッシュ環境は `migrate` 一発で最終スキーマになる。
- 既存アップロード済み関連書類データは破棄。切替時に運用側で `MEDIA_ROOT/contracts/related/` を
  手動削除すること（0001 のコメントにも明記）。
- （経緯：当初は破壊的な別マイグレーション `0002_rev16_related_contract_link` として作成し dev DB に
  適用済みだったが、上記ユーザー依頼で 0001 へ畳み込み。dev DB は `manage.py migrate contracts 0001
  --fake` 相当＋`django_migrations` の 0002 レコード削除でスキーマそのままに履歴だけ整理した。）

**新API**：`contracts:api_related_search`（`contracts.api.RelatedSearchAPIView`、`RequiresContractEditMixin`
で保護）。`title` / `freeword`（簡易検索のため OR 固定）で `contract_searchable_department_ids` の
範囲内・`is_deleted=False`・`exclude`（自分自身）を除いた契約書を更新日時の新しい順に最大
`RELATED_SEARCH_LIMIT`（50）件返す。タイトル/フリーワードのマッチは検索一覧と同じ
`core.search_services.apply_word_filter` / `apply_freeword_filter` を流用。

**ポップアップ UI**：`templates/base.html` に `#popup-related-search`（`popup-select` と同じ
`style-popup-select` クラス。契約書タイトル／フリーワード入力＋「検索」＋結果チェックボックス＋
「確定」）を新設。`common.js` は `openRelatedSearchPopup` / `runRelatedSearch` /
`renderRelatedSearchResults` / `submitRelatedSearchSelection` を追加。確定は「結果ページで
チェックしたものを追加、外したものを削除、結果に出ていない既存の紐付けは維持」で複数回検索を
またいで累積できる。`popup-select` のドラッグ/リサイズ IIFE は `makePopupMovable()` に、
`positionPopupPopup` は `positionPopupPopupEl(btn, el)` に切り出して両ポップアップで共用。
`handleRelatedFileChange` / `removeRelatedFileRow` / `removeExistingRelatedFile`（file input 時代の
関数）は撤去。

**送信形式**：選んだ契約書1件につき hidden input を1つ。保管画面は `related_contract_ids_{index}`
（ファイルごと）、編集・一括編集は `related_contract_ids`。`request.POST.getlist()` で受ける。
サーバー側は `contracts.services.filter_valid_related_ids(ids, employee, exclude_pk)` で実在・
閲覧範囲内・自分以外に絞る（改ざん対策。外れた値は `logger.warning`）。同期は
`sync_related_contracts(contract, related_ids)`（全量リストに一致させる：外れた行を削除、新規を追加、
`display_order` を並びに合わせる）。

**ビュー**：
- `UploadStep2View`：`RelatedFile.objects.create` ループ → `sync_related_contracts`。関連書類の
  ファイルI/Oが無くなったため `created_related` の孤児ファイル後始末を撤去。「削除」（表示中ファイルの
  取り消し）でも `_remap_related_ids_after_remove` で hidden input を添字詰め直し＝選び直し不要に。
  再描画は `_merge_related_into_field_sets` で `file_field_sets` の各要素に `related_contracts` を注入。
- `ContractEditView`：`apply_contract_edit(contract, cleaned_data, employee, related_ids)`（差分
  `remove_ids`/`new_related_files` → 全量 `related_ids`）。ファイルI/O例外が無くなり `except OSError`
  を撤去（`except DBError` は維持）。`related_rows`（`{id,title,is_deleted}`）をテンプレートへ。
- `BulkEditView`：`core.bulk_edit_services` の `stage_related`（tmp退避）→ `stage_related_ids`
  （pkリストを丸ごと上書き）、`staged_related_for` → `staged_related_ids_for`。
  `discard_staged_related_files` と `core.upload_services.stash_files_to_tmp` は未使用になり撤去
  （`discard_bulk_edit` は state 破棄のみに）。確定パスの `opened_files` / `PendingFileStorageError`
  ハンドリングも撤去。
- `core.management.commands.purge_expired_deleted_records`：契約書の `extra_files_fn`
  （related_files のファイル実体退避）を撤去。ContractRelation は CASCADE で自動削除。

**編集テンプレート**：`edit.html` の [3] は bulk / 単独 の分岐を廃し `related_rows` の1ループに統一。
`storage2.html` の [3] は `#storage-related-container-{index}`＋「ファイルの選択」ボタンへ。
`remove_related_ids` hidden・file input・「関連書類は選び直しが必要です」の注記を撤去。

**テスト**：`contracts/tests.py` の関連書類テスト群を全面改修（`RelatedSearchAPIViewTests` 新規3件、
`RelatedFilesMultiUploadTests`・`BulkEditViewTests`・`ContractEditViewFileHandlingTests`・
`DetailAPIViewTests`・`DeleteViewAjaxTests` を ContractRelation ベースに書き換え、
`StoragePathTests` の related_file_upload_path 2件は削除）。`core/tests.py` の
`BulkEditServicesStagingTests` 2件・`PurgeExpiredDeletedRecordsCommandTests` 1件も書き換え。
`manage.py test` 全846件 PASS（R6-3 まで反映後の最終値）。

**ブラウザ確認**（seed_test_data、9005 管理四郎）：契約書編集 [3]「ファイルの選択」→ ポップアップで
「Book1」を検索・チェック・確定 → 行「📎 Book1 ×」表示 → 更新 → `ContractRelation(6→5)` が永続化。
検索・閲覧の詳細ポップアップ「関連書類」欄に紐付け先タイトル「📎 Book1」表示。コンソールエラー無し。
（seed の契約書pk1・3・7 は category が doc_kbn=document の不正データで編集フォームが元々
バリデーションエラーになる別問題。R6-1 とは無関係。）

**detail API**：R6-1 では `related_files` キーで紐付け先契約書タイトルの配列を返すだけ（表示は
素テキスト踏襲）。リンク化・削除済み赤表示は R6-3 で対応。

### R6-3 検索・閲覧・変更（契約書）「関連書類」欄をリンク化・削除済みは赤表示（2026-09-09）

xlsx 検索・閲覧・変更!B677-680（Rev1.6 仕様追加、原本ラベルは「関連資料」だが html6 の詳細
ポップアップは「関連書類」で未改訂＝そのまま踏襲）：
- 関連資料が設定されている場合はファイル名にリンクを設定し、クリックでPDFファイルが開ける。
- 関連資料が既に削除されている場合は赤フォントで表示し、クリック時に「既に削除されている
  関連資料です」とメッセージを表示する。

ユーザー判断（`AskUserQuestion`）：リンク先は**紐付け先契約書のPDFを新規タブで開く**（既存
`contracts:preview` / `PreviewView`）。

- **`contracts.api.DetailAPIView`**：`related_files`（タイトル配列）→ `related_contracts`
  （`[{title, is_deleted, preview_url}]`）。`preview_url` は「紐付け先が削除されておらず、かつ
  閲覧者に契約書ダウンロード権限がある」ときだけ `reverse("contracts:preview", args=[pk])` を入れ、
  それ以外は `None`。
- **`static/js/common.js`**：詳細ポップアップのプロパティ表「関連書類」行を
  `renderRelatedResourceLink(rc)` で組む。
  - `preview_url` あり → `<a target="_blank" rel="noopener">📎 タイトル</a>`
  - `is_deleted` → `<a href="#" style="color:#c0392b" onclick="alertDeletedRelatedResource();return false;">`
    （`alertDeletedRelatedResource()` は `alert("既に削除されている関連資料です")` のみ）
  - どちらでもない（権限不足）→ 素テキスト
  タイトルは `escapeHtml` 済みの整形済みHTMLとして innerHTML へ（従来の複数ファイル名 `<br>` 連結と
  同じ扱い）。
- ついでに Rev1.6 で不要になったコメント・引数を整理：`core.upload_views.
  remap_step2_initial_after_remove` の docstring、`core.management.commands.
  purge_expired_deleted_records._purge` の `extra_files_fn` 引数（関連書類がファイルを持たなくなり
  未使用に）と `_delete_file` の `related_pk` 引数を撤去。

**テスト**：`contracts/tests.py DetailAPIViewTests` に `related_contracts` の3ケース
（権限ありでpreview_url／削除済みで is_deleted=true・preview_url=null／権限なしで preview_url=null）。
`core/tests.py` の物理削除バッチのpkログ検証は末尾スペース依存だったのを緩めた。
`manage.py test` 全846件 PASS。

**ブラウザ確認**（seed_test_data、9005）：契約書「Print」に「Book1」（有効）と「削除済み旧契約
2020」（is_deleted=True）を紐付け → 検索・閲覧の詳細ポップアップで「📎 Book1」が
`/contracts/5/preview/` への別タブリンク、「📎 …削除済み旧契約2020」が赤字＋クリックで
「既に削除されている関連資料です」。コンソールエラー無し。

これで Rev1.6（R6-1／R6-2／R6-3）の反映は完了。
