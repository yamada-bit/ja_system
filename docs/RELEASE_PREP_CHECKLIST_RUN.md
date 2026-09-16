# 本番リリース前チェック：改善版 指示シーケンス

（2026-09-16注記：本ファイルはP1以降の実行当時の指示文をそのまま記録した過去ログのため、
「プロジェクトルートに保存して」という指示文言はそのまま残している。実際の置き場所は
2026-09-16以降 `reviews/`（review_*.txt・release_baseline.txt・xlsx_audit_*.txt）と
`docs/`（*.mdの文書類）に変更済み。次回以降このテンプレートを流用する場合は保存先を
読み替えること。詳細はdocs/RELEASE_QUALITY_WORKFLOW.md ⑥参照。）

前回実行した指示列（アプリ群ごとに code-review → 規約準拠 → テストカバレッジ、最後に
security）をベースに、壁打ちで洗い出した穴を埋めた版。docs/RELEASE_QUALITY_WORKFLOW.md の
軸分離・レポート/修正分離・`/clear` の挟み方の原則はそのまま踏襲する。

追加・変更した点（前回との差分）：
- **P0 ベースラインを「作業ツリーをクリーンにしてから」取得し、環境情報も記録する**。
- **各修正ループで `core/` `config/settings/` `base.html` `common.js` を触った回はその回だけ全体テスト**。
- **テストカバレッジ棚卸しに `coverage.py` の実測を併用**（モデルの目視推測だけに頼らない）。
- **security の既存コード監査をエンドポイント単位で明示列挙**（diff限定の `/security-review` を補う）。
- **P9 最終ゲートを新設**：全体テスト×ベースライン照合／`makemigrations --check`／`check` ／
  `check --deploy`／差分全体レビュー／触った画面のフィデリティ・スポット再確認／実アプリのスモークテスト。

共通の前提：
- venv の python は `C:\Users\yamad\Claude\JA\ja_system\venv\Scripts\python.exe`。
- テスト実行の cwd は `C:\Users\yamad\Claude\JA\ja_system\ja_pj`。
- レポートは `reviews/` 直下に `review_*.txt` で保存し、git 追跡する。
- 「レポート生成」と「修正」の間で必ず `/clear`。修正フェーズ内は 1 件ずつ・同一セッション。
- 各コミットは日本語メッセージ＋末尾 `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`。

---

## P0. ベースライン確認（グリーンの固定）

```
/clear
リリース前チェックのベースラインを取りたい。

1. まず git status を確認して、作業ツリーに未コミット変更があれば内容を一覧にして、
   コミットするか stash するかを聞いて。クリーンな状態にしてから先へ進んで。
2. venv の python（C:\Users\yamad\Claude\JA\ja_system\venv\Scripts\python.exe）を使い、
   cwd を ja_system/ja_pj にして python manage.py test --verbosity=2 を全体実行して。
3. 失敗・エラーがあれば一覧化して。既存の失敗はベースラインとして把握したいだけなので修正はしない。
4. 併せて環境情報を記録して：python --version / Django のバージョン /
   python -m pip freeze の出力 / git HEAD のハッシュとブランチ /
   python manage.py makemigrations --check --dry-run の結果。
5. 上記すべてを reviews/release_baseline.txt として保存して。
   実行日時・実行コマンド・実行環境・結果サマリ・失敗一覧・環境情報の順で。
```

---

## P1〜P4. アプリ群ごとの品質チェック（4 グループ）

対象グループは前回同様：
- P1: `documents/` `contracts/`
- P2: `permissions/` `accounts/`
- P3: `organizations/` `masters/`
- P4: `audit/` `core/`

各グループで **(a) コードレビュー → (b) 修正 → (c) 規約準拠監査 → (d) 修正 →
(e) テストカバレッジ棚卸し → (f) 追加** を、それぞれ `/clear` で区切って実行する。
以下は P1 のテンプレート。P2〜P4 はアプリ名・ファイル名・テスト対象を読み替える
（P4 のみ後述の「core 変更時の全体テスト」ルールが特に効く）。

### P1-a. コードレビュー（レポートのみ）

```
/clear
/code-review high documents/ contracts/
対象は documents/ と contracts/ アプリ全体。
・正しさのバグと、再利用性・単純化・効率性の指摘を分けて出して。
・CLAUDE.md のコーディング規約（CBV のみ／verbose_name・help_text・エラー文言・docstring は日本語／
  設定は base.py に集約し django-environ 経由／Argon2 優先／監査イベントは audit アプリ経由／
  共通処理は core に集約／コメントは「なぜ」／logger 整備・logger.warning／例外処理の完成・bare except 禁止／
  ページネーションは Django Paginator／未実装 UI は disabled + title）との整合性も確認対象に含めて。
・documents と contracts は並行構成なので、同種の指摘が両方にある場合は 1 件にまとめて
  （両方のファイル名を併記して）指摘して。
・修正はまだせず、指摘一覧と優先度（高/中/低）だけ出して。
・結果を review_code_documents_contracts.txt としてプロジェクトルートに保存して。
  各指摘に通し番号・対象ファイル・優先度・根拠を含めて。
```

### P1-b. コードレビュー指摘の修正

```
/clear
review_code_documents_contracts.txt を読んで。
優先度「高」「中」の指摘を通し番号順に 1 件ずつ修正して。
1 件直すごとに venv の python（cwd=ja_system/ja_pj）で
python manage.py test documents contracts を実行し、パスを確認してから次へ進んで。
ただしその 1 件で core/ ・ config/settings/ ・ templates/base.html ・ static/js/common.js を
変更した場合は、その回だけ python manage.py test 全体も実行して回帰がないことを確認して。
対応済みの指摘は review_code_documents_contracts.txt の該当行に「対応済み」と追記。
優先度「低」は修正せず、該当行に「見送り／理由: ...」を追記するだけ。
全件終わったら、ここまでの修正をコミットして（日本語メッセージ＋Co-Authored-By 行）。
```

### P1-c. CLAUDE.md 規約準拠監査（レポートのみ）

```
/clear
documents/ と contracts/ アプリの CLAUDE.md 規約準拠監査を実行して。
コーディング規約の各項目（CBV のみ／日本語 verbose_name・help_text・エラー文言・docstring／
設定は base.py 集約・django-environ 経由・.env.example 追記／Argon2 優先／監査イベントは audit 経由／
共通処理は core 集約／コメントは「なぜ」・非自明メソッドに docstring／logger 整備・logger.warning／
例外処理の完成・具体例外型の捕捉・logger.exception・bare except 禁止／ページネーションは Django Paginator／
未実装 UI は disabled + title）に照らして逸脱を洗い出して。
レポートのみで修正はしないで。各指摘に通し番号・対象ファイル・優先度（高/中/低）・根拠を付けて。
review_rule_doc_contract.txt としてプロジェクトルートに保存して。
```

### P1-d. 規約準拠監査の修正

```
/clear
review_rule_doc_contract.txt を読んで。
優先度「高」「中」の指摘を通し番号順に 1 件ずつ修正して。
1 件ごとに venv の python で python manage.py test documents contracts（cwd=ja_system/ja_pj）を
実行し確認してから次へ。その 1 件で core/ ・ config/settings/ ・ base.html ・ common.js を
変更した場合はその回だけ全体テストも実行して。
対応済み項目には「対応済み」を追記。優先度「低」は修正せず「見送り／理由: ...」を追記するだけ。
全件終わったらここまでをコミットして（日本語メッセージ＋Co-Authored-By 行）。
```

### P1-e. テストカバレッジ棚卸し（レポートのみ＋実測併用）

```
/clear
documents/ と contracts/ アプリのテストカバレッジ棚卸しを実行して。

1. まず coverage で実測して。venv の python（cwd=ja_system/ja_pj）で:
   python -m coverage run manage.py test documents contracts
   python -m coverage report --show-missing --include="*/documents/*,*/contracts/*"
   （coverage 未インストールなら python -m pip install coverage してから）
   未到達行を対象ファイルごとに拾って。
2. その実測を踏まえ、tests.py の既存カバレッジと、View / api.py / services / validators /
   forms / 削除系のうち未カバーの分岐（権限拒否・異常系・境界値・並行構成の非対称な挙動）を
   洗い出して。「実測で未到達」と「到達はしているが分岐条件を検証していない」を区別して。
3. レポートのみで追加はしないで。各不足テストに通し番号・対象・優先度（高/中/低）・理由を付けて。
   review_test_doc_contract.txt としてプロジェクトルートに保存して。
```

### P1-f. 不足テストの追加

```
/clear
review_test_doc_contract.txt を読んで。
優先度「高」「中」の不足テストを通し番号順に 1 件ずつ追加して。
1 件追加ごとに venv の python で python manage.py test documents contracts（cwd=ja_system/ja_pj）を
実行し確認してから次へ。
追加したものには「追加済み」を追記。優先度「低」は追加せず「見送り／理由: ...」を追記するだけ。
全件終わったらここまでをコミットして（日本語メッセージ＋Co-Authored-By 行）。
```

> **P4（audit/core）の注意**：core は共通基盤なので、b/d/f の各修正・追加で core を触った回は
> 必ず python manage.py test 全体を実行する。P4-a のレビュー指示には
> 「他アプリから使われる基底クラス・サービス関数の後方互換に影響する指摘は明記して」を追加する。

---

## P5. セキュリティレビュー（diff）

```
/clear
現在のブランチ差分を対象に /security-review でレビューして。
検出された脆弱性を優先度別（高/中/低）に分類し、コードの修正は行わず、
レポートのみを review_security.txt としてプロジェクトルートに保存して
（通し番号・対象ファイル・優先度・根拠付き）。
```

## P6. セキュリティレビュー（既存コード・エンドポイント単位）

```
/clear
/security-review は主にブランチ差分を見るので、既存コード全体を対象にした監査を別途実行して。
documents/ contracts/ permissions/ organizations/ masters/ accounts/ の全 View・api.py・
storage_paths.py・validators.py を対象に、次を 1 エンドポイント／1 関数ずつ確認して。
チェックリストのどの項目をどのエンドポイントで確認したか、表形式で残して。

【認可・IDOR】
・削除／編集／ダウンロード／完全削除／権限変更など副作用のある全エンドポイントで、
  クライアント側のボタン非表示（disabled / style.display / URL 生成の None 化）だけに頼らず、
  対応する View.post / API 側でサーバーサイドの権限チェック（部署スコープ含む）が実装され、
  URL 直打ち・pk 改ざんでバイパスできないか。
・detail / download 系の get_queryset が閲覧部署範囲・is_deleted で確実に絞られているか。
・他部署リソースへの直打ちアクセス試行が audit.services.log_denied_cross_department_access
  経由で記録されているか（masters は管理者用画面のため logger.warning のみで可）。

【AJAX / api.py】
・api.py の JsonResponse を返す全エンドポイントに、ログイン必須・権限チェック・
  （POST なら）CSRF 保護が効いているか。GET で副作用を起こしていないか。

【機微情報】
・パスワード等がハッシュ化され、画面表示はマスク（●●●●●●）になっているか
  （ログイン画面・職員マスタ詳細/編集・その他設定のパスワード変更）。
・個人情報が URL クエリパラメータに乗っていないか。

【外部境界の例外処理】
・ファイルアップロード・チャンク結合・OCR（Google Cloud Vision）・PDF テキスト抽出
  （pdfplumber / pdf2image）で、bare except でなく具体的な例外型を try/except で捕捉し、
  logger.exception で記録した上で利用者にわかるエラー応答を返しているか。
・OCR / 外部呼び出しにタイムアウトが設定され、失敗時にバッチ全体が止まらないか。

【アップロード・パス】
・storage_paths.py の保存パス生成にパストラバーサル（.. やスラッシュ混入）の余地がないか。
・アップロードのファイル拡張子・MIME・サイズのバリデーションがサーバー側にあるか。

【テンプレート】
・|safe / autoescape off / mark_safe の使用箇所が、ユーザー入力を含まないと確認できるか。

逸脱を優先度（高/中/低）付きで review_security.txt の末尾に追記して。修正はしないで。
```

## P7. セキュリティ指摘の修正

```
/clear
review_security.txt を読んで。
優先度「高」「中」の指摘を通し番号順に 1 件ずつ修正して。
1 件ごとに、関連アプリの python manage.py test（venv の python、cwd=ja_system/ja_pj）を
実行して確認してから次へ。core / settings を触った回は全体テストも実行して。
対応済みには「対応済み」を追記。優先度「低」は修正せず「見送り／理由: ...」を追記するだけ。
全件終わったら python manage.py test 全体を実行し、問題がないことを確認してから報告して。
最後にここまでをコミットして（日本語メッセージ＋Co-Authored-By 行）。
```

---

## P8. 低優先度・見送り項目の棚卸し

```
/clear
プロジェクトルートの review_code_*.txt / review_rule_*.txt / review_test_*.txt /
review_security.txt を全部読んで、「見送り」と記録した低優先度の指摘・不足テストを一覧にして。
各項目に「出典ファイル・通し番号・内容・見送り理由」を付けて。
軸ごとの見直し方針：
- セキュリティ：本番リリース前には必ず再検討（「今すぐ悪用されにくい」≠「放置していい」）。
- コードレビュー（再利用性・単純化・効率性）：別件で該当ファイルを触るときについで直す程度で可。
- 規約準拠：新規コードが違反を模倣する温床になるため件数が少ないうちに解消。
- テストカバレッジ：分類が「レアケースだから低」か「権限分岐・異常系だが見積もりが甘くて低」かを再確認。
一覧を見ながら「今回は見送り」か「直す」かを 1 件ずつ一緒に確認したい。まだファイルには保存しないで。
```

（判断後）

```
確定した「見送り」項目を、既存の review_pending.txt に重複を除いて追記して
（既存の No. 採番を引き継ぐ。上書きはしない）。
「直す」と決めた項目は、review_pending.txt の先頭に「未対応（要対応）」セクションを作ってそこに書いて。
追記後、見送り件数・未対応件数と、特に見直した方がよいと思うものがあれば所感を添えて。
```

### P8-b. 「直す」と決めた項目の修正 ※「直す」項目が 1 件以上あるときのみ

P9 の前に実行する（P9 の全体テスト・差分全体レビューがこの修正までカバーするように）。
「直す」項目がゼロなら P8-b はスキップして P9 へ。

```
/clear
review_pending.txt の先頭「未対応（要対応）」セクションを読んで。
そこに並んでいる項目を通し番号順に 1 件ずつ修正して。

1 件ごとに：
- その項目の「出典」に書かれたアプリの python manage.py test を venv の python
  （C:\Users\yamad\Claude\JA\ja_system\venv\Scripts\python.exe、cwd=ja_system/ja_pj）で実行し、
  パスを確認してから次へ。出典が複数アプリにまたがる場合は該当する全アプリを対象にする。
- その 1 件で core/ ・ config/settings/ ・ templates/base.html ・ static/js/common.js を
  変更した場合は、その回だけ python manage.py test 全体も実行して回帰がないことを確認して。
- 対応した項目は review_pending.txt で「未対応（要対応）」から外し、通常の記録側に移して
  行末に「対応済み（リリース前に P8 で対応）」と追記して。
  併せて出典元の review_*.txt の該当行の「見送り／理由: ...」を
  「対応済み（review_pending.txt 経由でリリース前に対応）」に書き換えて。

途中で、1 件ずつのループで安全に直せない規模・リスクだと判断した項目があれば、
そこで止めて報告して。再度見送るか別途対応するかを一緒に決める。

全件終わったら python manage.py test 全体を実行し、
ここまでの修正を 1 コミットにまとめて（日本語メッセージ、
本文で review_pending.txt の対応項目番号に言及、末尾に Co-Authored-By 行）。
```

補足：
- コミットは 1 本にまとめる（他フェーズと同じ粒度）。項目が少数かつ雑多なので
  `review_pending.txt 未対応項目の対応（No.X, No.Y）` のようなメッセージにする。
- テスト対象は項目ごとに変わる。P1〜P4 のような固定 2 アプリではなく、出典に書かれたアプリを
  都度対象にする（→ review_pending.txt に出典を必ず残しておく）。
- review_pending.txt 側と元の review_*.txt 側の両方の行を「対応済み」に更新し、履歴が矛盾しないようにする。

---

## P9. 最終ゲート（全部積んだ後の全体像）※新設

```
/clear
リリース前チェックの最終ゲート。ここまでの全修正コミットが main からの差分として積まれている。
次を順に実行して、結果を RELEASE_PREP_NOTES.md にまとめて。

1. 全体テスト：venv の python（cwd=ja_system/ja_pj）で python manage.py test --verbosity=1 を実行。
   結果を release_baseline.txt と突き合わせて、
   ・新規に増えた失敗がゼロであること
   ・ベースラインにあった既存失敗の残数と、それぞれリリース許容と判断できるか
   を明記して。

2. 静的チェック：
   python manage.py makemigrations --check --dry-run
   python manage.py check
   （prod 用 .env が用意できる範囲で）python manage.py check --deploy --settings=config.settings.prod
   出力とその評価（SECURE_* ヘッダ・DEBUG・ALLOWED_HOSTS・SECRET_KEY 等）を記録。

3. 差分全体レビュー：git diff main...HEAD を対象に /code-review high を実行。
   4 グループ＋セキュリティの修正が互いに矛盾・重複していないか、
   共通コード（core・settings・base.html・common.js）の変更が他画面に副作用を出していないかに絞って。
   指摘があれば優先度付きで RELEASE_PREP_NOTES.md に記録（修正は「高」のみ即対応、他は判断を仰いで）。

4. フィデリティ・スポット再確認：この一連のチェックで views.py / forms.py / api.py を変更した画面を
   git diff から洗い出し、その画面だけ原本 HTML（../../HTML/html6/index.html + style.css）と
   突き合わせて、レンダリング結果・エラー表示・context 変数の受け渡しにズレが出ていないか確認して。
   （全画面の再監査は不要。触った画面のみ。）

5. 実アプリのスモークテスト：Browser pane で runserver を立てて、次の主要フローを一周して
   スクリーンショットか read_page で確認して。コンソールエラー・テンプレート構文の生表示・
   500 が出ないこと。
   ・/accounts/login/ でログイン
   ・/ メイン画面（お知らせ件数の表示）
   ・/documents/search/ で検索 → 検索結果詳細ポップアップ
   ・/documents/upload/step1/ → step2 → step3 のウィザード
   ・文書の削除 → ゴミ箱表示
   ・/contracts/search/ で同様に 1 往復
   ・/settings/ から設定メニュー各画面（職員/部署/分類/カテゴリー/保存期間/権限管理/操作履歴ログ）を開く
   ・/healthz/ が 200

6. 上記 1〜5 の結果サマリと、リリース可否の判断（ブロッカーの有無）を RELEASE_PREP_NOTES.md に記録して。
   問題がなければ RELEASE_PREP_NOTES.md をコミット（日本語メッセージ＋Co-Authored-By 行）。
```

---

## 実行順まとめ

| # | セッション | 成果物 |
|---|---|---|
| P0 | ベースライン | release_baseline.txt |
| P1 a〜f | documents / contracts | review_code_documents_contracts.txt / review_rule_doc_contract.txt / review_test_doc_contract.txt ＋コミット3本 |
| P2 a〜f | permissions / accounts | review_*_permissions_accounts.txt ＋コミット3本 |
| P3 a〜f | organizations / masters | review_*_organizations_masters.txt ＋コミット3本 |
| P4 a〜f | audit / core（core 変更回は全体テスト） | review_*_audit_core.txt ＋コミット3本 |
| P5 | security（diff） | review_security.txt |
| P6 | security（既存コード・エンドポイント単位） | review_security.txt 追記 |
| P7 | security 修正 | コミット1本 |
| P8 | 低優先度・見送り棚卸し | review_pending.txt 更新 |
| P8-b | 「直す」項目の修正（該当あれば） | コミット1本＋review_pending.txt / review_*.txt 更新 |
| P9 | 最終ゲート | RELEASE_PREP_NOTES.md ＋コミット1本 |
