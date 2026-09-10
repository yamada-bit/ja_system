# models定義 妥当性監査 — フェーズ1 指摘統合一覧

フェーズ1（指摘出しのみ）の5監査を統合・重複排除したもの。フェーズ2で
この一覧を上から順に対応する。各項目の「対応」列は未着手＝空欄。

**✅ 2026-09-10：フェーズ2 完了。** 全指摘に対応（実装 or 理由付きで現状維持を確定）。
各対応の詳細・見送り理由は `HTML_REIMPL_CHECKLIST_ARCHIVE.md`「models定義 妥当性監査 フェーズ2：
指摘対応」節。モデル変更は全て `0001_initial.py` 直書き、`makemigrations --check` クリーン、
`manage.py test` 全998件 PASS。コミットは未実施（ユーザー指示待ち）。

- 監査範囲：全8アプリの `models.py` ＋ 各 `migrations/0001_initial.py`
  ＋ 突き合わせ対象（validators.py / forms.py / services.py / 原本HTML html6 /
  簡易設計指示書 Rev1.6）
- 監査軸：A=原本フィデリティ / B=Django設計 / C=規約準拠 / D=アプリ間整合 /
  E=マイグレーション整合
- 「今回は修正しない」方針で洗い出しonly。フェーズ2の対応方針は別途指示。

凡例（深刻度）：高 / 中 / 低 / 観察（規約上は許容だが一貫性の観点で挙げたもの）

---

## 0. 先に方針確定が必要（要ユーザー確認）

**✅ Q-1〜Q-7 は 2026-09-10 にユーザー承認済み。確定した方針は
`HTML_REIMPL_CHECKLIST_ARCHIVE.md`「models定義 妥当性監査 フェーズ2：指摘対応」→「セクション0」に記載。**

対応に着手する前に決めるべき方針判断。ここが決まらないと下の個別対応がぶれる。

| ID | 論点 | 補足 |
|---|---|---|
| Q-1 | `Meta.ordering` を全モデルに持たせるか、ビュー側 `apply_sort` 依存を正とするか | xlsx は各一覧の初期ソート順を明記。現状どのモデルにも `ordering` なし（`ContractRelation` のみ例外）。B-ORD の前提。 |
| Q-2 | `models.py` の `logger` 宣言を8ファイルで統一するか（全付け／全外し）。現状 7:1 で混在（`core/models.py` だけ無し） | CLAUDE.md は「モデル定義のみは不要」「未使用も許容」の両論。C-7 の前提。 |
| Q-3 | 検索用シャドウ列 `*_normalized`（`editable=False`）に日本語 `verbose_name` を付けるか、「内部列のため付けない」を明示方針にするか | C-1 の前提。 |
| Q-4 | モデル層バリデーション（`RegexValidator` 等）を追加するか、フォーム／サービス層集約を正とするか | B-VAL 系（employee_no・分類/カテゴリーコードの半角数字、year、period_value 等）の共通方針。CSV取込という非フォーム経路がある点が判断材料。 |
| Q-5 | `AuditLog` に対象レコード（文書/契約書 pk 等）の構造化参照列を持たせるか、現行「自由テキストのみ」を仕様確定とするか | D-3 の前提。非正規化設計を崩さない範囲での判断。 |
| Q-6 | 論理削除マスタ（Group/Category/RetentionPeriod）の `department IS NULL` 行が部分ユニーク制約を外れる件（2026-09-10 確認済み）：本番移行で旧データの department を必ず埋めるか、null 残置許容か最終確認 | A-3。 |
| Q-7 | `contract_amount` の桁（`max_digits=12` ≒ 9,999億円上限）・`decimal_places=0`、`title max_length=255`、`branch_code`/`section_code` `max_length=10`（実桁は本支所3+部課2=5）、`SystemSetting.session_idle_timeout_minutes` 既定60、`Position` "90" ラベルの閉じ括弧補正 — いずれも原本/xlsx に明記なし。確定値の承認 | A-1 / A-2 / A-4 / C-6。 |

---

## 1. A軸：原本フィデリティ

| ID | 対象 | 現状 | あるべき姿 | 深刻度 | 対応 |
|---|---|---|---|---|---|
| A-1 | `contracts/models.py:55-57` `contract_amount` | `DecimalField(max_digits=12, decimal_places=0)`。原本HTML `<input type="text">`・xlsx とも桁/型の指定なし | 桁上限と型を承認（→ Q-7）。整数円なら `PositiveBigIntegerField` も候補（B-6と共通） | 低 | ✅2026-09-10 DecimalField維持で桁確定、理由コメント追記（B-6も同時にクローズ） |
| A-2 | `contracts/models.py:134-182` `ContractRelation` | html6 の保管画面2 関連書類欄は依然 `<input type="file">`（[index.html:287]）で旧 RelatedFile UI のまま。実装は xlsx Rev1.6 B478-484（既存契約書を検索して紐付け）に準拠 | ARCHIVE「R6-1」で確定済みだが、「レンダリングされる原本マークアップを基準」という監査方針とは形式上矛盾。html6 が Rev1.6 未追従である旨の明示確認（→ Q-7） | 低 | ✅2026-09-10 ARCHIVE「R6-1」節に明示的例外として注記 |
| A-3 | `masters/models.py:59-61` / `:100-102` `unique_group_code` / `unique_category_code` | `department IS NULL`（Rev1.2 移行前データ）の行が Postgres の NULL 非同一仕様で一意対象から外れる。2026-09-10 方針確認済み | 本番移行時の department 補完運用を最終確認（→ Q-6） | 低 | ✅2026-09-10 null残置は許容しない運用で確定、両制約コメントに追記 |
| A-4 | `contracts/models.py:58` `contract_partner` | 一覧のソート対象列（契約先名）だが `NormalizedTextFieldsMixin` の正規化対象外で、フリーワード検索にも含まれない（`core/search_services.py:105-107`） | 契約先名をフリーワード検索対象にすべきか xlsx に記載なし。確認（→ Q-7） | 低 | ✅2026-09-10 現状維持（対象外）で確定、理由コメント追記 |
| A-5 | `accounts/models.py:45` `Position` の "90" | 原本HTML（`index.html:2195`）は「臨時時給（翌月払」で閉じ括弧欠落。model は「臨時時給（翌月払）」に補正 | 補正のまま確定でよいか（`Rank`/`Position` は原本にマスタ画面が無い TextChoices 固定値。→ Q-7） | 低 | ✅2026-09-10 補正のまま確定、理由コメント追記 |

---

## 2. B軸：Django設計の妥当性

### 2.1 インデックス（検索・集計性能）

| ID | 対象 | 現状 | あるべき姿 | 深刻度 | 対応 |
|---|---|---|---|---|---|
| B-IDX-1 | `documents/models.py:120` / `contracts/models.py:117` | GIN(gin_trgm_ops) が**生カラム** `extracted_text` に張られている。検索フィルタ（`core/search_services.apply_word_filter`/`apply_freeword_filter`）は `*_normalized` にしか `icontains` しない。`doc_extracted_text_trgm` / `contract_extracted_text_trgm` はどのクエリからも使われず、OCR更新の書き込みコストだけ発生（生 `extracted_text` の使用箇所は `filter(extracted_text="")` 等値のみ） | 索引対象を `extracted_text_normalized` に寄せる（既にもう1本ある）か、生索引を削除 | 中 | ✅2026-09-10 生 GIN 2本を削除（models＋0001直書き、base.py:36コメント修正）。正規化列GINは維持。`DocumentIndexTests`/`ContractIndexTests` 追加、test documents contracts 416件PASS |
| B-IDX-2 | `documents/models.py:74-75` / `contracts/models.py:75-76` | `title_normalized` / `memo_normalized` に索引なし。フリーワード検索（`core/search_services.py:105-106`）とタイトル検索（`:90-91`）が両カラムに trgm `icontains` する | GinIndex(gin_trgm_ops) を追加。`extracted_text` 系との索引方針の非対称も解消 | 中 | ✅2026-09-10 `doc_title_norm_trgm`/`doc_memo_norm_trgm`（＋contract側2本）追加。正規化3列でGIN方針統一。test 418件PASS |
| B-IDX-3 | `documents/models.py:49` / `contracts/models.py:60` `expiry_date` | `db_index` なし。メイン画面お知らせ集計（`expiry_date__lt today` / 範囲）と検索「保存満了日」範囲・ソートで毎回使用 | `db_index=True` 相当 | 中 | ✅2026-09-10 両モデル＋0001に `db_index=True`。test 420件PASS（提案4でB-IDX-4と同時対応） |
| B-IDX-4 | `documents/models.py:103` / `contracts/models.py:99` `save_date` | 索引なし。一覧の初期ソート（保存日 降順）＋期間検索（`save_date__date` 範囲）の常用カラム | 索引対象 | 中 | ✅2026-09-10 両モデル＋0001に `db_index=True` |
| B-IDX-5 | `documents/models.py:112-113` / `contracts/models.py:108-109` `is_deleted` / `deleted_at` | 索引なし。ほぼ全クエリが `is_deleted=False` で絞り、`deleted_at__date__gte` も「直近削除」通知で使用 | 部分索引 or 複合索引の検討 | 低 | ✅2026-09-10 `deleted_at` の部分索引（`is_deleted=True` 限定、`doc_/contract_deleted_at_partial`）追加。ゴミ箱一覧・完全削除バッチ用。お知らせの条件付き集約は索引非使用のため対象外と明記。test 455件PASS |
| B-IDX-6 | `audit/models.py:18` `employee_no` | 索引なし。一覧・CSV は「職員番号の完全一致検索」（`filter(employee_no=...)`）を常用（`audit/services.py:63-65`）。`timestamp` 降順・`employee_name`/`event_message` の trgm GIN はあるのに完全一致で最も引きやすい列だけ無索引 | `db_index=True` を検討 | 低 | ✅2026-09-10 `db_index=True` 追加（models＋0001）。`AuditLogIndexTests` 追加 |

### 2.2 制約・バリデータ

| ID | 対象 | 現状 | あるべき姿 | 深刻度 | 対応 |
|---|---|---|---|---|---|
| B-VAL-1 | `accounts/models.py:64` `employee_no` / `masters/models.py:31` `Group.code` / `:73` `Category.code` | モデルに `validators` なし。「半角数字のみ許可（全角→半角変換）」はフォームの `clean_*`（`accounts/forms.py:112`、`masters/forms.py:122`/`:230`）のみ | CSV取込（`accounts/csv_import_services.py`）という実在の別経路や admin/将来コードでバイパスされる。モデル層に `RegexValidator` 等を持たせるか、正規化を共通サービスへ集約（→ Q-4） | 中 | ✅2026-09-10 3フィールドに `RegexValidator(r"^[0-9]+$")` 追加（models＋0001直書き）。効くのは full_clean() 経由（admin・将来のModelForm）。CSV取込は従来の明示チェックを残す。`CodeValidatorModelTests`＋accounts側テスト追加。既存TOCTOUテスト2件を数字コードに修正。test 224件PASS |
| B-VAL-2 | `masters/models.py:80-87` / `masters/forms.py:246-251` | `Category.doc_kbn` と `Category.group.doc_kbn` の一致はフォーム `clean` のみ。DB 制約なし | 分類と書類管理区分の食い違いを DB が許容。少なくとも `Category` のモデル `clean()` へ引き上げ | 低 | ✅2026-09-10 `Category.clean()` に一致チェックを追加（full_clean 経由＝admin・将来ModelForm。フォーム側チェックは残す）。マイグレーション不要。`CodeValidatorModelTests` にテスト追加 |
| B-VAL-3 | `documents/models.py:42` / `contracts/models.py:49` `year` | `PositiveIntegerField`、`validators` なし。フォームは choices で制約 | admin・一括・将来コードの直接 save で 0/桁あふれ値を受ける。`MinValueValidator`/`MaxValueValidator` 併用（→ Q-4） | 低 | ✅2026-09-10 `_YEAR_VALIDATORS = [MinValueValidator(1900), MaxValueValidator(2200)]` を両モデル＋0001に。定数は併記（クロスアプリimport回避）。test 709件PASS |
| B-VAL-4 | `masters/models.py:163` `period_value` / `:165` `display_order` / `:215` `session_idle_timeout_minutes` | 下限バリデータなし（`PositiveIntegerField` は 0 を許容） | 0ヵ月保存・表示順0・0分自動ログアウト（即時ログアウト）は無意味。`MinValueValidator(1)` 相当（→ Q-4） | 低 | ✅2026-09-10 3フィールドに `MinValueValidator(1)`（models＋0001）。`ContractRelation.display_order`（0始まり内部順）は対象外と明記。`MinValueValidatorModelTests` 追加 |
| B-VAL-5 | `contracts/models.py:51-53` `contract_period_start`/`_end` | 前後関係は DB 制約なし（フォーム `validate_date_range` のみ）。同ファイル `ContractRelation` は自己参照禁止を `CheckConstraint` でも二重化しており rigor が非対称 | `CheckConstraint(period_start <= period_end)`（null 考慮）を検討 | 低 | ✅2026-09-10 `contract_period_start_before_end` CheckConstraint 追加（両端null可、models＋0001）。`ContractPeriodConstraintTests` |
| B-VAL-6 | `organizations/models.py:65-91` `DepartmentViewScope` | `viewer_department == visible_department` を禁じる `CheckConstraint` なし（`ContractRelation` は同種の禁止あり、非対称）。`apply_dept_action` が self を作らないかも要確認 | 自己参照禁止の `CheckConstraint` 追加 | 低 | ✅2026-09-10 `no_self_department_view_scope` CheckConstraint 追加（`apply_dept_action` は既に skip 済み＝多層防御）。`DepartmentViewScopeConstraintTests` |
| B-VAL-7 | `masters/models.py:208-232` `SystemSetting` | シングルトン前提だが DB/モデルで未強制。`core/views.py:154` は `get_or_create(pk=1)`、`core/middleware.py:42` は `.first()` と読み口が不統一 | `CheckConstraint(pk=1)` 固定 or 参照を1関数へ集約 | 低 | ✅2026-09-10 `CheckConstraint(pk=1)` はPGシーケンス非ロールバックで `objects.create()` 主体のテスト/adminと相性が悪く不採用。`SystemSetting.load()`（get_or_create(pk=1)）に集約：`core/views.py` の3箇所を置換。middleware だけは全リクエスト経路のため `.first()`+None フォールバック維持（行未作成時にDB書込みしない、理由コメント）。`SystemSettingLoadTests` |
| B-VAL-8 | `documents/models.py:58`/`:88` / `contracts/models.py:65`/`:86` `file` / `searchable_file` | `FileField` に拡張子・MIME・サイズ validator なし。能動コンテンツ拒否は `BaseUploadStep1View`（`core/upload_views.py:134-142`）のみ | `FileExtensionValidator` 等をフィールドにも付ける（配信側 `core.file_serving` と多層防御） | 低 | ✅2026-09-10 `core.upload_validation.validate_no_active_content` を新設し `Document.file`/`Contract.file` の validators に付与（models＋0001）。拒否リスト方式のため `FileExtensionValidator`（許可リスト）は不採用。`searchable_file` はシステム生成PDFのため対象外。`DocumentFileValidatorTests`/`ContractFileValidatorTests` |

### 2.3 型選択・フィールド構成・非対称

| ID | 対象 | 現状 | あるべき姿 | 深刻度 | 対応 |
|---|---|---|---|---|---|
| B-ORD | 全モデル（`ContractRelation` を除く） | `Meta.ordering` 未定義。xlsx は各一覧の初期ソートを明記 | ビュー側 `apply_sort` 依存で、ソート未指定経路の結果が不定。方針決定（→ Q-1）の上、必要なら `ordering` 付与 | 低 | ✅2026-09-10 Q-1どおり `ordering` は付けない。`core.search_services.apply_sort` が一覧ソートの唯一の入口である旨を docstring 化、`build_queryset` が全 return 経路で `apply_sort` を通ることを確認 |
| B-6 | `contracts/models.py:55-57` `contract_amount` | `DecimalField(decimal_places=0)`＝整数格納。`CommaNumberInput` が `Decimal` 往復 | 整数円なら `PositiveBigIntegerField` が素直（A-1 と共通判断） | 低 | ✅2026-09-10 A-1と同時クローズ。DecimalField維持（CommaNumberInputがDecimal往復前提） |
| B-7 | `permissions/models.py:157` `PermissionProfile` | `updated_at`(auto_now) はあるが `created_at` なし。他マスタは両方持つ（`RetentionPeriod` は review_pending No.24 で追随済み） | 権限プロファイルの新規作成時刻が残らない。他マスタと揃える | 低 | ✅2026-09-10 `created_at` 追加（提案13でB-8と同時）。test 273件PASS |
| B-8 | `organizations/models.py:97-122` `MenuItemSetting` / `masters/models.py:208-232` `SystemSetting` / `organizations/models.py:81` `DepartmentViewScope` | タイムスタンプ非対称：前2つは `created_at`/`updated_at` なし、`DepartmentViewScope` は `created_at` のみ | 変更時刻が残らず監査・障害調査で不利。他マスタと揃える | 低 | ✅2026-09-10 `MenuItemSetting`/`SystemSetting` に created_at/updated_at、`DepartmentViewScope` に updated_at を追加（3アプリ 0001 直書き） |
| B-9 | `audit/models.py:20` `department_name` | `CharField(max_length=200)`。記録元 `str(employee.department)` は実効的に最大100。`employee_name`(100=`Employee.name` と一致)・`employee_no`(20=一致) と根拠が不揃い | 200 の根拠を明記 or 実効長に合わせる | 低 | ✅2026-09-10 「実効長100・200は将来の部署名長変更/改編時の余裕」コメント追記 |
| B-10 | `permissions/models.py:81-119` `doc_visible_groups` / `contract_visible_groups`（M2M → `masters.Group`、`related_name="+"`） | Group は論理削除で物理行が残るため、削除済み Group への M2M 行が中間テーブルに残留。逆参照が `+` のため Group 側からの棚卸し経路なし | Group 論理削除時に関連 M2M 行も掃除する or `related_name` を付ける | 低 | ✅2026-09-10 「削除済みGroupへのM2M残行は消費側が`is_deleted=False`で必ず絞るため実害なし。棚卸しが要れば`related_name`を付ける」コメント追記（掃除・related_nameは見送り） |
| B-11 | `permissions/models.py:8-13` `PermissionRole` | 値が `"admin"/"manager"/"staff"`。xlsx は「権限コード 1:管理者 2:所属長 3:一般」昇順ソートを要求。`order_by("role")` のアルファベット順は偶然一致するだけ | ビュー側が `Case/When` で明示マッピングしているか確認。将来ラベル値を変えると崩れる旨をコメント化 | 低 | ✅2026-09-10 ビューは `order_by("permission_profile__role")`＝アルファベット順に依存（Case/Whenは無い）。`PermissionRole` docstring と `AUTHORITY_SORT_FIELDS["role"]` に「1/2/3昇順と偶然一致、格納値を変えるならCase/When化」を明記 |
| B-12 | `accounts/models.py:74-76` `is_retired` / `is_active` | `is_retired=True` でも `is_active` は `True` のまま。退職者ログイン拒否は `accounts/forms.py:39`（ログインフォーム）1 箇所のみ | Django の `ModelBackend.user_can_authenticate` は `is_active` を見る。別の認証経路が増えると退職者ログインが通る。`is_retired` セット時に `is_active=False` も落とす／バックエンドで一元化 | 低〜中 | ✅2026-09-10 `is_active` を BooleanField→プロパティ（`not is_retired`）化＋0001からカラム削除。ModelBackendも退職者を弾く。専用メッセージ維持のため `LoginForm.clean` に「退職者かつPW一致時のみ専用エラー」の上書き（ユーザー選択）。テスト2件追加、全件PASS |
| B-13 | `contracts/models.py:156-160` `ContractRelation.related_contract` = `on_delete=CASCADE` | 紐付け先（所有者でない側）が物理削除されると、削除されていない所有契約書の関連行が黙って消える。docstring では意図と明記 | 現状維持なら可、要認識（監査上「関連書類が消えた記録が残らない」点は残課題） | 低 | ✅2026-09-10 現状維持。docstring に「認識済み・現状維持（物理削除自体が日次バッチのみ）」を明記 |

---

## 3. C軸：規約準拠

| ID | 対象 | 現状 | あるべき姿 | 深刻度 | 対応 |
|---|---|---|---|---|---|
| C-1 | `documents/models.py:74-76` / `contracts/models.py:75-77` `*_normalized` | `verbose_name` 未設定。Django が英語風の自動名（"title normalized" 等）を生成。`editable=False` で通常 UI には出ない | 日本語 `verbose_name` を付けるか、付けない方針を明示（→ Q-3） | 低 | ✅2026-09-10 Q-3どおり付けない。「editable=False の検索用内部列のため付けない」コメントを両モデルに追記 |
| C-2 | `accounts/models.py`（`AbstractBaseUser` 継承分） | `password` / `last_login` の `verbose_name` が英語（"password" / "last login"）のまま。マイグレーション・admin・フォームに露出。`is_staff`/`is_superuser` は日本語で上書き済みで非対称 | `Employee` 側で override するか許容根拠を明記 | 低 | ✅2026-09-10 `password`（"パスワード"）/`last_login`（"最終ログイン"）を再宣言で上書き（0001も更新）。test 388件PASS |
| C-3 | `accounts/models.py:12` / `:20` `EmployeeManager.create_user` / `create_superuser` | メソッド docstring なし（クラスには docstring あり）。`create_superuser` は `is_staff`/`is_superuser` を暗黙設定 | 1行 docstring を付ける | 低 | ✅2026-09-10 両メソッドに1行 docstring |
| C-4 | `masters/models.py:202-205` `RetentionPeriod.__str__` | `period_unit == PERMANENT` で分岐する非自明メソッドだが docstring なし | 「永年」特別扱いの理由を1行 | 低 | ✅2026-09-10 `__str__` に「永年」特別扱いの docstring |
| C-5 | `accounts/models.py:96-100` `Employee.has_perm` / `has_module_perms` | `is_superuser` のみ返すが「なぜ」コメント／docstring なし。クラス docstring は PermissionsMixin 不使用までで、admin 用最小実装の意図には触れていない | 「なぜ」を1行 | 低 | ✅2026-09-10 「admin 用最小実装。認可は permissions アプリで独自判定」コメント追記 |
| C-6 | `masters/models.py:215` `session_idle_timeout_minutes = PositiveIntegerField(default=60)` | `60` が `config/settings/base.py:178` のフォールバック値と重複したハードコード | `default` を callable 化して settings 参照にする余地（→ Q-7 で値自体も確認） | 低 | ✅2026-09-10 `default=_default_session_idle_timeout`（`settings.SESSION_IDLE_TIMEOUT_MINUTES` を返す関数）に。0001も更新。`test_default_session_idle_timeout_follows_settings` |
| C-7 | 8アプリの `models.py`（accounts:6 / organizations:5 / masters:6 / documents:9 / contracts:12 / permissions:5 / audit:8） | 7つが未使用の `logger = logging.getLogger(__name__)` を宣言。`save()` を override する `core/models.py` だけ logger なしで非対称 | CLAUDE.md は両論。8ファイルで方針統一（→ Q-2） | 観察 | ✅2026-09-10 Q-2で現状維持（7:1混在を許容）と確定。CLAUDE.md が両論明記済みで実害なし。コード変更なし |

---

## 4. D軸：アプリ間整合

| ID | 対象 | 現状 | あるべき姿 | 深刻度 | 対応 |
|---|---|---|---|---|---|
| D-1 | `permissions/models.py:78` `role` + 生成経路 | `default` なし。CSV取込は即時 `create(role=STAFF)`（`accounts/csv_import_services.py:174`）、手動の職員登録（`accounts/forms.py:123-130`）は `PermissionProfile` を作らず遅延生成（`permissions/views.py:193`/`:215` の `get_or_create(defaults={"role": STAFF})`、`permissions/services.py:27` の欠損時フォールバック）。初期値 STAFF が4箇所に散在 | xlsx 職員マスタ D118「新規登録時に『権限管理』は初期値をセットしておく」。`default=PermissionRole.STAFF` をフィールドに持たせ、登録経路の挙動を揃える（`t_staff_permission` に行が無い職員が存在し得る状態を解消）（→ Q-4/Q-5 と併せ判断） | 中 | ✅2026-09-10 `default=PermissionRole.STAFF` をフィールドに追加（models＋0001）。ユーザー指示で「defaultのみ」＝遅延生成フロー統一・CSV取込の明示role指定撤去は別スコープ。test 183件PASS |
| D-2 | `permissions` 電子決裁3フラグ | `eapproval_view_setting`/`eapproval_doc_name_manage`/`eapproval_retention` は「保持のみ・連動先なし」。`models.py`/`FLAG_FIELDS`/`CSV_EXPORT_FIELDS`/フォーム/CSV出力/tests にしか現れず、`if profile.eapproval_*` の分岐はゼロ。将来用注記（`permissions/models.py:139-140`）健在。CLAUDE.md「既知の未実装・保留事項」と一致 | **指摘なし（現状維持）**。フェーズ2で連動ロジックを入れない／注記を消さない | — | |
| D-3 | `audit/models.py:11-31` `AuditLog` | 非正規化スナップショット設計で、対象レコード（文書/契約書 pk 等）への構造化参照を持たず、`event_message` 自由テキストに `ID:{pk}` 等が混ざるのみ（`audit/services.py:159`） | 将来「特定文書の操作履歴一覧」要件が出たら別途 `target_type`/`target_id` 列が必要。現行「テキストのみ」で確定してよいか（→ Q-5） | 低 | ✅2026-09-10 Q-5どおり自由テキストのみで仕様確定。`AuditLog` docstring に明記 |
| D-4 | 8アプリ FK 方向・循環 import・related_name | **問題なし**。FK は DAG（organizations → accounts/masters → permissions/documents/contracts、audit → core のみ、core は抽象 Mixin）。循環 import なし（全クロスアプリ FK が文字列参照）。related_name 衝突なし（`Department`/`Group` への複数逆参照は `employees`/`documents`/`contracts`/`categories`/`view_scopes_as_*`/`menu_item_setting` ＋ `+` で全て一意） | **指摘なし**。回帰しないよう新規 FK 追加時に再確認 | — | |

---

## 5. E軸：マイグレーション整合

`makemigrations --check --dry-run` → **差分なし**（"No changes detected"）。
全8アプリで `models.py` と `0001` が一致。migration は各アプリ `0001` の1本のみ
（core のみ `0001_enable_pg_trgm.py`）。**0002 以降の未材化 migration なし**、
squash 運用中の 0001 直書きは漏れなし。制約・索引・choices・default・on_delete・
（不使用の）db_collation の目視突き合わせも一致。

以下は E軸として実害のない整容レベルの観察（`--check` 差分ではない）。

| ID | 対象 | 現状 | あるべき姿 | 深刻度 | 対応 |
|---|---|---|---|---|---|
| E-1 | `contracts/models.py:175-178` `CheckConstraint` | モデルは `check=~models.Q(...)`（`check=` キーワード＝Django 5.1 で `condition=` に改称、5.x で非推奨・6.0 で削除予定）。生成済み migration（`contracts/migrations/0001_initial.py:84`）は `condition=` | モデル側も `condition=~models.Q(...)` に揃える。schema 同一・`--check` も通るが、再 makemigrations 時の無用な差分・警告を避ける | 低 | ✅2026-09-10 `ContractRelation` の `check=`→`condition=` |
| E-2 | `audit/models.py:38` `models.Index(fields=["-timestamp"])` | `name=` 未指定。migration 側は自動命名 `t_audit_log_timesta_894930_idx` が pin 済み。同ファイルの GinIndex 2本や documents/contracts の GinIndex は全て明示 `name=` 付きで非対称 | 明示名（例 `auditlog_timestamp_desc_idx`）を付ける。※現状 migration に固定済みで schema drift リスクはなし | 低 | ✅2026-09-10 `name="auditlog_timestamp_desc_idx"` をモデル＋0001に。`AuditLogIndexTests` に assertion 追加 |
| E-3 | documents ↔ contracts の GinIndex 記述方式 | `documents` migration は `CreateModel(options={"indexes":[...]})` 内包、`contracts` migration は独立 `AddIndex` 2本。生成 schema は同一 | 並行構成なので記述方式も揃えると差分レビューが楽（squash 直書き時にどちらかへ寄せる） | 低（整容） | ✅2026-09-10 `contracts/0001` の Contract 用 `AddIndex`4本・`AddConstraint`1本を `CreateModel` の `options` へ移動（documents 側に統一）。ContractRelation の `AddConstraint` は別モデルのため据え置き |

---

## 6. フェーズ1で「問題なし」を確認した項目（フェーズ2で再調査不要）

- **業務ロジックのモデル漏れなし**：全8モデルに `clean()` は1つも無く、`save()` の
  override は `core/models.py:51` の検索正規化シャドウカラム同期のみ（業務ルール
  ではなくインフラ処理、`update_fields` の落とし穴まで docstring 済み）。保存満了日
  再計算・部署スコープ判定・権限判定はすべて services.py に分離。
- **非正規化・choices固定値・並行構成の意図的差異には「なぜ」コメントあり**
  （AuditLog、Rank/Position、Contract に privacy_flag なし 等）。
- **設定値ハードコードなし**（C-6 の `default=60` を除く）：お知らせしきい値・
  契約書保存年数・「永年」実年数・監査ログ保持期間はモデルに literal なく
  settings/services 経由（help_text が settings 名を明示）。
- **全モデルクラスに日本語 docstring あり**。verbose_name/help_text は
  C-1/C-2 の例外を除き日本語統一。
- **on_delete 保護**：master 参照系（Employee/Document/Contract の
  department・group・category・retention_period、Category.group、
  Group/Category.department）は全て `PROTECT`。論理削除マスタは物理行を消さない
  ため PROTECT が発火せず既存レコードの参照も切れない。
- **unique**：`employee_no`、`Department`(branch_code, section_code)、
  Group/Category/RetentionPeriod の部分ユニーク制約群はいずれも要件どおり。
- **employee_no ログイン・Argon2 前提**：`USERNAME_FIELD`／`EmployeeManager`／
  `PermissionsMixin` 不使用で整合。`password`(max_length=128) に Argon2 収まる。
- **eapproval 3フラグ**＝保持のみ・連動先なし（D-2）。
- **FK方向 DAG・循環importなし・related_name衝突なし**（D-4）。
- **マイグレーション：`--check` 差分なし・0002以降なし・squash直書き漏れなし**（E軸）。
