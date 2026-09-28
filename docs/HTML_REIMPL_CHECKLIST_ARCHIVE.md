# HTML確定版への作り直し チェックリスト（アーカイブ：Rev1.5以降の詳細記録）

このファイルは[HTML_REIMPL_CHECKLIST.md](HTML_REIMPL_CHECKLIST.md)から、完了済み作業の詳細な
実装経緯・監査結果・バグ修正ログを切り出したアーカイブである（2026-08-24に分割、2026-09-07に
初期分を[HTML_REIMPL_CHECKLIST_ARCHIVE2.md](HTML_REIMPL_CHECKLIST_ARCHIVE2.md)へ、2026-09-16に
Rev1.4期〜2026-09-03頃の記録を[HTML_REIMPL_CHECKLIST_ARCHIVE3.md](HTML_REIMPL_CHECKLIST_ARCHIVE3.md)
へ再分割。方針は[[feedback_html_checklist_archive_split]]）。

**このファイルにはRev1.5改訂（html5→html6、2026-09-04）以降の記録のみが入っている**。それより前は
以下を参照：
- Phase 0〜8の作り直し・原本フィデリティ監査・Rev1.1〜Rev1.3期は
  [HTML_REIMPL_CHECKLIST_ARCHIVE2.md](HTML_REIMPL_CHECKLIST_ARCHIVE2.md)
- Rev1.4改訂の反映（2026-08-28）〜2026-09-03頃は
  [HTML_REIMPL_CHECKLIST_ARCHIVE3.md](HTML_REIMPL_CHECKLIST_ARCHIVE3.md)

**新規セッションが通常参照すべきはHTML_REIMPL_CHECKLIST.mdのみ**。このアーカイブは特定の過去の
判断・バグ修正の詳しい経緯を掘り下げたい時にのみ参照する。一般化済みの運用ルールはCLAUDE.md
「原本フィデリティに関する運用方針」に集約済み。今後の新規記録はこのファイルの末尾に追記する。

---

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

> **監査 A-2（2026-09-10）**：html6 は依然 `<input type="file">`（index.html:287）で旧 RelatedFile UI の
> まま＝Rev1.6 未追従。ja_pj の実装は xlsx Rev1.6 B478-484 準拠。「レンダリングされる原本マークアップを
> 基準にする」というモデル定義妥当性監査の方針に対する**明示的な例外**として確定（ユーザー承認済み）。

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

---

## models定義 妥当性監査 フェーズ2：指摘対応（2026-09-10〜、ユーザー依頼）

`MODEL_AUDIT_FINDINGS.md`（フェーズ1で5監査を統合した一覧）を上から順に対応する。フェーズ1の
指示テンプレートは `MODEL_AUDIT_INSTRUCTION_TEMPLATE.md`。1件ずつ「提案→ユーザー承認→適用」、
モデル変更は 0001_initial.py 直書き（本番リリース前 squash 運用）、新規制約・バリデータには
tests.py にユニットテスト追加、コミットはユーザー指示があるまでしない。

### セクション0：方針確定（Q-1〜Q-7、2026-09-10 ユーザー承認）

| Q | 確定した方針 |
|---|---|
| Q-1 | `Meta.ordering` は全モデルには付けない。一覧のソートはビュー側 `core.search_services.apply_sort` 依存を正とする（B-ORD は原則対応せず、素通り経路の有無だけ確認）。 |
| Q-2 | `models.py` の `logger` 宣言は現状維持（7:1 混在を許容）。CLAUDE.md が「モデル定義のみは不要」「未使用宣言も許容」の両論を明記済みで実害なし（C-7 は観察のまま no-op）。 |
| Q-3 | `*_normalized`（`editable=False`）シャドウ列に日本語 `verbose_name` は付けない。「検索用内部列のため付けない」をコメントで明示（C-1）。 |
| Q-4 | モデル層バリデーションは「CSV取込という実在の非フォーム経路がバイパスするもの」だけ追加する。`employee_no`/`Group.code`/`Category.code` に `RegexValidator`（半角数字）、`year`/`period_value`/`display_order`/`session_idle_timeout_minutes` に Min/Max バリデータ。フォームの全角→半角変換 `clean_*` はそのまま残す。 |
| Q-5 | `AuditLog` は現行「自由テキストのみ」を仕様確定。構造化参照列（target_type/target_id）は追加しない（D-3、方針コメント追記のみ）。 |
| Q-6 | 論理削除マスタ（Group/Category/RetentionPeriod）の `department IS NULL` 行は、本番移行で `department` を必ず補完する運用で確定（null 残置は許容しない、A-3）。 |
| Q-7 | `contract_amount max_digits=12/decimal_places=0`（DecimalField 維持）・`title max_length=255`・`branch_code`/`section_code max_length=10`・`session_idle_timeout_minutes` 既定60（ただし C-6 で settings 参照の callable 化）・`Position` "90" 閉じ括弧補正 — いずれも確定値として承認。A-2（html6 の Rev1.6 未追従）は上記 R6-1 節に注記。A-4（`contract_partner` をフリーワード検索対象に）は現状維持。 |

### A軸（A-1〜A-5）：コメント・記録の追記のみ（2026-09-10、コード挙動変更なし）

- **A-1**：`contracts/models.py` `contract_amount` に桁/型確定の理由コメント（原本・xlsx とも指定なし、
  9,999億円上限・整数格納、DecimalField 維持は CommaNumberInput が Decimal 往復前提のため）。
- **A-2**：上記 R6-1 節に「html6 は Rev1.6 未追従、ja_pj は xlsx 準拠。原本マークアップ基準の監査方針への
  明示的な例外」を注記。
- **A-3**：`masters/models.py` の `unique_group_code`/`unique_category_code` コメントに「本番移行で
  `department IS NULL` 行の department を必ず補完（null 残置は許容しない）」を追記。
  `doc/文書管理システム_残項目_本番リリース手順書.xlsx` への反映はユーザー指示があれば別途。
- **A-4**：`contracts/models.py` `contract_partner` に「フリーワード検索・正規化シャドウの対象外、
  xlsx 記載なしのため現状維持で確定」のコメント。
- **A-5**：`accounts/models.py` `Position` "90" に「原本 index.html:2195 は閉じ括弧欠落、タイポ補正のまま
  確定」のコメント。
- マイグレーション不要（`makemigrations --check` 不変）、既存データ影響なし、テスト追加なし。

### B-IDX-1（深刻度：中）：未使用の生 `extracted_text` GIN 索引を削除（2026-09-10）

`extracted_text`（生カラム）の `gin_trgm_ops` GIN（`doc_extracted_text_trgm` /
`contract_extracted_text_trgm`）はどのクエリからも使われていなかった。フリーワード全文検索
（`core.search_services.apply_freeword_filter`）・タイトル検索（`apply_word_filter`）はいずれも
正規化シャドウ列（`title_normalized` / `memo_normalized` / `extracted_text_normalized`）にしか
`icontains` せず、生 `extracted_text` を参照するのは `extract_pending_pdf_text` の
`filter(extracted_text="")`（OCR未処理レコード抽出）の**等値判定のみ**で、trgm GIN の効くアクセス
パターンではない。生 GIN は OCR 更新（本文数十KB）ごとの書き込みコストだけ発生していた。

- `documents/models.py` / `contracts/models.py` の `Meta.indexes` から生 `extracted_text` の
  `GinIndex` を削除（`extracted_text_normalized` の GIN は維持）。理由コメントを両モデルに追記。
- `documents/migrations/0001_initial.py`（`options["indexes"]`）・`contracts/migrations/0001_initial.py`
  （`AddIndex`）から当該行を削除（0001 直書き、`makemigrations --check` クリーン）。
- `config/settings/base.py:36` の `django.contrib.postgres` のコメントを「正規化シャドウ列の
  GinIndex 用」に修正。
- テスト：`documents.tests.DocumentIndexTests` / `contracts.tests.ContractIndexTests`（SimpleTestCase）を
  新設。「生 `extracted_text` の GIN が無い／正規化列の GIN はある」を固定。
- `manage.py test documents contracts` 416件 PASS。
- 既存 dev DB は手動 `DROP INDEX doc_extracted_text_trgm; DROP INDEX contract_extracted_text_trgm;`
  が必要（フレッシュ環境は `migrate` 一発で最終形）。

### B-IDX-2（深刻度：中）：`title_normalized` / `memo_normalized` に GIN 索引を追加（2026-09-10）

フリーワード検索は正規化3列（`title_normalized` / `memo_normalized` / `extracted_text_normalized`）を
OR で `icontains`、タイトル検索は `title_normalized` を `icontains` するが、GIN があるのは
`extracted_text_normalized` だけで、3列 OR の検索が結局フルスキャンに落ちていた。

- `documents/models.py` に `doc_title_norm_trgm` / `doc_memo_norm_trgm`、`contracts/models.py` に
  `contract_title_norm_trgm` / `contract_memo_norm_trgm` の `GinIndex(gin_trgm_ops)` を追加。
  これで正規化シャドウ列3本すべてに GIN が揃い、B-IDX-1 と合わせて「検索は正規化列、GIN も正規化列」で
  方針統一。
- 両 `0001_initial.py` に 0001 直書きで追記（`makemigrations --check` クリーン）。
- テスト：`DocumentIndexTests` / `ContractIndexTests` に `title_normalized` / `memo_normalized` の
  GIN 存在 assertion を追加。既存のタイトル検索・フリーワード検索テストが機能回帰を担保。
- `manage.py test documents contracts` 418件 PASS。
- 既存 dev DB はフレッシュ `migrate` で反映（squash 運用）。

### B-IDX-3 / B-IDX-4（深刻度：中）：`expiry_date` / `save_date` に `db_index=True`（2026-09-10）

- `expiry_date`：メイン画面お知らせ集計（`expiry_date__lt today` / 範囲）・検索「保存満了日」範囲/
  ソートで常用。`save_date`：一覧の初期ソート（`order_by("-save_date")`）＋期間検索（`save_date__date`
  範囲）で常用。いずれも無索引だった。
- documents / contracts 両モデルの当該フィールドに `db_index=True` を追加。`0001_initial.py` の
  `CreateModel` フィールド定義にも反映（`db_index=True` は暗黙インデックスで別 operation を生まないため
  `AddIndex` 行は不要、`makemigrations --check` クリーン）。
- テスト：`DocumentIndexTests` / `ContractIndexTests` に `db_index` True の assertion 追加。
- `manage.py test documents contracts` 420件 PASS。

### B-IDX-5 / B-IDX-6（深刻度：低）：削除済みレコードとログ職員番号の索引（2026-09-10）

- **B-IDX-5**：documents / contracts の `Meta.indexes` に `models.Index(fields=["deleted_at"],
  condition=Q(is_deleted=True), name="doc_/contract_deleted_at_partial")` を追加。削除済み行だけの
  小さな部分索引で、ゴミ箱一覧（`search_services` の `filter(is_deleted=True)`）と日次バッチ
  `purge_expired_deleted_records`（`is_deleted=True` かつ `deleted_at` 範囲）が使う。
  メイン画面お知らせの `recently_deleted` は `aggregate(Count("pk", filter=Q(...)))` の条件付き集約で
  3件数を1スキャンで出す構造上どの索引も使わないため対象外（コメントに明記）。生 `is_deleted` 単独の
  btree は低選択性（`False` が大多数）で使われないため張らない。
- **B-IDX-6**：`audit.AuditLog.employee_no` に `db_index=True`。一覧・CSV の職員番号完全一致検索用。
  ログテーブルは無制限に増える。
- 両方 `0001_initial.py` 直書き、`makemigrations --check` クリーン。
- テスト：部分索引の名前 assertion（documents/contracts）、`AuditLogIndexTests`（audit）。
- `manage.py test documents contracts audit` 455件 PASS。

### B-VAL-1（深刻度：中）：コード類フィールドに `RegexValidator`（半角数字）（2026-09-10）

`employee_no` / `Group.code` / `Category.code` の「半角数字のみ」検証がフォームの `clean_*`（NFKC
正規化→`isdigit`）と CSV 取込側にしか無かった。

- `accounts/models.py` に `_HANKAKU_DIGITS_VALIDATOR = RegexValidator(r"^[0-9]+$", "半角数字で入力して
  ください")` を定義し `employee_no` に付与。`masters/models.py` にも同名の validator を定義し
  `Group.code` / `Category.code` に付与。両 `0001_initial.py` にも `validators=[...]` を直書き
  （`import django.core.validators` 追加、`makemigrations --check` クリーン）。
- **効く経路 / 効かない経路**：`full_clean()` を通る admin・将来の ModelForm では弾く。素の `save()`
  および CSV 取込（`create_user()`/`save()` 直呼び）は `full_clean()` を通らないため、CSV 取込側の
  明示的な正規化＋チェック（`accounts.csv_import_services`）は撤去せず維持。フォームの `clean_*` も
  NFKC 変換を担うため残す（多層防御）。
- テスト：`masters.tests.CodeValidatorModelTests`、`accounts.tests.EmployeeModelTests` に
  `full_clean()` の全角・非数字拒否テストを追加。既存の TOCTOU IntegrityError テスト2件
  （`test_group_regist/edit_integrity_error_shows_friendly_message`）が非数字コード `"A"` を
  フォーム POST していたため、数字コード `"70"/"71"` に修正（テストの意図＝(department, code)
  一意制約の競合再現は不変）。
- `manage.py test` 全件 PASS。

### B-VAL-3 / B-VAL-4（深刻度：低）：数値フィールドの下限（・上限）バリデータ（2026-09-10）

- **B-VAL-3**：`documents.Document.year` / `contracts.Contract.year` に
  `[MinValueValidator(1900), MaxValueValidator(2200)]`。定数 `_YEAR_VALIDATORS` は両モデルに併記
  （2行の定数のためクロスアプリ import を避けた）。フォームは choices で絞るため実挙動は不変、
  admin・一括・将来コードの直接 save で 0・5桁の異常年を防ぐ多層防御。
- **B-VAL-4**：`RetentionPeriod.period_value`（0ヵ月/0年保存は無意味、null＝永年は検証スキップ）／
  `RetentionPeriod.display_order`（表示順は1始まり）／`SystemSetting.session_idle_timeout_minutes`
  （0分＝即時ログアウトで破綻）に `MinValueValidator(1)`。`contracts.ContractRelation.display_order`
  （`default=0` の内部リンク順）は対象外（コメントに明記）。
- 3アプリ（documents/contracts/masters）の `0001_initial.py` 直書き。`import django.core.validators`
  追加、`makemigrations --check` クリーン。
- テスト：`DocumentYearValidatorTests` / `ContractYearValidatorTests` / `MinValueValidatorModelTests`
  （いずれも field の `run_validators()` を直接叩く SimpleTestCase）。
- `manage.py test documents contracts masters core` 709件 PASS。

### D-1（深刻度：中）：`PermissionProfile.role` に `default=PermissionRole.STAFF`（2026-09-10）

xlsx 職員マスタ D118「新規登録時に『権限管理』は初期値をセットしておく」。初期値 STAFF が
CSV取込の即時 `create(role=STAFF)`・手動登録後の遅延 `get_or_create(defaults={"role": STAFF})`・
`services.get_role` の欠損フォールバックに散在していた。

- `permissions/models.py` の `role` に `default=PermissionRole.STAFF`、`0001_initial.py` に
  `default='staff'` を直書き（`makemigrations --check` クリーン）。
- **ユーザー指示で「default のみ」**：`csv_import_services` の明示 `role=STAFF` 指定は残す（冗長だが
  意図が読める）。職員登録時に `PermissionProfile` を必ず同時生成するフロー統一（遅延生成3経路の
  リファクタ）は別スコープとして見送り。
- テスト：`PermissionServicesTests.test_role_field_defaults_to_staff`。
- `manage.py test permissions accounts` 183件 PASS。

### B-12（深刻度：低〜中）：`is_active` を `is_retired` から導出（退職者ログインの多層防御）（2026-09-10）

`is_retired=True` でも `is_active` は `True` のまま（`is_active` はアプリコードのどこからも
読み書きされず、定義のみ）。退職者ログイン拒否は `LoginForm.confirm_login_allowed` 1箇所頼みで、
Django の `ModelBackend.user_can_authenticate` / `get_user`（セッション復元）は素通りだった。

- `accounts/models.py`：`is_active` BooleanField を削除し `@property def is_active(self): return
  not self.is_retired` に。`0001_initial.py` から `is_active` カラム定義を削除（`--check` クリーン、
  `m_staff.is_active` カラムはフレッシュ migrate で消える）。
- これで `ModelBackend` も退職者を弾く。ただし副作用として `AuthenticationForm.authenticate()` が
  退職者に None を返し、ログイン画面のエラーが専用メッセージ→汎用メッセージに変わる。
  **ユーザー選択で専用メッセージを維持**：`LoginForm.clean` を上書きし、`super().clean()` が
  ValidationError を投げたケースのうち「職員番号が存在・退職済み・パスワード一致」の時だけ
  「退職済みの職員はログインできません。」を出す（パスワード不一致では汎用エラー＝アカウントの
  存在・退職を明かさない。従来挙動と等価）。`confirm_login_allowed` の override は廃止。
- テスト：`test_is_active_is_derived_from_is_retired`（`ModelBackend.user_can_authenticate`）、
  `test_retired_employee_wrong_password_gets_generic_error` を追加。既存の
  `test_retired_employee_cannot_login` は不変で PASS。
- `manage.py test` 全984件 PASS。

### B-VAL-5 / B-VAL-6 / B-VAL-7（深刻度：低）：CheckConstraint とシングルトンアクセサ（2026-09-10）

- **B-VAL-5**：`contracts.Contract` に `contract_period_start_before_end` CheckConstraint
  （`period_start <= period_end`、両端 null 可）。フォームの `validate_date_range` に加えた DB 側の
  多層防御。`ContractRelation.no_self_contract_relation` と rigor を揃える。
- **B-VAL-6**：`organizations.DepartmentViewScope` に `no_self_department_view_scope` CheckConstraint
  （`viewer != visible`）。`apply_dept_action` は既に `target == department` をスキップするが DB でも
  担保。`ContractRelation` と対称。
- **B-VAL-7**：`CheckConstraint(pk=1)` は **不採用**（Postgres のシーケンスがロールバックで戻らない
  ため、`objects.create()`（自動pk）主体のテスト・admin で pk が 1 以外になり制約違反が頻発する）。
  代わりに `SystemSetting.load()` classmethod（`get_or_create(pk=1)[0]`）を新設し、読み口を集約：
  - `core/views.py` の3箇所（`OtherMainView`、`LogoutTimeEditView.get/post`）の `get_or_create(pk=1)`
    を `SystemSetting.load()` に置換（挙動同値の純リファクタ）。
  - `core/middleware.py._get_timeout_minutes` は **`.first()` + None フォールバックを維持**（理由コメント
    追記）。全リクエスト経路のミドルウェアで、行が未作成の状態〈デプロイ直後・マイグレーション直後〉
    でも DB へ書き込まず `settings.SESSION_IDLE_TIMEOUT_MINUTES` へ静かに倒れる方が安全なため。
- 3アプリ（contracts/organizations）の `0001_initial.py` に `AddConstraint` / options.constraints を
  直書き。masters はモデル変更のみ（constraint 追加なし）。`makemigrations --check` クリーン。
- テスト：`ContractPeriodConstraintTests` / `DepartmentViewScopeConstraintTests`（IntegrityError）、
  `SystemSettingLoadTests`。
- `manage.py test contracts organizations masters core` 564件 PASS。

### B-VAL-2 / B-VAL-8（深刻度：低）：モデル層のデータ整合バリデーション（2026-09-10）

- **B-VAL-2**：`masters.Category.clean()` に「`group.doc_kbn` と自身の `doc_kbn` が一致しないと
  ValidationError」を追加。`CategoryForm.clean` の既存チェックは残す（Category は CSV 取込経路が無く
  full_clean() で十分＝admin・将来 ModelForm の多層防御）。マイグレーション不要。
- **B-VAL-8**：`core/upload_validation.py` に `validate_no_active_content(value)` を新設
  （`is_blocked_upload_filename` を使い HTML/SVG/JS 等を ValidationError）。`Document.file` /
  `Contract.file` の `validators` に付与（`0001_initial.py` 直書き、`import core.upload_validation`）。
  アップロードポリシーは**拒否リスト方式**（セキュリティレビュー H-3、Office/PDF/画像/zip は許可）
  のため、許可リスト型の `FileExtensionValidator` は使わない。`searchable_file` はシステム生成 PDF の
  ため対象外。`BaseUploadStep1View` の入口チェックと二重防御。
- テスト：`CodeValidatorModelTests.test_category_doc_kbn_must_match_group`、
  `DocumentFileValidatorTests` / `ContractFileValidatorTests`。
- `manage.py test documents contracts masters core` 718件 PASS。

### B-7 / B-8（深刻度：低）：設定系テーブルのタイムスタンプ非対称を解消（2026-09-10）

管理画面から更新される設定テーブルのうち、他マスタ（Group/Category/RetentionPeriod/Department/
Employee は created_at/updated_at 両方持ち）と非対称だったものを揃えた。

- `permissions.PermissionProfile`：`created_at` 追加（updated_at は既存）。
- `organizations.MenuItemSetting`：`created_at` / `updated_at` 追加。
- `masters.SystemSetting`：`created_at` / `updated_at` 追加。
- `organizations.DepartmentViewScope`：`updated_at` 追加（created_at は既存。`apply_dept_action` は
  `update_or_create` で action を更新することがある）。
- 3アプリの `0001_initial.py` は 0001 直書き（`makemigrations` は `auto_now_add` 追加で対話プロンプトに
  なるため、生成させず手編集）。`makemigrations --check` クリーン。
- テスト：`PermissionServicesTests.test_profile_has_created_and_updated_timestamps`（B-7）。
  他は Django 標準の auto_now(_add) 挙動のため専用テストなし。
- `manage.py test permissions organizations masters` 273件 PASS。

### E-1 / E-2 / E-3（深刻度：低・整容）：マイグレーション整容（2026-09-10、スキーマ変更なし）

- **E-1**：`contracts.ContractRelation` の `CheckConstraint(check=…)` を `condition=…` に
  （`check=` は Django 5.1 で非推奨・6.0 で削除予定。生成済み migration は既に `condition=`）。
- **E-2**：`audit.AuditLog` の `models.Index(fields=["-timestamp"])` に `name="auditlog_timestamp_desc_idx"`
  を明示。`0001_initial.py` の pin 名も自動命名 `t_audit_log_timesta_894930_idx` から同名に更新。
  同ファイルの GinIndex 2本・documents/contracts の索引と揃う。
- **E-3**：`contracts/0001_initial.py` の Contract 用 `AddIndex` 4本＋`AddConstraint` 1本
  （`contract_period_start_before_end`）を `CreateModel(Contract)` の `options["indexes"/"constraints"]`
  へ移動し、documents 側の記述方式に統一。`ContractRelation` の `AddConstraint` 2本は別モデルのため
  据え置き。
- 3ファイルとも `makemigrations --check` クリーン。テスト：`AuditLogIndexTests` に timestamp 索引名の
  assertion 追加。`manage.py test audit contracts documents` 467件 PASS。

### C-2 / C-6（深刻度：低）：AbstractBaseUser 継承フィールドの日本語化・既定値のハードコード解消（2026-09-10）

- **C-2**：`Employee` に `password`（"パスワード"）/ `last_login`（"最終ログイン"）を `AbstractBaseUser`
  と同一定義で再宣言し `verbose_name` を日本語化（`is_staff`/`is_superuser` と揃える）。`0001_initial.py`
  の該当行も更新。
- **C-6**：`masters/models.py` に `_default_session_idle_timeout()`（`return settings.SESSION_IDLE_TIMEOUT_MINUTES`）
  を定義し `SystemSetting.session_idle_timeout_minutes` の `default=60` を callable 参照に。ハードコード
  `60` と settings フォールバック値の重複を解消。migration は `masters.models._default_session_idle_timeout`
  としてシリアライズ（`import masters.models` 追加）。
- テスト：`accounts.tests` に verbose_name assertion、`masters.tests.SystemSettingLoadTests.
  test_default_session_idle_timeout_follows_settings`（`override_settings`）。
- `manage.py test accounts masters core` 388件 PASS。

### B-9 / B-10 / B-11 / B-13 / B-ORD / D-3 / C-1 / C-3 / C-4 / C-5 / C-7：コメント・docstring のみ（2026-09-10）

コード挙動変更ゼロ・マイグレーション不要。「なぜ現状で確定か／既知の制約」をコード近傍に残した。

- **B-9**：`audit.AuditLog.department_name` に「実効長は 100（`str(employee.department)`）、200 は将来の
  部署名長変更・改編時の余裕」コメント。
- **B-10**：`PermissionProfile` の `doc_visible_groups`/`contract_visible_groups` に「Group 論理削除で
  中間テーブルに残る行は消費側が `is_deleted=False` で必ず絞るため実害なし。棚卸しが要れば
  `related_name` を付ける」コメント。
- **B-11**：`PermissionRole` の docstring と `permissions.services.AUTHORITY_SORT_FIELDS["role"]` に
  「`admin`/`manager`/`staff` のアルファベット順が xlsx 権限コード 1/2/3 昇順と偶然一致。格納値を
  変えるなら `Case/When` 化が必要」。
- **B-13**：`ContractRelation` docstring に「紐付け先（非所有側）の物理削除で所有側の関連行も記録を
  残さず消える点は認識済み・現状維持」。
- **B-ORD**：`core.search_services.apply_sort` docstring に「`Meta.ordering` は持たせない方針（Q-1）、
  この関数が一覧ソートの唯一の入口」。`documents`/`contracts.search_services.build_queryset` は全 return
  経路で `apply_sort` を通し、未指定でも `order_by("-save_date")` で確定することをコード確認済み。
- **D-3**：`AuditLog` docstring に「構造化参照列は持たず自由テキストのみで確定（Q-5）」。
- **C-1**：`documents`/`contracts` の `*_normalized` に「`verbose_name` は付けない（editable=False の
  検索用内部列、Q-3）」。
- **C-3**：`EmployeeManager.create_user`/`create_superuser` に1行 docstring。
- **C-4**：`RetentionPeriod.__str__` に「永年」特別扱いの docstring。
- **C-5**：`Employee.has_perm`/`has_module_perms` に「admin 用最小実装、認可は permissions アプリ」コメント。
- **C-7**：Q-2 で「`models.py` の `logger` 宣言は現状維持（7:1 混在を許容）」と確定。コード変更なし。

`manage.py test` 全件 PASS（回帰なし）。

---

以上で `MODEL_AUDIT_FINDINGS.md` フェーズ2の全指摘に対応完了（対応 or 理由付きで現状維持を確定）。
D-2（電子決裁3フラグ＝現状維持）・D-4（FK方向・循環import・related_name＝問題なし）・E軸の
`--check` 差分なし、およびセクション6「問題なし」項目は元々対応不要。

---

## 全文検索・OCRデータ層の再設計（案1+2+3、2026-09-11、ユーザー依頼）

「1000ページPDF等で `extracted_text` と `extracted_text_normalized` の二重保持＋埋め込み済み
searchable_file の恒久保存が容量を圧迫する」というユーザーからの容量最適化の相談を受けて、
モデル定義妥当性監査フェーズ2の直後に別サイクルとして再設計した（xlsx/HTML 仕様外の
OCR・検索・ストレージ再設計のため、CLAUDE.md 方針どおりユーザー承認＋独立実装。設計討議で
「現在の ja_pj 機能はすべて満たせる」ことを機能マトリクスで確認済み。決定：privacy_flag=True は
ocr_textdata も保存しない／保存するのは textdatas（Vision 生レスポンスではない）。推奨6ポイント
すべてユーザー承認）。

### 案1：生 `extracted_text` カラムを廃止

- `documents.Document` / `contracts.Contract` から `extracted_text`（TextField）を**削除**。
  検索の唯一の格納テキストは `extracted_text_normalized`（NFKC 正規化済み）のみ。
- populate は `NormalizedTextFieldsMixin`（title/memo の *_normalized 導出）**ではなく**、
  抽出サービス（`core.text_extraction_services.try_immediate_text_layer_extraction` /
  `core.management.commands.extract_pending_pdf_text`）が `normalize_for_search(text)` を直接
  セットして `save(update_fields=["extracted_text_normalized", "text_extracted"])` する。
  → Mixin の `_NORMALIZED_FIELD_MAP` から `extracted_text` 対応を除去。通常の title 変更等で
  OCR全文を無駄に再正規化する問題も消滅。
- 根拠：テキスト層抽出（pdfplumber）は決定的・ローカル・無料で元ファイルから再実行でき、
  OCR 結果は `ocr_textdata` から `_get_textlines` で再導出できる（privacy 除く）。生テキストを
  DB に持つ意味が無い。原本性は原本ファイル `file` の保持でカバー。

### 案2：`text_extracted`（BooleanField）で未処理判定を一本化

- 新フィールド `text_extracted`（default=False, db_index=True）。テキスト層抽出 or OCR が
  完了したら True（結果が空文字列でも「抽出は完了」＝True）。
- 旧 `ocr_attempted` フィールドは**削除**（`text_extracted` に統合）。
- バッチのクエリ：`filter(extracted_text="", ocr_attempted=False, ...)` →
  `filter(text_extracted=False, is_deleted=False)`。カラムの中身に依存しないフラグ判定になり、
  「テキスト層PDFだが本文がほぼ無い」の曖昧さも解消。
- 誤OCR再抽出の運用手順：「`extracted_text` を空に戻す」→「`text_extracted` を False に戻す」。
  → `doc/文書管理システム_残項目_本番リリース手順書.xlsx` 等の運用手順に手順名変更の反映が必要
  （xlsx 直接編集はユーザー指示があれば別途）。

### 案3：`searchable_file`（埋め込み済みPDF恒久保存）→ `ocr_textdata` ＋ 遅延生成

- `searchable_file`（FileField）を**削除**。新フィールド `ocr_textdata`（JSONField, null可,
  editable=False）に OCR 行レイアウト（`core.ocr_layout_services.textdatas_to_json` 形式、
  `[{"page":n,"w":pw,"h":ph,"lines":[[x1,y1,x2,y2,text], ...]}, ...]` の配列形式でキー重複を圧縮）を
  保存する。1000ページのスキャン文書で埋め込み済みPDF数十〜数百MB → 座標JSON 1〜4MB（圧縮後）。
- 保存条件：`settings.OCR_STORE_TEXTDATA=True`（旧 `OCR_EMBED_TEXT_TO_PDF` からリネーム、既定
  False のまま）。**当初実装は privacy_flag の影響なし**（`_should_store_textdata()` は常に True、
  Document/Contract とも設定のみに従う。2026-09-11ユーザー方針。当初「privacy_flag=True は除外」で
  実装したが、その後「まず privacy_flag の影響なしで実装したい」に変更。除外ロジックは
  `Command._should_store_textdata` にコメントアウトで残置＝コメント行1つ有効化で再度除外できる）。
- 遅延生成：`core.searchable_pdf_services.build_searchable_pdf(obj)` ＝
  `pdf_text_embed_services.embed_textdatas_into_pdf(原本PDF, textdatas_from_json(obj.ocr_textdata))`。
  `ocr_textdata` が null なら `SearchablePdfUnavailable`。
- エンドポイント：`documents:searchable_pdf` / `contracts:searchable_pdf`（`<pk>/searchable-pdf/`）＝
  `core.record_views.BaseSearchablePdfView`。`can_download` 権限で保護、`apply_file_response_
  security_headers` 付与、監査ログ（action「文書検索　検索用PDFダウンロード」等）。**まだどの画面
  からもリンクしていない**（旧 searchable_file に読み経路が無かったのと同じ状態。利用者向けUIの
  追加は別途）。
- `core.ocr_layout_services` に `textdatas_to_json` / `textdatas_from_json` を追加。
- `purge_expired_deleted_records` から `searchable_file` 実体削除分岐を撤去（`ocr_textdata` は
  DBカラムのため `obj.delete()` で自動的に消える）。
- `core.storage_paths.build_hierarchical_upload_path` の `searchable=` 引数、
  `document_searchable_upload_path` / `contract_searchable_upload_path` を撤去。

### マイグレーション・設定・テスト

- documents / contracts の `0001_initial.py` を直書き（`extracted_text`・`ocr_attempted`・
  `searchable_file` を削除、`text_extracted`・`ocr_textdata` を追加）。`makemigrations --check`
  クリーン。
- `.env.example` / `.env`（gitignore、ユーザーの意図を汲んで `OCR_STORE_TEXTDATA=True` に更新）/
  `requirements.txt` コメント / `config/settings/base.py` を更新。
- `core.search_services.LIST_DEFERRED_TEXT_FIELDS` → `LIST_DEFERRED_HEAVY_FIELDS`（`extracted_text`
  を外し `ocr_textdata` を追加。一覧クエリで defer）。
- テスト：`ExtractPendingPdfTextCommandTests` / `ExtractPendingPdfTextTextdataTests`（旧
  ...EmbedTests）/ `ShouldStoreTextdataTests`（旧 ShouldEmbedTests）/ `TryImmediateTextLayer
  ExtractionTests` を `extracted_text_normalized`＋`text_extracted`＋`ocr_textdata` ベースに全面
  書き換え。`textdatas_to_json` 往復テスト、`SearchablePdfViewTests`（documents/contracts、権限・
  404・監査）を新設。`searchable_file` の副ファイル削除テストは `ocr_textdata` の同時削除確認に
  差し替え。`manage.py test` 全1002件 PASS。
- 既存 dev DB はフレッシュ `migrate` で反映（squash 運用）。既存の埋め込み済み searchable_file
  実体（`MEDIA_ROOT/documents|contracts/**/searchable/`）は運用側で手動削除。

### 現在の ja_pj 機能との整合（設計討議で確認）

フリーワード全文検索／登録直後の即時反映／スキャン文書OCR／OCR無限リトライ防止／privacy_flag
除外／一覧の defer 最適化／削除時の物理削除／`OCR_ENABLED=False` 耐性 — **すべて維持**。
劣化するのは「テキスト層PDFの登録時点の抽出結果を DB に永続保存する」という内部的な冗長性のみ
（原本ファイル保持＋再抽出でカバー）。`extracted_text` は view/API/テンプレートのどこからも
参照されておらず、検索スニペット・本文表示の機能は存在しないため表示系は無影響。

## メイン画面お知らせ件数と遷移先検索初期表示の部署スコープ不一致を修正（2026-09-11、ユーザー指摘）

### 経緯

ユーザーから「管理者で複数部署閲覧できる場合に部署A(2)＋部署B(1)で3件と表示、遷移先では管理者が
所属する部署Aで絞り込み初期表示が2件」という実地の不整合報告を受け調査。xlsx メイン画面!B40
「・件数をクリックすると『検索・閲覧画面』へ遷移し、**お知らせの条件に沿った**検索結果を
自動的に表示する。」の「お知らせの条件に沿った」＝バッジが数えた母集団と遷移先の表示件数は
一致すべき、という原本の意図に対する実装バグと判断し修正した（Rev1.6でのメイン画面シート自体の
文言変更は無し。ユーザーが引用した「部署による絞り込みがあり全件表示できない場合がある」は
Rev1.6原文ではなく、この不整合に対するユーザー自身の懸念だった）。

### 原因

`core.notice_services.get_notice_counts()`（バッジ集計）と `documents/contracts.forms.SearchForm`
（遷移先の検索フォーム）が、部署スコープについて異なるルールを使っていた：

- バッジ集計：管理者は部署フィルタ無し＝全部署集計。契約書は非管理者でも
  `contract_searchable_department_ids()`（自部署＋閲覧部署範囲＋契約書-部門間閲覧設定）まで含めて集計。
- 検索フォームの初期表示：`core.forms.apply_search_department_default()` が
  xlsx 検索・閲覧・変更!B47,B417「ログインユーザーの部署を自動セットする」に従い、管理者も
  含めて`department`欄に**自部署（visible_department_ids、部門間閲覧設定は含まない）のみ**を
  既定投入していた。

お知らせリンク（`?notice=expired`等、`department`パラメータ無し）でこの既定が働くと、バッジが
数えた範囲より遷移先が狭くなる。非管理者（部門間閲覧設定なし）はバッジ側も同じ
`visible_department_ids`で絞っているため元々一致しており、影響は**管理者、および契約書-部門間
閲覧設定を持つ非管理者に限定**されていた。

### 対応

`core.forms.apply_search_department_default()` に、data に `notice` があり `department` が無い
場合はこの既定セット自体をスキップする分岐を追加（呼び出し元の `documents/contracts.forms.
SearchForm` 側は無改修）。スキップ後は各アプリの `search_services.build_queryset()` が持つ
「選べる部署の上限」フィルタ（documents: 非管理者のみ `visible_department_ids`／contracts:
`contract_searchable_department_ids()`、管理者は常にNone＝無制限）だけが効き、これがバッジ集計と
同じ関数・同じ範囲のため自動的に一致する。`department`が明示指定された場合（`?notice=expired&
department=1`等）は従来通り優先される。

### テスト

- `documents.tests.SearchFormDepartmentAutoSetTests`：お知らせ経由で部署欄が空になること／
  明示指定時は従来通り優先されることを追加。
- `documents.tests.NoticeLinkDepartmentScopeConsistencyTests`（新設）：管理者が自部署以外にも
  期限切れ文書を持つ場合、お知らせ経由の検索結果件数がバッジ集計と一致すること（結合テスト）。
- `contracts.tests.SearchFormDepartmentAutoSetTests`：管理者・契約書-部門間閲覧設定ありの非管理者
  の両方でお知らせ経由の部署欄が空になることを追加。
- `contracts.tests.NoticeLinkDepartmentScopeConsistencyTests`（新設）：管理者、および部門間閲覧
  設定ありの非管理者の両方で、お知らせ経由の検索結果件数がバッジ集計と一致することを確認。
- `manage.py test`（documents/contracts/core、計597件）PASS、既存テストの回帰無し。

---

## 簡易設計指示書 Rev1.6 全行監査（xlsx全行監査フェーズ2、2026-09-16、ユーザー依頼）

原本改訂を伴わない、リリース前総仕上げとしての実装漏れ網羅監査
（`REVISION_TO_RELEASE_WORKFLOW.md`フェーズ2手順）。フェーズ0〜1（差分反映）が「変更点」だけを
追うのに対し、xlsxシート全体を実装と1行ずつ突き合わせて改訂の有無に関わらない実装漏れを洗い出す。

### 監査方法

1. openpyxlで全16シートのセルテキストを抽出。画像埋め込みセル（画面モック・権限マトリクス等）は
   `ws._images`の生画像だけでなく、`xl/drawings/drawingN.xml`をパースして`xdr:pic`の`srcRect`
   クロップと`xdr:sp`の塗りつぶし矩形を実際にz-order順で合成レンダリングしてから読む専用スクリプト
   （`extract_xlsx.py`、PIL使用）を新規作成。既知の誤読事例（設定メニューシート「分類管理　一覧」
   行、本来○/○/―だが生画像だけでは○/―/―に見える）で正しく合成できることを検証済み。
2. 表紙・目次・(ひな形)を除く13シート（ログイン画面・メイン画面・設定メニューは1グループに統合）
   を、mainセッションで一括抽出したファイル（cells.txt＋drawing.png）を渡した上で、11本の
   background agentへシート単位で並行調査を依頼（結果報告のみ、修正はしない）。
3. 各agentの報告を「確度の高い実装漏れ」「判断が必要な項目」「低優先度」の3群に分類して
   `xlsx_audit_Rev1.6.txt`（プロジェクトルート直下）に集約。

### 結果

**確度の高い実装漏れは全13シートで0件**。既に複数回の原本フィデリティ監査・規約準拠監査・
コードレビューを経ているシートが大半で、新規の高確度な乖離は検出されなかった。

判断が必要な項目14件をAskUserQuestionでユーザーに1件ずつ確認：

- 13件は「現状維持」または「見送り・対応不要」で確定。
- うち1件（分類管理シート担当agentが報告した「権限管理B201/B234の書類管理区分別制限が未解決」）
  は、調査の結果**過検出**と判明：`HTML_REIMPL_CHECKLIST_ARCHIVE2.md`「要再確認（赤字）箇所
  リスト」の該当項目（No.7/No.15）は、同リストの2026-08-19追記で「Rev1.1改訂により権限管理の
  個別フラグ方式が廃止されシステム権限プルダウン1段階に統一されたため対象を失った」と既に
  陳腐化が明記されていた。分類管理シート担当agentがこの解消済みの追記を見落として「未解決」と
  誤認したもの。現在のRev1.6権限管理シートには「書類管理区分」の文言自体が存在しないことも
  再確認済み。実装対応なし。
- 実装対応が必要だったのは**1件のみ**（No.7、カテゴリー管理シート担当agent発見）：

### 対応した1件：分類(Group)論理削除時の配下カテゴリー保護

**問題**：`masters.views.GroupDeleteView.blocking_count()`は、その分類に直接紐づく文書・契約書
件数（doc_count/contract_count）だけを見て削除可否を判定しており、配下の「カテゴリー」
（`masters.Category`）が有効（`is_deleted=False`）のまま残っているかは考慮していなかった。
分類配下の各カテゴリーの文書件数が個別に0件であれば、分類自体を論理削除できてしまう。その状態で
当該カテゴリーの編集画面（`CategoryEditView`）を開くと、`masters.forms.CategoryForm.__init__`の
「分類」プルダウンのqueryset（`is_deleted=False`限定）から現在参照中の分類が選択肢から消え、
Django `ModelChoiceField`はbound valueがqueryset内に無い場合どの`<option>`にも`selected`を
付けずにレンダリングするため、ブラウザ上は先頭の別の分類が見た目上選択された状態になる。利用者が
「分類」欄を意図的に触らずに他の項目だけ変更して更新すると、カテゴリーの「分類」が意図に反して
別の分類へサイレントに変わってしまうリスクがあった。

xlsx/原本HTMLに直接の記載が無い業務ロジックのため、CLAUDE.md「xlsx/HTMLに仕様記載の無い危険な
業務ロジックは無断で憶測実装しない」方針に従い、実装前にユーザーへ対処方針を確認（(a)分類削除を
ブロック／(b)カテゴリー編集時に削除済み分類も選択肢に残す／(c)現状維持の3案を提示）。
ユーザーは(a)案（分類削除をブロック）を選択。

**実装**：`GroupDeleteView.blocking_count()`に、配下の有効なカテゴリー件数
（`_group_queryset_with_counts()`にannotateした`active_category_count`）を加算する分岐を追加。
既存の「紐づくデータが存在するため削除できません」という汎用メッセージ・ブロック条件
（`count > 0`）の仕組みをそのまま流用でき、URLの変更は不要。

**追記（2026-09-16 フェーズ4品質チェックで発見・同日修正）**：初版実装では一覧
（`class_list.html`）の「削除」ボタンのdisabled判定がdoc_count/contract_countのみを見ており、
上記のカテゴリー起因のブロックに追随していなかった（「テンプレートの変更は不要」との当初判断は
誤りだった）。文書0件・配下に有効なカテゴリーが残っている分類は、一覧では「削除」が活性表示の
まま確認画面まで進め、POST時に初めてブロックされる不整合があった。`_group_queryset_with_counts()`
に`active_category_count`をannotateし、`class_list.html`の非活性条件へ追加、
`GroupDeleteView.blocking_count()`側もこのannotate値を再利用する形に修正（個別クエリの重複を解消）。
あわせて`core.master_views.BaseScopedMasterDeleteView.post`の警告ログ文言
「文書件数が0件でない…」も、文書件数以外が原因のブロックを誤解させるため
「紐づくデータが残っている…」に変更。一覧のdisabled表示を検証するテストが従来一切無かったため
`masters/tests.py`に`test_class_list_delete_button_disabled_reflects_active_category_block`を追加。

**テスト**：`masters/tests.py`に以下を追加・修正。
- `test_group_with_active_category_cannot_be_deleted_even_without_documents`（新規）：文書0件でも
  有効なカテゴリーが紐づいていれば削除できないことを確認。
- `test_group_with_only_deleted_category_can_be_deleted`（新規）：配下カテゴリーが既に論理削除済み
  なら削除できることを確認（対比）。
- `test_trashed_document_is_excluded_from_count_and_delete_block`・
  `test_trashed_contract_is_excluded_from_count_and_delete_block`（既存）：setUpで分類に有効な
  カテゴリーが紐づいたまま「文書0件なら削除できる」ことを検証していたため、新しいブロック条件と
  衝突しないよう、削除成功を確認する直前でそのカテゴリーも論理削除するよう修正
  （このテストの検証対象＝文書/契約書件数のみを切り分けるため）。

`manage.py test masters`134件PASS。

### 未対応（今回は見送り）の主な項目

- CSV取込の管理者0人ガード抵触時、中止範囲は行単位のまま（ファイル全体中止には変更しない）。
- 部署新規登録画面での「本支所のみ」部署（部課コード・部課名空欄）登録は引き続きWeb画面からは
  不可（CSV取込・初期データ投入経由のみ）。
- 部署統合・分割対象ポップアップは部課コード"99"（退職）を引き続き除外しない。
- 操作履歴ログのAuditLog.department_name表示はプレフィックスなしのまま（モックのサンプル行が
  古いと判断）。
- 保管画面の「年」プルダウンは未来年+1年を許容する現行仕様を維持（原本の静的な窓より1年広い）。
- 契約金額欄の下限バリデーション欠如は`review_pending.txt`での追跡を継続（対応せず）。

いずれも詳細な検討根拠は`xlsx_audit_Rev1.6.txt`（プロジェクトルート直下、gitで追跡）参照。

## アプリ全体CSP・MEDIA別オリジン配信の再検討（2026-09-18、ユーザー依頼）

H-3対応（2026-08-28、`docs/HTML_REIMPL_CHECKLIST_ARCHIVE3.md`参照）で「中期対応」として見送っていた
2項目を`review_pending.txt`の未確認事項棚卸しの一環で再検討した。

### MEDIA別オリジン配信 → 対応不要で確定

`config/urls.py`を確認したところ、`static(settings.MEDIA_URL, ...)`のようなMEDIA直配信の仕組み自体が
存在しない。文書・契約書ファイルへのアクセスは全て認証・権限チェック付きのDjangoビュー
（`core/record_views.py BaseFileServeView`等）経由でのみ行われ、そこで既にH-3対応により：
- 安全な種別（PDF・ラスター画像）以外は`resolve_as_attachment()`で強制的に`attachment`扱い（inline表示させない）
- 全レスポンスに`apply_file_response_security_headers()`で`X-Content-Type-Options: nosniff`＋
  `Content-Security-Policy: script-src 'none'; object-src 'none'`を付与
- アップロード側で`core/upload_validation.py BLOCKED_UPLOAD_EXTENSIONS`によりHTML/SVG/JS等の
  危険拡張子を拒否

という多層防御が入っている。「MEDIA別オリジン配信」が本来防ぎたかった「静的ファイルサーバーが
認証なしでアップロードファイルをそのまま生配信し、悪意あるファイルが同一オリジンで実行される」
というシナリオ自体が、現状のアーキテクチャ（生配信の経路が無く、全経路がハードニング済み
ビュー経由）で構造的に発生し得ないと判断し、対応不要で確定した。

**前提条件（再検討が必要になる場合）**：将来、性能上の理由でnginx等がMEDIA_ROOTを直接静的配信する
ようになった場合はこの判断を見直すこと。

### アプリ全体CSP → 中期対応のまま維持、リリース後の技術的負債として明示

テンプレート全体を`grep`で調べたところ、`onclick`だけで194件、`onchange`/`onkeydown`/`oninput`等を
含めると約250件のインラインイベントハンドラが40テンプレートに分散している（原本HTMLの構造を
そのまま引き継いだもの）。厳格なCSP（`script-src`に`unsafe-inline`を含めない）を導入するには
この250件全てを`addEventListener`方式（`common.js`のイベント委譲パターン等）へ移行する必要があり、
リリース前に着手するには規模・リグレッションリスクが大きすぎると判断した。

一方、実際に見つかっていたXSS脆弱性（H-1/H-2：検索結果詳細・行クリックプレビューの格納型XSS）は
既に根本原因（`innerHTML`直代入）を`escapeHtml`／DOM API化で修正済み（2026-09-04反映、上記参照）。
CSPはその上に重ねる多層防御であり、「今アプリ全体CSPが無いと防げない具体的な脆弱性」が
残っているわけではないため、リリースをブロックする理由はないと判断した。

**結論**：中期対応のまま維持するが、「リリース後の技術的負債」として明示的にスケジュール化する
（インラインハンドラのイベントリスナー移行は独立した別プロジェクトとして扱う）。コード変更なし。

## 保管画面１：PDF以外の選択時にクライアント側でalertエラー（2026-09-18、ユーザー依頼）

原本HTML/xlsxは保管画面１（`templates/documents/storage1.html`／`templates/contracts/storage1.html`）の
ファイル選択にPDF以外の制限を設けていない（サーバー側も`core/upload_validation.py`の拒否リスト
方式で、HTML/SVG/JS等の能動的コンテンツのみ拒否し、Office文書・画像・テキスト・圧縮ファイル等は
通常通り許容する設計を維持している）。

ユーザーから「原本にはないが」の前置き無しの依頼だったため、適用範囲をユーザーに確認：
- 対象範囲：documents/contracts両方の保管画面１
- 対応レイヤー：クライアント側（`<input type="file">`のchangeイベント・ドラッグ＆ドロップの
  dropイベント）のalertのみ。サーバー側の登録処理・`core/upload_validation.py`の拒否リストは
  変更しない（画像・Office文書等の既存の許容範囲はサーバー側では維持されたまま）。

両テンプレートの`enforcePdfOnlySelection()`で、拡張子が`.pdf`（大文字小文字を問わない）以外の
ファイルを検出したらalertで案内し、`DataTransfer`経由でPDFファイルだけを`file-input`へ詰め直す
（PDF以外を含めたまま送信ボタンを押しても、除外済みの状態で通常のチャンク分割判定へ進む）。
サーバー側は変更していないため、開発者ツール等でファイル種別チェックを回避してPOSTした場合は
従来通り画像・Office文書等も登録できる（意図的な非対称性。ユーザーが「クライアント側のみで良い」
と明示的に選択したため）。
