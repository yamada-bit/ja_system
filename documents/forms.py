import datetime
import logging

from django import forms
from django.urls import reverse_lazy

from core.forms import search_year_choices, year_choices_with_existing
from core.widgets import InlineRadioSelect, PopupSelectWidget
from documents.services import used_retention_periods
from masters.models import Category, DocKbn, Group, RetentionPeriod
from organizations.models import Department
from organizations.services import visible_department_ids
from permissions.services import can_edit_retention, can_select_department, visible_groups

logger = logging.getLogger(__name__)

API_OPTIONS_URL = reverse_lazy("documents:api_options")


class UploadStep2Form(forms.Form):
    """screen-storage2（文書モード）の保管先・文書情報フォーム。バッチ内の全ファイルに共通の
    メタデータ（部署・分類・年・カテゴリー・保存期間・個人情報・メモ）を1回の入力で適用する
    （HTML確定版のJSも`startRegisterMock()`で分類・年・カテゴリー等をバッチ全体に共通適用しており、
    ファイルごとに異なるのはタイトルのみ＝別途`title_0`,`title_1`,...を動的に追加する）。

    部署/分類/カテゴリーは原本通り`core.widgets.PopupSelectWidget`（読み取り専用テキスト＋
    「選択」ボタン→ポップアップ）を使う。年・保存期間は原本でも素の`<select>`のため、
    Djangoの既定ウィジェットのままにしている。
    """

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
        queryset=RetentionPeriod.objects.filter(kbn="document", is_deleted=False).order_by("display_order"),
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
        current = datetime.date.today().year
        # 編集モード（DocumentEditView）では選択肢に対象の現在の年を必ず含める
        # （core.forms.year_choices_with_existingのdocstring参照。含めないと、直近ウィンドウ外の
        # 古い年を持つ文書を年欄に触れずに更新しただけで年が意図せず書き換わってしまう）。
        self.fields["year"].choices = year_choices_with_existing(self.initial.get("year"))
        self.fields["year"].initial = current
        # xlsx 保管!B78-82: 部署名欄「選択」ボタンは権限管理で権限が"管理者"のユーザのみ表示
        # （B79-81）。管理者以外はボタンを非表示にした上で自部署固定（読み取り専用）にする
        # （ボタン非表示はcore.widgets.PopupSelectWidget側。改ざん防止のためPOST値も無視し
        # view側で強制する）。
        # self.initial（Formのinitial=辞書）はself.fields[x].initialより解決時に優先されるため
        # （Django BaseForm.get_initial_for_field）、view側から渡されたinitial={"department": ...}を
        # 確実に上書きするにはここも更新する必要がある。
        if employee is not None and not can_select_department(employee):
            self.fields["department"].disabled = True
            self.initial["department"] = employee.department_id
        elif employee is not None and not edit_mode:
            # B82「初期値はログインユーザーの部署名をセット」は新規登録画面（管理者は「選択」
            # ボタンで別部署に変更可能）。編集画面は既存文書の部署をview側から渡すため、
            # ここで上書きしない（上書きすると、年欄で既に修正した「一切触れていないのに
            # 値が意図せず書き換わる」のと同種の事故になる。documents.views.DocumentEditView
            # は既存documentのdepartmentをinitialとして渡している）。
            self.initial["department"] = employee.department_id
        # xlsx 権限管理!B172-175(Rev1.1)「文書管理-文書-保存満了日変更」。OFFの場合、保存済み
        # 文書の保存期間は編集不可（新規保管時はまだ「保存済み」ではないため対象外）。
        if edit_mode and employee is not None and not can_edit_retention(employee):
            self.fields["retention_period"].disabled = True
        allowed_groups = visible_groups(employee, kind="document") if employee else None
        if allowed_groups is not None:
            qs = allowed_groups.filter(doc_kbn=DocKbn.DOCUMENT, is_deleted=False)
            self.fields["group"].queryset = qs
            self.fields["group"].widget.queryset = qs
        initial_titles = initial_titles or []
        for i in range(file_count):
            initial = initial_titles[i] if i < len(initial_titles) else ""
            self.fields[f"title_{i}"] = forms.CharField(
                label=f"文書タイトル({i + 1})", initial=initial, max_length=255
            )

    def titles(self, file_count):
        return [self.cleaned_data[f"title_{i}"] for i in range(file_count)]


MATCH_OR = "or"
MATCH_AND = "and"
MATCH_CHOICES = ((MATCH_OR, "いずれかを含む"), (MATCH_AND, "すべて含む"))

# RadioSelectのバインド済みフォームは、選択肢キーがdataに無いと（未送信時と区別が付かず）
# 一切checkedを付けない。SearchFormは初回アクセス時もrequest.GETで常時バインドする方針
# （accounts.services.filter_staff_querysetのコメント参照）のためinitialが効かず、
# 原本index.html:383,387,395が既定でchecked状態にしているラジオが未選択表示になっていた。
SEARCH_RADIO_DEFAULTS = {"title_match": MATCH_OR, "freeword_match": MATCH_OR, "save_day_kbn": "save"}


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
        if args and args[0] is not None:
            data = args[0].copy()
            for field_name, default in SEARCH_RADIO_DEFAULTS.items():
                data.setdefault(field_name, default)
            args = (data,) + args[1:]
        elif kwargs.get("data") is not None:
            data = kwargs["data"].copy()
            for field_name, default in SEARCH_RADIO_DEFAULTS.items():
                data.setdefault(field_name, default)
            kwargs["data"] = data
        super().__init__(*args, **kwargs)
        # xlsx 検索・閲覧・変更!B137-140「今年～文書が保存されている最古の年」（IntegerFieldでは
        # なくMultipleChoiceFieldなのはPopupSelectWidgetがリスト値を扱う都合上）。
        self.fields["year"].choices = search_year_choices(DocKbn.DOCUMENT)
        self.fields["retention_period"].queryset = used_retention_periods()

        if employee is not None and not can_select_department(employee):
            # 原本は行自体を消さず「選択」ボタンのみ非表示にする（index.html
            # select-dept-div表示切替）。フィールド自体は残しdisabled化し、
            # 自部署を読み取り専用表示する（widgetのボタン非表示はcore.widgets.PopupSelectWidget側）。
            # xlsx 検索・閲覧・変更!B48(Rev1.1)「閲覧部署範囲テーブルを参照し...自動セットする」。
            self.fields["department"].disabled = True
            self.fields["department"].initial = (
                visible_department_ids(employee) if employee.department_id else []
            )
        allowed_groups = visible_groups(employee, kind="document") if employee else None
        if allowed_groups is not None:
            qs = allowed_groups.filter(doc_kbn=DocKbn.DOCUMENT, is_deleted=False)
            self.fields["group"].queryset = qs
            self.fields["group"].widget.queryset = qs
