# HTML確定版への作り直し チェックリスト

このファイルは進捗管理用の作業メモであり、仕様書ではない。
**画面構成・項目・挙動の一次情報源は常に届いたHTML/簡易設計指示書そのもの**であり、
このチェックリストや棚卸し表の記載とHTML/xlsxが食い違った場合は必ずHTML/xlsxを正とする。

開発ルール（コーディング規約・原本フィデリティに関する運用方針）は`CLAUDE.md`に集約されている。
過去このファイル側で運用ルールとして記述していた内容のうち一般化できるものは、2026-08-24に
CLAUDE.mdへ昇格済み（原本改訂受領時のdiff優先手順、同一注記の繰り返し確認、Djangoテンプレート
コメントの罠など）。

完了済みフェーズの詳細な実装経緯・監査結果・バグ修正ログは
[HTML_REIMPL_CHECKLIST_ARCHIVE.md](HTML_REIMPL_CHECKLIST_ARCHIVE.md)に切り出した
（2026-08-24、元ファイルが1815行まで肥大化したため分割。**新規セッションが通常参照すべきは
このファイルのみ**。アーカイブは特定の過去の判断・バグ修正の詳しい経緯を掘り下げたい時にのみ開く）。

## 実装状況サマリ
- 第一陣（検索・保管画面）／第二陣（設定画面：職員マスタ〜権限管理）／第三陣（設定画面：
  分類マスタ〜その他設定）とも実装・原本フィデリティ監査完了。フェーズ8の全陣横断整合性
  チェックも完了。詳細はアーカイブの「フェーズ0」〜「フェーズ8」節参照。
- 原本HTML改訂 html1→html2→html3→html4→html5、簡易設計指示書 Rev1.0→…→Rev1.3→Rev1.4まで
  反映済み（現在の一次情報源はhtml5 + Rev1.4）。詳細はアーカイブの「原本HTML改訂差分の確認」
  「原本HTML/xlsx Rev1.1改訂の反映」「簡易設計指示書 Rev1.2改訂の反映」
  「簡易設計指示書 Rev1.3改訂の反映」「原本HTML改訂差分の確認（html4→html5）・簡易設計指示書
  Rev1.4改訂の反映」各節参照。
- html4→html5 / Rev1.3→Rev1.4改訂の反映（2026-08-28）：Rev1.4は保管シートの説明文言復活＋説明画像
  2枚のみで新規挙動なし。html5で新規反映したのは (A)権限管理一覧「操作」列の固定列化、(B)保管
  登録フォームの「削除」ボタンを[4]メモ欄ボックス外へ移動、(C)common.js `openPopupPopup`の
  ポップアップ縦位置反転、(D)メイン画面お知らせのラッパを`.notice-columns`クラスに統一、
  (E)権限管理編集の表示欄textareaを`rows="5"`に。他のhtml5差分はモックがRev1.2/Rev1.3に追いついた
  だけで実装影響なし。詳細はアーカイブ該当節参照。
- xlsx記載の要再確認（赤字）27箇所は全件解消済み。残る恒久的な未実装・保留事項は
  `CLAUDE.md`「既知の未実装・保留事項」に集約されている（電子決裁機能全般、論理削除
  文書・契約書の復元機能は「不要」と最終確定済み）。
- レイアウト差異・文言差異・機能面差異の監査もそれぞれ完了済み。見送った低優先度差異は
  アーカイブの各監査節に理由付きで記録されている。
- audit/coreアプリのテストカバレッジ棚卸し（2026-08-26）：高・中優先度の指摘に対応する
  テストを追加済み（`manage.py test audit core`115→130件）。見送った低優先度・一部中優先度は
  理由付きでアーカイブに記録済み。
- メイン画面ボタン制御（xlsx メイン画面!B55）を`organizations.MenuItemSetting`へ再連動
  （2026-08-26、ユーザーが原本フィデリティより実データ連動を優先する方針へ変更）。詳細は
  アーカイブ「メイン画面ボタン制御をMenuItemSettingへ再連動」節参照。
- 操作履歴ログ（xlsx Rev1.2、原本index.htmlサンプルデータ）の行単位全数監査（2026-08-27）：
  検索操作の記録漏れ・ダウンロード等のメッセージ形式・更新イベントの差分記録漏れの3件を修正。
  詳細はアーカイブ「操作履歴ログの行単位全数監査・記録漏れ修正」節参照。
- 検索結果一覧「一括編集」の原本html4との挙動差異を修正（2026-08-27）：未選択時メッセージ文言、
  および送信ボタンを原本どおり常に「更新」（どのページでも即全件確定）に統一。詳細はアーカイブ
  「検索結果一覧 一括編集：原本html4との挙動差異の修正」節参照。
- 簡易設計指示書 Rev1.3改訂の反映（2026-08-27）：権限管理編集画面の「文書管理-分類-表示／
  契約書-部門間閲覧設定／契約書-分類-表示」3欄の表示用要素を1行inputから複数行textareaへ変更
  （`PopupSelectWidget`に`display_multiline`フラグ追加）。権限管理一覧の行内「編集」ボタンの
  背景色を白→`#FFCCFF`（初回見落とし、ユーザー指摘で修正）。保管シートの重複文言削除は
  実装影響なし。詳細はアーカイブ「簡易設計指示書 Rev1.3改訂の反映」節参照。
- 保管画面２「削除」ボタンの再定義（2026-08-27、ユーザー確定）：原本のメモ欄クリア（`clearMemo`）を
  廃止し、単独編集画面＝レコードの論理削除（`EditDeleteView`、xlsx B300/B581の1週間・削除済み非表示）
  ／登録画面＝表示中ファイルのアップロード取り消し（`UploadStep2RemoveView`、他ファイルは登録続行、
  入力途中は破棄）に変更。詳細はアーカイブ「保管画面２「削除」ボタンをメモ消去→レコード削除／
  アップロード取り消しへ変更」節参照。
- 一括編集を「更新ボタンで全ページ一括確定」モデルへ改修（2026-08-28、ユーザー確定）：save-as-you-go
  を廃止し、入力値・削除マーク・関連書類の増減を「更新」までセッション（＋一時ファイル領域）に
  ステージ。「更新」で全ページ検証→変更のあったページだけを1トランザクションで確定（dirty判定で
  「更新なし」を除外、エラー時は最初のエラーページへジャンプ、完了モーダルに全件を状態付きで表示）。
  削除は「削除予定」マーク＋「削除取消」トグル、「キャンセル」で全破棄。詳細はアーカイブ
  「一括編集を「更新ボタンで全ページ一括確定」モデルへ改修」節参照。
- documents/contractsコードレビュー（`review_code_documents_contracts.txt`、`/code-review high`）の
  反映（2026-08-28）：高＝0件。中3件（C-1 保存満了日の編集時再計算を「保存期間変更時のみ」に
  3経路で統一／C-2 契約書編集の関連書類保存途中失敗時の孤児ファイル後始末／C-3 一括DLのZIP構築を
  OSError全般捕捉に拡大）＋C-4（ZIPエントリ名をdisplay_name化＋同名連番）を修正、`manage.py test
  documents contracts`290件PASS。低優先度12件（C-5〜C-9・R-1〜R-7）は`review_pending.txt`項番
  45〜56に理由付きで記録。詳細はアーカイブ「documents/contractsコードレビューの反映」節参照。
- セキュリティレビュー（`review_security.txt`、リポジトリ全体精査）優先度「高」「中」の反映
  （2026-08-28）：高3件（H-1/H-2 検索結果詳細・行クリックプレビューの格納型XSS＝common.jsを
  escapeHtml／DOM API化／H-3 アップロードファイルのMIME未検証＋inline配信＝`core/file_serving.py`・
  `core/upload_validation.py`新設で「PDF・画像以外はinline配信させずnosniff/CSP付与」＋
  「HTML/SVG/スクリプトのアップロード拒否」）、中2件（M-1 一括編集ステージング型削除の
  can_delete()サーバー側未検証をtoggle_delete・_commit両方で補完／M-2 prod.pyの
  SECRET_KEYデフォルト廃止）を1件ずつ修正。`manage.py test`全752件PASS（新規テスト14件純増）。
  低優先度L-1〜L-3・情報I-1は修正せず`review_security.txt`「対応結果」節に理由付きで記録。
  アプリ全体CSP・MEDIA別オリジン配信は中期対応として見送り。詳細はアーカイブ
  「セキュリティレビュー（review_security.txt）優先度「高」「中」の反映」節参照。
- チャンク分割アップロードのチャンクサイズを settings 化（2026-08-28、ユーザー問い合わせ→指示）：
  JSハードコード（5MB）を `settings.CHUNK_UPLOAD_CHUNK_SIZE_BYTES`（`env.int`、既定5MB）へ集約し、
  保管画面１のテンプレートコンテキスト経由で `chunk_upload.js` の `uploadFilesInChunks()` 第3引数へ
  渡す方式に変更。推奨サイズ（既定のまま可、大容量主体なら10MBまで、5MB未満不可、上限は
  `MAX_UPLOAD_SIZE_BYTES` とリバースプロキシのボディ上限に依存）をコメントで明記。
  `manage.py test documents contracts` 332件PASS（新規1件）。詳細はアーカイブ
  「チャンク分割アップロードのチャンクサイズを settings 化」節参照。
- 保管画面２：複数件登録のメタデータをファイルごとの個別入力へ（2026-08-31、ユーザー依頼）：
  新規保管で複数ファイルを一括選択したとき、部署・分類・年・カテゴリー・保存期間・個人情報・
  メモ（契約書は契約日等）を「1回の入力でバッチ共通適用」から「ページャーで表示中のファイル
  ごとに個別入力」へ変更（原本の `startRegisterMock()` はバッチ共通＝意図的な差異）。
  `UploadStep2Form` が createモードで `PER_FILE_FIELDS` を `{name}_{i}` に複製、`file_data(i)` /
  `first_error_file_index()` 追加。`core.upload_views.file_field_sets` ＋ storage2.html を
  `.doc-fieldset` ループ化。編集画面（1ファイル）は挙動不変。続く追補で、複数件登録中の
  「削除」（アップロード取り消し）が残るファイルの入力を保持するよう変更（メインフォームごと
  `action=remove` で送信 → `UploadStep2View._handle_remove` が残りの入力値を詰め直して
  unbound フォームの initial に載せ再描画。旧 `upload_step2_remove` URL/`BaseUploadStep2RemoveView`
  は廃止）。契約書 storage2 の複数行 `{# #}` コメント生表示・`.form-row` 全行 flex-wrap による
  契約期間行の折り返しも同時修正（`:has(.field-error)` に限定）。`manage.py test documents
  contracts core` 470件PASS。詳細はアーカイブ「保管画面２：複数件登録のメタデータをファイル
  ごとの個別入力へ」節（追補3つ含む）参照。
- 保管画面２／編集画面のフィールドエラー表示位置を入力欄の下へ（2026-08-31、ユーザー指摘）：
  `.form-row`（flex）内で素の `<div>` だったDjango必須エラーが入力欄の右隣に横並び表示されて
  いたため、`django_widgets.css` に `.form-row:has(.field-error) { flex-wrap:wrap }` ＋
  `.field-error`（flex-basis:100%、ラベル幅ぶん字下げ）を追加し、storage2/edit の4テンプレートの
  エラー `<div>` を `class="field-error"` へ統一。実プレビューで分類・カテゴリーのエラーが
  入力欄直下に出ることを実測確認。詳細はアーカイブ
  「保管画面２／編集画面のフィールドエラー表示位置を入力欄の下へ」節参照。
- 保管画面２・詳細ポップアップ・編集画面の右側（情報表示・入力エリア）が原本より約10px狭い
  問題を修正（2026-08-31、ユーザー指摘）：ドラッグスクロール用に追加した `.pdf-scroll-area`
  （幅1140px・flex-shrink:0）の固定幅が左列 `.pdf-preview-container` の flex 自動最小サイズ
  として染み出し、`.storage-layout` の収縮時に左列がほぼ縮まず右列 `.meta-input-form-wrapper`
  （35%）が原本より狭くなっていた。`style.css` の `.pdf-preview-container` に `min-width:0` を
  追加し本来の 65/35 に復帰（実プレビュー実測：詳細ポップアップ右列 398.3→408.0px＝原本一致、
  編集画面 446.x→456.75px＝原本一致）。ドラッグスクロール／ズームは影響なし。詳細はアーカイブ
  「保管画面２・詳細・編集画面の右側エリアが原本より狭い問題の修正」節参照。
- PDFプレビューを PDF.js 自前描画へ（2026-08-31、ユーザー依頼）：実プレビュー（2026-08-12追加）の
  PDF を、狭い枠で問題の出るブラウザ内蔵PDFビューア `<iframe>`（ツールバー見切れ→水平スクロール
  バー、横長ページの右欠け）から、PDF.js（`static/vendor/pdfjs` 3.11.174 legacy、CDN不使用）で
  各ページを枠幅ぴったりの `<canvas>` に描画する方式へ変更。`IntersectionObserver` ではなく
  スクロール連動の遅延描画で数百ページPDFでも軽い。`settings.PDF_JS_PREVIEW_ENABLED`（`.env`、
  既定True）を False にすれば旧 `<iframe>` へ完全復帰（アセットも読み込まれない）。画像プレビュー
  （`<img>`）・モック文言は不変。新規：`static/js/pdf-preview.js`・`core/context_processors.py`。
  `manage.py test` 全766件PASS（フラグON/OFF両テスト追加）。詳細はアーカイブ
  「PDFプレビューを PDF.js 自前描画へ」節参照。
- ↑の追補（2026-08-31、ユーザー依頼）：当初対象外だった**文書／契約書 検索・閲覧画面の
  「文書イメージ」欄も PDF.js へ**。お知らせ件数リンク経由と「検索・閲覧・変更」ボタン経由で
  プレビューの見え方が違うとの指摘（実体はブラウザ内蔵PDFビューアがズーム/ツールバー状態を
  ブラウザ側で保持する挙動差。アプリ側の差ではない）を機に、`search.html` に
  `#search-pdfjs-preview` 枠を追加、`common.js showSearchPreview()` を PDF は `PdfPreview.render()`・
  画像は従来 `<iframe>` に振り分け。`SearchPreviewPaneTests` 追加、`test documents contracts` 342件PASS。
  詳細はアーカイブ「検索・閲覧画面『文書イメージ』欄も PDF.js へ」節参照。
- 職員マスタ編集のパスワード欄ヒント文言を欄外（右側）へ配置変更（2026-09-01、ユーザー依頼）：
  `.password-note-aside`（`password-wrapper` 基準の絶対配置）。詳細はアーカイブ該当節参照。
- 登録・編集フォームの送信ボタンが必須エラー後に押せなくなる不具合を修正（2026-09-01、ユーザー報告）：
  二重送信防止の `onclick` が、クライアント側必須バリデーションで送信がブロックされた場合でも
  `setTimeout` でボタンを `disabled` にしていた。`onclick` 先頭に
  `if (!this.form.reportValidity()) return false;` を追加（登録/編集/削除フォーム16ファイル一括）。
  `test accounts masters organizations` 211件PASS。詳細はアーカイブ「登録・編集フォームの
  『登録/更新』ボタンが必須エラー後に押せなくなる不具合の修正」節参照。
- 職員マスタ登録・編集：部課が1つだけの本支所で部課が表示・選択できない不具合を修正
  （2026-09-01、ユーザー報告）：`updateSections()` の部課select無効化判定を「本支所コードが000か」
  から「実在する部課（section_code 非空）を持つか」に変更（`staff_regist.html`/`staff_edit.html`）。
  `test accounts` 77件PASS。詳細はアーカイブ該当節参照。
- 権限管理編集「システム権限」プルダウンに空選択肢 `---------` が出る不具合を修正
  （2026-09-02、ユーザー報告）：`PermissionProfile.role` が blank/default なしの `CharField(choices)`
  のため Django ModelForm が空選択肢を自動付与していた。`AuthorityEditForm.__init__` で
  `editable_roles` 未指定（管理者編集）時も `role.choices` を `PermissionRole` の3値のみに絞る
  よう変更（xlsx 権限管理!B113-115）。`test permissions` 65件PASS。「権限管理」シートは
  Rev1.4まで本件以外に仕様乖離なしを行単位監査で確認済み。
- 「保存期間設定」シートの行単位全数監査（2026-09-03、ユーザー依頼）：シートは Rev1.0〜Rev1.4 で
  無改訂（セルテキスト・埋め込み画像8枚ともハッシュ一致）。一覧/登録/編集/削除の4画面×文書/
  電子決裁、ラジオ切替・書類名プルダウン・「永年」制御（数値クリア＋入力不可、実年数は
  `settings.RETENTION_PERMANENT_YEARS`）・論理削除・初期ソート（表示順昇順）・No.連番はすべて実装
  済み。**唯一の乖離＝B77/B104/B191/B229「保存期間や表示順の重複登録を出来ないように制御」のうち
  "保存期間そのもの"（period_value+period_unit、「永年」は値なし）の重複が未制御**（表示順のみ実装
  済みだった）だったため修正：`RetentionPeriod` に `unique_retention_period_value`（kbn,doc_name,
  period_value,period_unit）＋ `unique_retention_permanent`（period_unit='permanent' 限定の部分
  ユニーク、「永年」を書類名毎に1件へ）の2制約を追加、`RetentionPeriodForm.clean`
  に同趣旨のアプリ層チェック、`RetentionRegist/EditView` の重複時フォールバック文言を
  「保存期間または表示順が…重複」に一般化。`manage.py test` 全779件PASS（新規4件）。
  開発中のため新規マイグレーションは作らず `masters/migrations/0001_initial.py` の
  `RetentionPeriod` の `constraints` に直接畳み込み（`makemigrations --check` クリーン、
  開発DBには手動で部分ユニークインデックス2本を作成＋シードの「永年」重複1行を削除）。
  ※本番反映前に既存 `m_retention_period` に同一保存期間・複数「永年」の重複行が無いか要確認。
  追補（2026-09-03、ユーザー報告）：「永年」の設定を編集画面で開くと保存期間の数値が入力できる
  不具合を修正。原本の `handlePermanent()` は select の `onchange` にしか繋がっておらず初期表示で
  未実行だったため、`retention_edit.html`/`retention_regist.html` に `DOMContentLoaded` で
  `handlePermanent(#id_period_unit)` を1回呼ぶ初期化を追加。実プレビューで「永年」→数値欄
  disabled、単位変更で enable/disable 追従、非永年は enable を実測確認。回帰テスト1件追加。

## 継続タスク
- [ ] 新機能追加のたびにユニットテスト追加
- [ ] 進捗に応じて随時コミット（陣単位・フェーズ単位を目安に）

## 原本改訂・xlsx改訂を受け取った時の対応
手順は`CLAUDE.md`「原本改訂を受け取った時の手順」参照（diff優先で機械的に差分特定→画面固有／
共通部分に振り分け→該当箇所のみ確認→反映経緯を記録）。過去の適用実例（html1→html2、
html3→html4、xlsx Rev1.1、xlsx Rev1.2の反映）はアーカイブ参照。新たな改訂を反映した際は、
このファイルの「実装状況サマリ」と`CLAUDE.md`の該当箇所を更新し、詳細な反映経緯は
アーカイブに追記すること。

## 新たに要再確認事項が生じた場合
`CLAUDE.md`「既知の未実装・保留事項」とこのファイルの「実装状況サマリ」を更新すること。
