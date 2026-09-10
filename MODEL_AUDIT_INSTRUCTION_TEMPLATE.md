# モデル定義 妥当性監査 指示テンプレート

`models.py` の定義が「原本HTML／xlsx簡易設計指示書」「Django設計上の妥当性」「コーディング規約」
「アプリ間整合」「マイグレーション整合」に照らして妥当かを、Claude Code に監査させるための指示雛形。

## 運用ルール（フィデリティ監査テンプレートと共通）

- **軸を混ぜない**。1回の指示で扱う軸は最大2つ。
- **範囲を区切る**。全8アプリを一度に見ない。下記の3グループ単位で回す。
- **今回は指摘出しのみ**。修正は一覧を確定してから別指示（フェーズ2）で行う。
- 出力形式は必ず「`ファイル:行` / 現状 / 原本または規約が求める姿 / 深刻度（高・中・低） / 根拠」の表。
- 監査対象は `models.py` を主とし、関連する `validators.py` / `forms.py` / `services.py` /
  `migrations/0001_initial.py` も突き合わせ対象に含める。

## 監査の5軸

| 軸 | 見る内容 |
|---|---|
| **A. 原本フィデリティ** | 各フィールドが原本HTML（`../../HTML/html6/index.html`＋`style.css`）の該当画面の入力項目、および簡易設計指示書 `../../HTML/文書管理システム_簡易設計指示書_Rev1_6.xlsx` の該当シートと一致するか。項目の過不足・データ型・最大長・必須/任意・選択肢（choices）の値と表示順・初期値。xlsxセル文言のdiffではなく、実際にレンダリングされる原本マークアップを基準にする。 |
| **B. Django設計の妥当性** | フィールド型の選択（CharField/TextField、DecimalFieldのmax_digits/decimal_places、DateField/DateTimeField、BooleanFieldのnull禁止、choices vs 別テーブル）、`null`/`blank`の組み合わせの整合、`on_delete`の妥当性（CASCADE/PROTECT/SET_NULL）、`related_name`の命名と衝突、`unique`/`Meta.constraints`（UniqueConstraint・CheckConstraint）、`db_index`/`Meta.indexes`（GinIndex含む）、`default`の型と callable、`Meta.ordering`、`verbose_name`/`verbose_name_plural`。 |
| **C. 規約準拠** | `verbose_name`/`help_text`/`ValidationError`メッセージ/docstringが日本語で統一されているか。クラス・非自明メソッドにdocstringがあるか。業務ロジック（保存満了日計算、権限判定等）がモデルの`save()`/`clean()`に漏れておらず`services.py`へ分離されているか。設定値のハードコードがなく`settings`経由か。`logger`の用意。 |
| **D. アプリ間整合** | 8アプリ間のFK方向・循環import、`documents`と`contracts`の並行構成の非対称（片方だけにあるフィールド・制約・バリデータ・インデックス）、`audit.AuditLog`の非正規化スナップショット項目が監査対象モデルの現行フィールドに追随しているか、`masters`の選択肢マスタと参照側の`on_delete`整合、`permissions.PermissionProfile`のフラグと連動先の有無。 |
| **E. マイグレーション整合** | モデル定義と`migrations/0001_initial.py`（本番リリース前はsquash運用中＝新規migrationを作らず0001を直接書き換え）が一致するか。`makemigrations --check --dry-run`で差分が出ないか。制約・インデックス・choices・default・db_collationの反映漏れ。 |

## 範囲グループ（この単位で回す）

1. **文書・契約書**: `documents` / `contracts`（並行構成のズレを対で確認）
2. **マスタ系**: `accounts` / `organizations` / `masters`
3. **権限・監査・基盤**: `permissions` / `audit` / `core`

---

## フェーズ1：指摘出し（範囲ごとに1回ずつ実行）

### 1-1. 文書・契約書

```
models定義の妥当性監査（フェーズ1・指摘出しのみ）。

範囲：documents と contracts の2アプリの models.py（関連する validators.py /
forms.py / services.py / migrations/0001_initial.py も突き合わせ対象に含める）。
軸：A（原本フィデリティ）と B（Django設計の妥当性）の2つのみ。

A：各モデルの各フィールドを、原本HTML ../../HTML/html6/index.html の
文書（検索・保管step1〜／編集／保管画面2のファイルごとメタデータ）および
契約書の該当画面の入力項目、ならびに簡易設計指示書
../../HTML/文書管理システム_簡易設計指示書_Rev1_6.xlsx の該当シートと
1項目ずつ突き合わせる。過不足・データ型・最大長・必須/任意・choices の値と表示順・
初期値の不一致を洗い出す。xlsx のセル文言 diff ではなく、実際にレンダリングされる
原本マークアップと JS 挙動を基準にすること。

B：フィールド型の選択（CharField/TextField、DecimalField の桁指定、日付型、
BooleanField の null）、null/blank の組み合わせ、on_delete、related_name、
unique/UniqueConstraint/CheckConstraint、db_index/Meta.indexes（GinIndex 含む）、
default、Meta.ordering の妥当性を確認する。特に documents と contracts で
並行しているべき箇所の非対称（片方だけにある制約・バリデータ・インデックス・
フィールド）を必ず指摘する。

出力：以下の列の表のみ。
| ファイル:行 | 現状 | 原本／規約が求める姿 | 深刻度(高中低) | 根拠(原本の画面名・xlsxシートセル or 規約項目) |

今回は修正しない。一覧を確認してから別途フェーズ2で指示する。
不明点・原本にもxlsxにも記載が無く判断できない項目は「要ユーザー確認」として別掲。
```

### 1-2. マスタ系

```
models定義の妥当性監査（フェーズ1・指摘出しのみ）。

範囲：accounts / organizations / masters の3アプリの models.py（関連ファイルも
突き合わせ対象）。
軸：A（原本フィデリティ）と B（Django設計の妥当性）の2つのみ。

A：Employee / Rank / Position / Department / MenuItemSetting /
DepartmentViewScope / Group / Category / RetentionPeriod / SystemSetting の
各フィールドを、原本HTMLの職員マスタ・部署管理・分類管理・カテゴリー管理・
保存期間設定・システム設定の各画面、および簡易設計指示書xlsxの該当シートと
1項目ずつ突き合わせる。過不足・型・最大長・必須任意・choices・初期値の不一致。
SystemSetting は実使用が session_idle_timeout_minutes のみで他は settings へ
移行済みという現状（CLAUDE.md）と定義が乖離していないかも見る。

B：軸Bの標準チェック（型選択・null/blank・on_delete・related_name・
unique/constraints・index・default・ordering）。特にマスタの選択肢が
参照される側（documents/contracts 等）からの on_delete が PROTECT 相当で
保護されているか。employee_no ログイン・Argon2 前提の accounts の整合。

出力形式・修正しない旨・要ユーザー確認の別掲は 1-1 と同じ。
```

### 1-3. 権限・監査・基盤

```
models定義の妥当性監査（フェーズ1・指摘出しのみ）。

範囲：permissions / audit / core の3アプリの models.py（関連ファイルも対象）。
軸：B（Django設計の妥当性）と D（アプリ間整合）の2つのみ。
※この範囲は原本HTMLに対応画面が薄いため A は対象外。規約 C は次サイクルで。

B：PermissionProfile（システム権限3段階＋電子決裁3フラグ）、AuditLog
（非正規化スナップショット）、SystemSetting 等の型選択・null/blank・on_delete・
constraints・index・default・ordering の妥当性。AuditLog が意図的に
非正規化（FK ではなく値コピー）である設計を壊していないか。

D：
- audit.AuditLog のスナップショット項目が、監査対象（documents/contracts/
  accounts/permissions/organizations/masters）の現行フィールドに追随しているか。
  記録漏れ・廃止フィールドの残骸。
- permissions の電子決裁3フラグ（eapproval_view_setting /
  eapproval_doc_name_manage / eapproval_retention）が「保持のみ・連動先なし」
  というCLAUDE.md記載の保留状態と一致しているか（勝手に連動ロジックが
  入っていないか、逆に将来用コメントが消えていないか）。
- 8アプリ間の FK 方向・循環 import・related_name 衝突。

出力形式・修正しない旨・要ユーザー確認の別掲は 1-1 と同じ。
```

### 1-4. 規約準拠（全アプリ横断・軸Cのみ）

```
models定義の妥当性監査（フェーズ1・指摘出しのみ）。

範囲：全8アプリの models.py。
軸：C（規約準拠）のみ。

チェック項目：
- verbose_name / help_text / ValidationError等のメッセージ / docstring が
  すべて日本語で統一されているか（英語・未設定の洗い出し）。
- クラスと非自明メソッドに docstring があるか。「なぜ」を説明するコメントが
  非自明な設計判断（非正規化・choices固定値・並行構成の意図的差異等）に
  付いているか。
- 業務ロジックがモデルの save()/clean() に漏れておらず services.py へ
  分離されているか（特に保存満了日の再計算、部署スコープ判定、権限判定）。
- 設定値のハードコードがなく settings 経由か（お知らせしきい値・契約書保存
  年数・「永年」実年数・各種保存期間）。
- 各モデル定義ファイルに logger = logging.getLogger(__name__) 相当があるか
  （モデル層で不要なら不要と判断してよいが、その根拠）。

出力形式・修正しない旨は 1-1 と同じ。
```

### 1-5. マイグレーション整合（軸Eのみ）

```
models定義とマイグレーションの整合監査（フェーズ1・指摘出しのみ）。

範囲：全8アプリの models.py と各 migrations/0001_initial.py。
軸：E（マイグレーション整合）のみ。

- venv の python フルパスで python manage.py makemigrations --check --dry-run を
  実行（カレントは ja_system/ja_pj）。差分が出るモデル・フィールドを列挙。
- 0001_initial.py に、制約（UniqueConstraint/CheckConstraint）・インデックス
  （GinIndex 含む）・choices・default・db_collation・on_delete が
  モデル定義どおり反映されているか目視で突き合わせる。
- 本番リリース前の squash 運用中のため、0002 以降の新規 migration が
  生まれていないか、0001 直書きが漏れなく行われているかを確認。

出力：| 対象 | --check の差分内容 | 0001での現状 | あるべき姿 | 深刻度 |
今回は修正しない。
```

---

## フェーズ2：修正（フェーズ1の一覧確定後）

```
フェーズ1で確定した指摘一覧の「深刻度：高」から順に対応する。

- 1件ずつ「対象ファイル:行 / 変更内容 / 理由 / 影響範囲（マイグレーション要否・
  既存データへの影響・テスト追加要否）」を提示 → こちらの承認 → 適用。
- モデル変更を伴う場合、新規 migration は作らず 0001_initial.py を直接書き換える
  （本番リリース前 squash 運用）。書き換え後 makemigrations --check がクリーンに
  なることを確認。
- 原本にはない設計改善（制約追加等）を提案する場合は、その旨を明示し、
  採否をこちらに委ねる。勝手に業務ロジックを憶測実装しない。
- 対応した項目は HTML_REIMPL_CHECKLIST.md の該当箇所、および必要なら
  doc/文書管理システム_実装と原本の差異一覧.xlsx を更新。
- 新規・変更したバリデーションや制約には tests.py にユニットテストを追加。
- コミットはこちらが「コミットして」と言うまで行わない。
```

---

## 補足

- xlsx のセル diff は「何が変わったか」の手がかりに過ぎない。実装要否・粒度は必ず
  原本HTML（実際にレンダリングされるマークアップ・JS）と突き合わせて判断させる。
- 原本のJS自体がモックとして壊れている箇所（存在しないDOM参照・コピペ二重定義）は
  再現しない、という既存方針をフェーズ2でも適用。
- 電子決裁機能全般は恒久的にスコープ外。関連フラグは「保持のみ」で正しい。
