import datetime
import logging
from decimal import Decimal, InvalidOperation

from django import forms
from django.urls import reverse_lazy

from core.forms import search_year_choices, year_choices_with_existing
from core.widgets import InlineRadioSelect, PopupSelectWidget
from masters.models import Category, DocKbn, Group
from organizations.models import Department
from permissions.services import can_select_department, contract_searchable_department_ids, visible_groups

logger = logging.getLogger(__name__)

API_OPTIONS_URL = reverse_lazy("contracts:api_options")


class CommaNumberInput(forms.TextInput):
    """契約金額欄（screen-storage2.html98、原本のformatCurrency()による3桁カンマ区切り表示）用。
    送信時はJSのonblurカンマ整形に関わらずvalue_from_datadictでカンマを除去してから
    DecimalField.to_python()に渡す。表示側（初期値・バリデーションエラー再表示時）は
    onblurが一度も発火していないとカンマ無しの素の数字のまま表示されてしまう（監査で発見：
    編集画面を開いた直後の契約金額欄が「1200000」のままで、原本の「1,200,000」相当の
    見た目にならなかった）ため、format_valueでも同じ3桁カンマ整形を行う。
    """

    def value_from_datadict(self, data, files, name):
        raw = super().value_from_datadict(data, files, name)
        return raw.replace(",", "") if raw else raw

    def format_value(self, value):
        value = super().format_value(value)
        if not value:
            return value
        try:
            number = Decimal(value)
        except InvalidOperation:
            return value
        return f"{number:,.0f}"


class UploadStep2Form(forms.Form):
    """screen-storage2（契約書モード）。documents.forms.UploadStep2Formと同じ考え方だが、
    保存期間の選択式フィールドが無く（固定10年、contracts.services.calculate_expiry_date）、
    契約特有項目（契約日・契約期間・契約更新日・契約金額・契約先名）を持つ。
    部署/分類/カテゴリーは原本通り`core.widgets.PopupSelectWidget`を使う。
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
        queryset=Group.objects.filter(doc_kbn=DocKbn.CONTRACT, is_deleted=False),
        required=True,
        widget=PopupSelectWidget(
            popup_type="group",
            mode="storage",
            api_url=API_OPTIONS_URL,
            queryset=Group.objects.filter(doc_kbn=DocKbn.CONTRACT, is_deleted=False),
            label_func=lambda g: g.name,
        ),
    )
    category = forms.ModelChoiceField(
        label="カテゴリー",
        queryset=Category.objects.filter(doc_kbn=DocKbn.CONTRACT, is_deleted=False),
        required=True,
        widget=PopupSelectWidget(
            popup_type="category",
            mode="storage",
            api_url=API_OPTIONS_URL,
            queryset=Category.objects.filter(doc_kbn=DocKbn.CONTRACT, is_deleted=False),
            label_func=lambda c: c.name,
        ),
    )
    # documents.forms.UploadStep2Form.year参照（原本は固定<select>だが、値のハードコードは
    # 避け実行時に直近年の選択肢を生成する）。
    year = forms.TypedChoiceField(
        label="年",
        required=True,
        choices=[],
        coerce=int,
        widget=forms.Select(attrs={"class": "size-short"}),
    )
    contract_date = forms.DateField(
        label="契約日", required=False, widget=forms.DateInput(attrs={"type": "date", "class": "size-medium"})
    )
    contract_period_start = forms.DateField(
        label="契約期間(開始)", required=False, widget=forms.DateInput(attrs={"type": "date", "class": "size-medium"})
    )
    contract_period_end = forms.DateField(
        label="契約期間(終了)", required=False, widget=forms.DateInput(attrs={"type": "date", "class": "size-medium"})
    )
    renewal_date = forms.DateField(
        label="契約更新日", required=False, widget=forms.DateInput(attrs={"type": "date", "class": "size-medium"})
    )
    contract_amount = forms.DecimalField(
        label="契約金額",
        required=False,
        max_digits=12,
        decimal_places=0,
        widget=CommaNumberInput(attrs={"onblur": "formatCurrency(this)", "style": "width:150px; display:inline-block;"}),
    )
    contract_partner = forms.CharField(label="契約先名", required=False, max_length=255)
    memo = forms.CharField(
        label="メモ",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "備考・補足事項等を入力"}),
    )

    def __init__(self, *args, employee=None, file_count=1, initial_titles=None, edit_mode=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.employee = employee
        current = datetime.date.today().year
        # documents.forms.UploadStep2Form.__init__と同じ理由（core.forms.year_choices_with_existing
        # のdocstring参照）。編集モード（ContractEditView）では対象の現在の年を選択肢から
        # 外さないことで、年欄に触れずに更新しただけで年が意図せず書き換わる事故を防ぐ。
        self.fields["year"].choices = year_choices_with_existing(self.initial.get("year"))
        self.fields["year"].initial = current
        # xlsx 保管!B412-416: documents.forms.UploadStep2Formと同じ理由。管理者以外は自部署固定とし、
        # 「選択」ボタンのみ非表示にする（欄自体は表示したまま読み取り専用にする。ボタン非表示は
        # core.widgets.PopupSelectWidget側）。self.initial（Formのinitial=辞書）はself.fields[x].
        # initialより解決時に優先されるため（Django BaseForm.get_initial_for_field）、view側から
        # 渡されたinitial={"department": ...}を確実に上書きするにはここも更新する必要がある。
        if employee is not None and not can_select_department(employee):
            self.fields["department"].disabled = True
            self.initial["department"] = employee.department_id
        elif employee is not None and not edit_mode:
            # documents.forms.UploadStep2Form.__init__と同じ理由（xlsx 保管!B82「初期値は
            # ログインユーザーの部署名をセット」は新規登録画面のみ。編集画面は既存契約書の
            # 部署をContractEditView._build_formがinitialで渡すため、ここで上書きしない）。
            self.initial["department"] = employee.department_id
        allowed_groups = visible_groups(employee, kind="contract") if employee else None
        if allowed_groups is not None:
            qs = allowed_groups.filter(doc_kbn=DocKbn.CONTRACT, is_deleted=False)
            self.fields["group"].queryset = qs
            self.fields["group"].widget.queryset = qs
        initial_titles = initial_titles or []
        for i in range(file_count):
            initial = initial_titles[i] if i < len(initial_titles) else ""
            self.fields[f"title_{i}"] = forms.CharField(
                label=f"契約書タイトル({i + 1})", initial=initial, max_length=255
            )

    def titles(self, file_count):
        return [self.cleaned_data[f"title_{i}"] for i in range(file_count)]


MATCH_OR = "or"
MATCH_AND = "and"
MATCH_CHOICES = ((MATCH_OR, "いずれかを含む"), (MATCH_AND, "すべて含む"))

# documents.forms.SEARCH_RADIO_DEFAULTS参照。バインド済みRadioSelectはdataにキーが
# 無いとchecked無しになるため、原本index.htmlの既定checked状態を補う。
SEARCH_RADIO_DEFAULTS = {"title_match": MATCH_OR, "freeword_match": MATCH_OR, "save_day_kbn": "save"}


class SearchForm(forms.Form):
    """screen-search（契約書モード）の検索条件フォーム。部署/分類/年/カテゴリーは複数選択
    ポップアップ（documents.forms.SearchForm参照）。"""

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
        queryset=Group.objects.filter(doc_kbn=DocKbn.CONTRACT, is_deleted=False),
        required=False,
        widget=PopupSelectWidget(
            popup_type="group",
            mode="search",
            api_url=API_OPTIONS_URL,
            queryset=Group.objects.filter(doc_kbn=DocKbn.CONTRACT, is_deleted=False),
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
        queryset=Category.objects.filter(doc_kbn=DocKbn.CONTRACT, is_deleted=False),
        required=False,
        widget=PopupSelectWidget(
            popup_type="category",
            mode="search",
            api_url=API_OPTIONS_URL,
            queryset=Category.objects.filter(doc_kbn=DocKbn.CONTRACT, is_deleted=False),
            label_func=lambda c: c.name,
            multi=True,
        ),
    )
    title = forms.CharField(
        label="契約書タイトル",
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

    def __init__(self, *args, employee=None, **kwargs):
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
        # xlsx 検索・閲覧・変更!B499「※文書管理と同じ」（B137-140「今年～契約書が保存されている
        # 最古の年」）。
        self.fields["year"].choices = search_year_choices(DocKbn.CONTRACT)

        if employee is not None and employee.department_id:
            allowed_ids = contract_searchable_department_ids(employee)
            if allowed_ids is not None:
                # xlsx 検索・閲覧・変更!B417-418,421-423(Rev1.1)「閲覧部署範囲テーブルを参照し...
                # 自動セットする」「権限が"管理者"。または契約書-部門間閲覧設定に設定がある場合に
                # 表示。」。管理者以外は選べる部署自体を自部署＋閲覧部署範囲＋権限管理で許可された
                # 部署に限定する（「選択」ボタンは契約書-部門間閲覧設定が1件以上あれば表示する）。
                allowed_qs = Department.objects.filter(pk__in=allowed_ids)
                self.fields["department"].queryset = allowed_qs
                self.fields["department"].widget.queryset = allowed_qs
                self.fields["department"].initial = list(allowed_ids)
                if not can_select_department(employee, kind="contract"):
                    self.fields["department"].disabled = True
        allowed_groups = visible_groups(employee, kind="contract") if employee else None
        if allowed_groups is not None:
            qs = allowed_groups.filter(doc_kbn=DocKbn.CONTRACT, is_deleted=False)
            self.fields["group"].queryset = qs
            self.fields["group"].widget.queryset = qs
