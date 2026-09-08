import copy
import datetime
import logging
from decimal import Decimal, InvalidOperation

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
from masters.models import Category, DocKbn, Group
from organizations.models import Department
from organizations.services import visible_department_ids
from permissions.services import can_select_department, contract_searchable_department_ids

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

    新規保管（createモード）では複数契約書を一括選択した場合でもメタデータをファイルごとに
    個別入力する（2026-08-31ユーザー確定。詳細は documents.forms.UploadStep2Form docstring）。
    `PER_FILE_FIELDS`をファイル数ぶん複製して`{name}_{i}`に差し替える。編集モードは無添字のまま。
    """

    PER_FILE_FIELDS = (
        "department", "group", "category", "year", "contract_date", "contract_period_start",
        "contract_period_end", "renewal_date", "contract_amount", "contract_partner", "memo",
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
        self.file_count = file_count
        # createモードはメタデータ項目もファイルごと（{name}_{i}）。編集モードは無添字のまま。
        self.per_file_mode = not edit_mode
        current = datetime.date.today().year

        if self.per_file_mode:
            for name in self.PER_FILE_FIELDS:
                base_field = self.fields.pop(name)
                for i in range(file_count):
                    self.fields[f"{name}_{i}"] = copy.deepcopy(base_field)

        def fname(base, i):
            return f"{base}_{i}" if self.per_file_mode else base

        # xlsx 保管!P430,P459(Rev1.2)「分類/カテゴリー選択は…自部署の内容を表示」。
        group_qs, category_qs = scoped_group_and_category_querysets(
            doc_kbn=DocKbn.CONTRACT, kind="contract", employee=employee
        )

        for i in range(file_count):
            # documents.forms.UploadStep2Form.__init__と同じ理由（year_choices_with_existing
            # docstring）。編集モードは対象の現在の年を選択肢から外さない。createは常にNone。
            year_field = self.fields[fname("year", i)]
            year_field.choices = year_choices_with_existing(
                None if self.per_file_mode else self.initial.get("year")
            )
            year_field.initial = current

            # xlsx 保管!B412-416: 管理者以外は自部署固定＋「選択」ボタン非表示（欄は読み取り専用で
            # 表示）。self.initial は fields[x].initial より優先されるため（Django
            # BaseForm.get_initial_for_field）、view側initialを確実に上書きするにはここも更新する。
            dept_field = self.fields[fname("department", i)]
            if employee is not None and not can_select_department(employee):
                dept_field.disabled = True
                self.initial[fname("department", i)] = employee.department_id
            elif employee is not None and not edit_mode:
                # xlsx 保管!B82「初期値はログインユーザーの部署名をセット」は新規登録画面のみ。
                # setdefaultなのは「削除」後の再描画でview側が保持済み部署をinitialで渡すため
                # （2026-08-31、documents.forms.UploadStep2Formと同じ）。
                self.initial.setdefault(fname("department", i), employee.department_id)

            for base, qs in (("group", group_qs), ("category", category_qs)):
                f = self.fields[fname(base, i)]
                f.queryset = qs
                f.widget.queryset = qs

        initial_titles = initial_titles or []
        for i in range(file_count):
            initial = initial_titles[i] if i < len(initial_titles) else ""
            self.fields[f"title_{i}"] = forms.CharField(
                label=f"契約書タイトル({i + 1})", initial=initial, max_length=255
            )

    def clean(self):
        cleaned = super().clean()
        # 契約期間(開始)＞(終了)の逆転はほぼ入力ミスのため保存前に弾く（review_pending.txt No.3）。
        # createモードはフィールド名がファイルごとに{name}_{i}へ複製されている（__init__参照）。
        if self.per_file_mode:
            for i in range(self.file_count):
                validate_date_range(
                    self, f"contract_period_start_{i}", f"contract_period_end_{i}", label="契約期間"
                )
        else:
            validate_date_range(self, "contract_period_start", "contract_period_end", label="契約期間")
        return cleaned

    def file_data(self, i):
        """i番目のファイルとして保存するクリーン値の辞書（キーは PER_FILE_FIELDS ＋ "title"）。
        documents.forms.UploadStep2Form.file_data と同じ役割。"""
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
        # 実体はcore.forms.apply_radio_defaultsに集約済み（documents.forms.SearchFormとの重複を
        # コード監査で発見、2026-08-25修正）。
        args, kwargs = apply_radio_defaults(args, kwargs)
        # xlsx 検索・閲覧・変更!B416-418(Rev1.1)「部署名：ログインユーザーの部署を自動セット／
        # 閲覧部署範囲テーブルの旧部署もカンマ区切り」。管理者、および契約書-部門間閲覧設定ありの
        # 職員は部署欄が非disabled（＝「選択」ボタンあり）のため`field.initial`が描画されず
        # 空だった（documents.forms.SearchFormと同じ漏れ。core.forms.
        # apply_search_department_default のdocstring参照）。部門間閲覧設定の部署は「選択」で
        # 追加する対象であって自動セット対象ではない（B421-423は表示可否の規定）ため、
        # 自動セット値は visible_department_ids（自部署＋統合/分割スコープ）に限定する。
        own_dept_ids = (
            visible_department_ids(employee)
            if employee is not None and employee.department_id
            else []
        )
        args, kwargs = apply_search_department_default(args, kwargs, own_dept_ids)
        super().__init__(*args, **kwargs)
        # xlsx 検索・閲覧・変更!B499「※文書管理と同じ」（B137-140「今年～契約書が保存されている
        # 最古の年」）。
        self.fields["year"].choices = search_year_choices(DocKbn.CONTRACT)

        # contract_searchable_department_ids()は内部でDepartmentViewScope・
        # contract_visible_departments(M2M)の2クエリを発行するため、下のgroup/category絞り込みでも
        # 同じ範囲が必要な箇所（department_ids_for_group_scope(kind="contract")は内部でこの関数を
        # そのまま呼ぶだけ）は使い回す。以前は同じ内容を2回計算しており、検索画面を開くたびに
        # 本来2クエリで済むところを4クエリ発行していた（コード監査で発見、2026-08-24修正）。
        contract_dept_ids = contract_searchable_department_ids(employee) if employee is not None else None
        # views.SearchView.getが検索一覧クエリ（search_services.build_queryset）にも同じ範囲を
        # 渡して使い回せるよう、計算済みの値をフォームインスタンスに保持しておく（効率性レビューで
        # 発見：フォーム側で1回・build_queryset側でまた1回、計4クエリを検索画面表示のたびに
        # 発行していた。上のコメントが「2026-08-24修正」と主張していたのはフォーム内部の
        # 重複だけで、build_queryset側との重複は未解消だった。2026-08-25修正）。
        self.contract_dept_ids = contract_dept_ids
        if employee is not None and employee.department_id:
            allowed_ids = contract_dept_ids
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
        # xlsx 検索・閲覧・変更!P470,P507(Rev1.2)「分類/カテゴリー選択は…自部署の内容を表示」。
        # department_ids_for_group_scope(kind="contract")を経由せず、上で計算済みの
        # contract_dept_idsをそのまま使う（上のコメント参照）。
        group_qs, category_qs = scoped_group_and_category_querysets(
            doc_kbn=DocKbn.CONTRACT, kind="contract", employee=employee, dept_ids=contract_dept_ids
        )
        self.fields["group"].queryset = group_qs
        self.fields["group"].widget.queryset = group_qs
        self.fields["category"].queryset = category_qs
        self.fields["category"].widget.queryset = category_qs

    def clean(self):
        cleaned = super().clean()
        # documents.forms.SearchForm.clean と同じ（review_pending.txt No.3）。
        validate_date_range(self, "save_date_start", "save_date_end", label="期間")
        return cleaned
