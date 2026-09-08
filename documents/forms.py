import copy
import datetime
import logging

from django import forms
from django.urls import reverse_lazy

from core.forms import (
    MATCH_CHOICES,
    MATCH_OR,
    apply_radio_defaults,
    apply_search_department_default,
    scoped_group_and_category_querysets,
    search_year_choices,
    validate_date_range,
    year_choices_with_existing,
)
from core.widgets import InlineRadioSelect, PopupSelectWidget
from documents.services import used_retention_periods
from masters.models import Category, DocKbn, Group, RetentionKbn, RetentionPeriod
from organizations.models import Department
from organizations.services import visible_department_ids
from permissions.services import can_edit_retention, can_select_department

logger = logging.getLogger(__name__)

API_OPTIONS_URL = reverse_lazy("documents:api_options")


class UploadStep2Form(forms.Form):
    """screen-storage2（文書モード）の保管先・文書情報フォーム。

    新規保管（createモード＝`edit_mode=False`）では、複数ファイルを一括選択した場合でも
    **メタデータ（部署・分類・年・カテゴリー・保存期間・個人情報・メモ）をファイルごとに
    個別入力する**（2026-08-31ユーザー確定。ページャーで表示中のファイルの分だけ設定する）。
    そのため、`PER_FILE_FIELDS`の各フィールドをファイル数ぶん複製して`{name}_0`,`{name}_1`,…に
    差し替える（タイトルも従来どおり`title_0`,`title_1`,…）。原本HTML確定版のJS
    （`startRegisterMock()`）はタイトル以外をバッチ全体へ共通適用しており、ここは原本との
    意図的な差異（ユーザー明示依頼のため原本一致よりユーザー指示を優先。CLAUDE.md
    「原本フィデリティに関する運用方針」）。

    編集モード（`edit_mode=True`＝DocumentEditView／BulkEditView、常に1ファイル）は複製せず
    無添字（`department`,`group`,…）のまま。ビューの保存ループは`file_data(i)`を通すことで
    どちらのモードでも分岐しない。

    部署/分類/カテゴリーは原本通り`core.widgets.PopupSelectWidget`（読み取り専用テキスト＋
    「選択」ボタン→ポップアップ）を使う。年・保存期間は原本でも素の`<select>`のため、
    Djangoの既定ウィジェットのままにしている。
    """

    # createモードでファイルごとに複製する項目名（タイトルは別枠でtitle_Nとして追加）。
    PER_FILE_FIELDS = (
        "department", "group", "year", "category", "retention_period", "privacy_flag", "memo",
    )

    department = forms.ModelChoiceField(
        label="部署",
        queryset=Department.objects.all(),
        required=True,
        widget=PopupSelectWidget(
            popup_type="dept", mode="storage", api_url=API_OPTIONS_URL, queryset=Department.objects.all()
        ),
    )
    group = forms.ModelChoiceField(
        label="分類",
        queryset=Group.objects.filter(doc_kbn=DocKbn.DOCUMENT, is_deleted=False),
        required=True,
        widget=PopupSelectWidget(
            popup_type="group",
            mode="storage",
            api_url=API_OPTIONS_URL,
            queryset=Group.objects.filter(doc_kbn=DocKbn.DOCUMENT, is_deleted=False),
            label_func=lambda g: g.name,
        ),
    )
    category = forms.ModelChoiceField(
        label="カテゴリー",
        queryset=Category.objects.filter(doc_kbn=DocKbn.DOCUMENT, is_deleted=False),
        required=True,
        widget=PopupSelectWidget(
            popup_type="category",
            mode="storage",
            api_url=API_OPTIONS_URL,
            queryset=Category.objects.filter(doc_kbn=DocKbn.DOCUMENT, is_deleted=False),
            label_func=lambda c: c.name,
        ),
    )
    # 原本は<select id="storage-year">の固定選択式（screen-storage2.html56-65、2021〜2026年の
    # 6択ハードコード）。IntegerFieldのままだと自由入力の数値スピンボックスになり見た目・挙動が
    # 大きく食い違うため、検索画面のyearフィールドと同じ「実行時に直近年の選択肢を生成する」
    # 方式のChoiceFieldにする（値を固定年でハードコードすると実装が経年劣化するため）。
    # 2026-08-20ユーザー確認：保存満了日＝保存した日+保存期間であり、この「年」欄（文書の
    # 業務上の年）は保存満了日の計算に一切関与しない。そのためonchangeは付けない
    # （calculateExpiryDate()側もyearを参照しない設計に変更済み。documents.services.
    # expiry_date_previews docstring参照）。
    year = forms.TypedChoiceField(
        label="年",
        required=True,
        choices=[],
        coerce=int,
        widget=forms.Select(attrs={"id": "storage-year", "class": "size-short"}),
    )
    retention_period = forms.ModelChoiceField(
        label="保存期間",
        queryset=RetentionPeriod.objects.filter(kbn=RetentionKbn.DOCUMENT, is_deleted=False).order_by(
            "display_order"
        ),
        required=True,
        empty_label=None,
        # 原本index.html:242 <select id="storage-period" onchange="calculateExpiryDate()" class="size-short">
        # を再現。id/onchangeはJS(calculateExpiryDate、documents/storage2.html・edit.htmlのextra_script)から参照される。
        widget=forms.Select(attrs={"id": "storage-period", "class": "size-short", "onchange": "calculateExpiryDate()"}),
    )
    privacy_flag = forms.TypedChoiceField(
        label="個人情報が含まれる",
        choices=((True, "含まれる"), (False, "含まれない")),
        coerce=lambda v: v in ("True", True),
        initial=True,
        widget=forms.RadioSelect,
    )
    memo = forms.CharField(
        label="メモ",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "備考・補足事項等を入力"}),
    )

    def __init__(self, *args, employee=None, file_count=1, initial_titles=None, edit_mode=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.employee = employee
        self.file_count = file_count
        # createモードはメタデータ項目もファイルごと（{name}_{i}）。編集モードは無添字のまま。
        self.per_file_mode = not edit_mode
        current = datetime.date.today().year

        if self.per_file_mode:
            # PER_FILE_FIELDS をファイル数ぶん複製して {name}_0.. に差し替える（素の name は消す）。
            # Field.__deepcopy__ が widget.attrs も複製するため、各コピーの属性は独立する。
            for name in self.PER_FILE_FIELDS:
                base_field = self.fields.pop(name)
                for i in range(file_count):
                    self.fields[f"{name}_{i}"] = copy.deepcopy(base_field)

        def fname(base, i):
            return f"{base}_{i}" if self.per_file_mode else base

        # xlsx 保管!P139,P174(Rev1.2)「分類/カテゴリー選択は…自部署の内容を表示」。
        group_qs, category_qs = scoped_group_and_category_querysets(
            doc_kbn=DocKbn.DOCUMENT, kind="document", employee=employee
        )

        for i in range(file_count):
            # 年: 実行時の直近年で選択肢生成。編集モードでは対象の現在の年を必ず含める
            # （core.forms.year_choices_with_existing docstring。含めないと年欄に触れず更新
            # しただけで年が意図せず書き換わる）。createは既存年が無いため常にNone。
            year_field = self.fields[fname("year", i)]
            year_field.choices = year_choices_with_existing(
                None if self.per_file_mode else self.initial.get("year")
            )
            year_field.initial = current

            # xlsx 保管!B78-82: 部署名欄「選択」ボタンは権限が"管理者"のユーザのみ表示。管理者以外は
            # ボタン非表示＋自部署固定（読み取り専用）。self.initial（Formのinitial辞書）は
            # fields[x].initialより優先されるため（Django BaseForm.get_initial_for_field）、
            # view側initialを確実に上書きするにはここも更新する。
            dept_field = self.fields[fname("department", i)]
            if employee is not None and not can_select_department(employee):
                dept_field.disabled = True
                self.initial[fname("department", i)] = employee.department_id
            elif employee is not None and not edit_mode:
                # B82「初期値はログインユーザーの部署名をセット」は新規登録画面のみ。編集画面は
                # 既存文書の部署をview側がinitialで渡すため上書きしない。setdefaultにしているのは、
                # 「削除」（アップロード取り消し）後の再描画でview側が保持済みの部署をinitialで
                # 渡してくるため（2026-08-31、core.upload_views.remap_step2_initial_after_remove）。
                self.initial.setdefault(fname("department", i), employee.department_id)

            # xlsx 権限管理!B172-175(Rev1.1)「文書管理-文書-保存満了日変更」OFFで保存済み文書の
            # 保存期間は編集不可（新規保管はまだ「保存済み」でないため対象外）。
            if edit_mode and employee is not None and not can_edit_retention(employee):
                self.fields[fname("retention_period", i)].disabled = True

            for base, qs in (("group", group_qs), ("category", category_qs)):
                f = self.fields[fname(base, i)]
                f.queryset = qs
                f.widget.queryset = qs

            # per_file_mode では同一idのwidgetが複数出るため添字化する。retention_period の
            # onchange は保存満了日プレビュー（storage2.html の calculateExpiryDate(idx)）と連動。
            if self.per_file_mode:
                rp_attrs = self.fields[f"retention_period_{i}"].widget.attrs
                rp_attrs["id"] = f"storage-period-{i}"
                rp_attrs["onchange"] = f"calculateExpiryDate({i})"
                self.fields[f"year_{i}"].widget.attrs["id"] = f"storage-year-{i}"

        initial_titles = initial_titles or []
        for i in range(file_count):
            initial = initial_titles[i] if i < len(initial_titles) else ""
            self.fields[f"title_{i}"] = forms.CharField(
                label=f"文書タイトル({i + 1})", initial=initial, max_length=255
            )

    def file_data(self, i):
        """i番目のファイルとして保存するクリーン値の辞書（キーは PER_FILE_FIELDS ＋ "title"）。
        per_file_mode なら `{name}_{i}` を、編集モードなら無添字を引く（ビューの保存ループを
        モードで分岐させないため）。"""
        suffix = f"_{i}" if self.per_file_mode else ""
        data = {name: self.cleaned_data[f"{name}{suffix}"] for name in self.PER_FILE_FIELDS}
        data["title"] = self.cleaned_data[f"title_{i}"]
        return data

    def first_error_file_index(self):
        """最初に入力エラーを持つファイルの添字（無ければ0）。per_file_mode でのみ意味を持つ。"""
        if not self.per_file_mode:
            return 0
        for i in range(self.file_count):
            keys = {f"{name}_{i}" for name in self.PER_FILE_FIELDS} | {f"title_{i}"}
            if keys & set(self.errors):
                return i
        return 0


class SearchForm(forms.Form):
    """screen-search（文書モード）の検索条件フォーム。部署/分類/年/カテゴリーは原本通り
    複数選択（チェックボックス）ポップアップのため、カンマ区切りの複数値を受け取る
    `ModelMultipleChoiceField`/`MultipleChoiceField`にしている
    （SCREENS_INVENTORY_WAVE1.md: `renderPopupPopupItems()`は検索モードでは常にチェックボックス）。
    """

    department = forms.ModelMultipleChoiceField(
        label="部署",
        queryset=Department.objects.all(),
        required=False,
        widget=PopupSelectWidget(
            popup_type="dept", mode="search", api_url=API_OPTIONS_URL, queryset=Department.objects.all(), multi=True
        ),
    )
    group = forms.ModelMultipleChoiceField(
        label="分類",
        queryset=Group.objects.filter(doc_kbn=DocKbn.DOCUMENT, is_deleted=False),
        required=False,
        widget=PopupSelectWidget(
            popup_type="group",
            mode="search",
            api_url=API_OPTIONS_URL,
            queryset=Group.objects.filter(doc_kbn=DocKbn.DOCUMENT, is_deleted=False),
            label_func=lambda g: g.name,
            multi=True,
        ),
    )
    year = forms.MultipleChoiceField(
        label="年",
        required=False,
        choices=[],
        widget=PopupSelectWidget(
            popup_type="year", mode="search", api_url=API_OPTIONS_URL, label_func=lambda y: f"{y} 年", multi=True
        ),
    )
    category = forms.ModelMultipleChoiceField(
        label="カテゴリー",
        queryset=Category.objects.filter(doc_kbn=DocKbn.DOCUMENT, is_deleted=False),
        required=False,
        widget=PopupSelectWidget(
            popup_type="category",
            mode="search",
            api_url=API_OPTIONS_URL,
            queryset=Category.objects.filter(doc_kbn=DocKbn.DOCUMENT, is_deleted=False),
            label_func=lambda c: c.name,
            multi=True,
        ),
    )
    title = forms.CharField(
        label="文書タイトル",
        required=False,
        widget=forms.TextInput(attrs={"style": "width:340px;", "placeholder": "タイトルを入力　キーワードスペース区切り"}),
    )
    title_match = forms.ChoiceField(
        choices=MATCH_CHOICES, initial=MATCH_OR, required=False, widget=InlineRadioSelect
    )
    freeword = forms.CharField(
        label="フリーワード",
        required=False,
        widget=forms.TextInput(attrs={"style": "width:340px;", "placeholder": "フリーワードを入力　キーワードスペース区切り"}),
    )
    freeword_match = forms.ChoiceField(
        choices=MATCH_CHOICES, initial=MATCH_OR, required=False, widget=InlineRadioSelect
    )
    save_date_start = forms.DateField(
        label="期間(開始)", required=False, widget=forms.DateInput(attrs={"type": "date", "style": "width:140px;"})
    )
    save_date_end = forms.DateField(
        label="期間(終了)", required=False, widget=forms.DateInput(attrs={"type": "date", "style": "width:140px;"})
    )
    save_day_kbn = forms.ChoiceField(
        choices=(("save", "保存日"), ("expiry", "保存満了日")),
        initial="save",
        required=False,
        widget=InlineRadioSelect,
    )
    # xlsx 検索・閲覧・変更!B182-184「保存済み全文書に紐付けられている保存期間を重複なしで
    # 抽出し、プルダウン化する。(リストは日数の短い順から昇順で生成)　※「保存期間設定」で
    # 設定したデータは使用しない」。選択肢はdocuments.services.used_retention_periods()が
    # 実データから都度生成するため、queryset自体は__init__で差し替える（初期値はモデル全件だと
    # バリデーション上は矛盾しないが、実際に選べる選択肢と一致させるため必ず上書きする）。
    retention_period = forms.ModelChoiceField(
        label="保存期間",
        queryset=RetentionPeriod.objects.none(),
        required=False,
        empty_label="(指定なし)",
    )

    def __init__(self, *args, employee=None, **kwargs):
        # ラジオ選択肢の既定checkedを原本通りに出すため、バインドされたQueryDictに
        # 該当キーが無ければ既定値を補う（フォームのbound/unbound判定自体は変えない）。
        # 実体はcore.forms.apply_radio_defaultsに集約済み（contracts.forms.SearchFormとの
        # 重複をコード監査で発見、2026-08-25修正）。
        args, kwargs = apply_radio_defaults(args, kwargs)
        # xlsx 検索・閲覧・変更!B46-48(Rev1.1)「部署名：ログインユーザーの部署を自動セット／
        # 閲覧部署範囲テーブルの旧部署もカンマ区切り」。管理者（部署名「選択」ボタンあり＝
        # 非disabled）も含めて部署欄に自部署を既定表示するため、`field.initial`ではなくバインド
        # 済みdataへ補完する（core.forms.apply_search_department_default のdocstring参照。
        # 以前は下の非管理者分岐でしかセットされず、管理者は部署欄が空だった）。
        own_dept_ids = (
            visible_department_ids(employee)
            if employee is not None and employee.department_id
            else []
        )
        args, kwargs = apply_search_department_default(args, kwargs, own_dept_ids)
        super().__init__(*args, **kwargs)
        # xlsx 検索・閲覧・変更!B137-140「今年～文書が保存されている最古の年」（IntegerFieldでは
        # なくMultipleChoiceFieldなのはPopupSelectWidgetがリスト値を扱う都合上）。
        self.fields["year"].choices = search_year_choices(DocKbn.DOCUMENT)
        self.fields["retention_period"].queryset = used_retention_periods()

        if employee is not None and not can_select_department(employee):
            # 原本は行自体を消さず「選択」ボタンのみ非表示にする（index.html
            # select-dept-div表示切替）。フィールド自体は残しdisabled化し、
            # 自部署を読み取り専用表示する（widgetのボタン非表示はcore.widgets.PopupSelectWidget側）。
            # disabledフィールドはバインド済みでも`field.initial`が描画・cleanに使われるため、
            # 上のdata補完とは別に従来どおりinitialも設定する（同じ`own_dept_ids`で一致させる）。
            self.fields["department"].disabled = True
            self.fields["department"].initial = own_dept_ids
        # xlsx 検索・閲覧・変更!P96,P152(Rev1.2)「分類/カテゴリー選択は…自部署の内容を表示」。
        group_qs, category_qs = scoped_group_and_category_querysets(
            doc_kbn=DocKbn.DOCUMENT, kind="document", employee=employee
        )
        self.fields["group"].queryset = group_qs
        self.fields["group"].widget.queryset = group_qs
        self.fields["category"].queryset = category_qs
        self.fields["category"].widget.queryset = category_qs

    def clean(self):
        cleaned = super().clean()
        # 期間(開始)＞期間(終了)は「黙って0件」になり不親切なため弾く（review_pending.txt No.3）。
        validate_date_range(self, "save_date_start", "save_date_end", label="期間")
        return cleaned
