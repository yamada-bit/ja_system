import logging
import unicodedata

from django import forms

from masters.models import Category, DocKbn, Group, RetentionKbn, RetentionPeriod, RetentionPeriodUnit
from organizations.models import Department

logger = logging.getLogger(__name__)

DOC_KBN_CHOICES_WITH_ALL = [("", "(全て)")] + list(DocKbn.choices)


class GroupSearchForm(forms.Form):
    """screen-class-list検索パネル（xlsx 分類管理!B35-36(Rev1.1)「分類名はカテゴリー名の部分一致
    検索とする(スペース区切りの複合検索は考慮しない)」。旧仕様は分類名がプルダウン選択だったが、
    Rev1.1でCategorySearchForm.nameと同じテキスト部分一致検索に変更された）。

    `department`はRev1.2で追加（xlsx 分類管理!B35「「部署」プルダウン ※権限：管理者のみ表示」）。
    フィールド自体は常に定義するが、テンプレート側で管理者以外には表示しない
    （masters/views.py GroupListView.get, templates/masters/class_list.html参照）。
    """

    department = forms.ModelChoiceField(
        label="部署",
        queryset=Department.objects.order_by("branch_code", "section_code"),
        required=False,
        empty_label="(全て)",
        widget=forms.Select(attrs={"style": "padding:4px; width:150px;"}),
    )
    name = forms.CharField(
        label="分類名",
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "キーワード検索", "style": "padding:4px; width:150px;"}),
    )
    doc_kbn = forms.ChoiceField(
        label="書類管理区分",
        required=False,
        choices=DOC_KBN_CHOICES_WITH_ALL,
        widget=forms.Select(attrs={"style": "padding:4px; width:150px;"}),
    )


class GroupForm(forms.ModelForm):
    """screen-class-regist/edit。xlsx B119/B161「分類コードの重複登録・重複更新は不可」に対応。

    `department`はRev1.2で追加（xlsx 分類管理!B116「「部署」プルダウン ※権限：管理者のみ表示」）。
    `show_department=False`の場合はフィールド自体をself.fieldsから外し、呼び出し側
    （masters/views.py GroupRegistView/GroupEditView）が非管理者操作時に
    `form.instance.department = employee.department`を明示的にセットしてから保存する
    （permissions.forms.AuthorityEditFormのcontract_visible_departments扱いと同じパターン）。
    """

    # 原本index.html:2733-2759「書類管理区分」selectは空選択肢が無く、常に先頭の「文書管理」が
    # 暗黙に選択された状態（未選択で送信されることが無い）。Django ModelFormの既定では必須の
    # choiceフィールドにも自動でBLANK_CHOICE_DASH（---------）が追加され、原本に無い選択肢が
    # 増える上に未選択のまま送信すると必須エラーになってしまうため、choicesを明示して排除する。
    doc_kbn = forms.ChoiceField(label="書類管理区分", choices=DocKbn.choices)
    department = forms.ModelChoiceField(
        label="部署",
        queryset=Department.objects.order_by("branch_code", "section_code"),
        required=True,
        widget=forms.Select(attrs={"style": "padding:4px; width:150px;"}),
    )

    class Meta:
        model = Group
        fields = ["code", "name", "doc_kbn", "department"]
        labels = {"code": "分類コード", "name": "分類名", "doc_kbn": "書類管理区分", "department": "部署"}
        widgets = {"code": forms.TextInput(attrs={"style": "width:100px;"})}

    def __init__(self, *args, show_department=True, **kwargs):
        super().__init__(*args, **kwargs)
        if not show_department:
            del self.fields["department"]

    def clean_code(self):
        code = self.cleaned_data["code"]
        # xlsx 分類管理!B116(Rev1.1)「半角数字のみ許可する。(全角の場合は登録時に半角へ変換)」。
        code = unicodedata.normalize("NFKC", code)
        if not code.isdigit():
            raise forms.ValidationError("分類コードは数字のみ入力してください。")
        qs = Group.objects.filter(code=code, is_deleted=False)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("この分類コードは既に登録されています。")
        return code


class CategorySearchForm(forms.Form):
    """screen-cat-list検索パネル（xlsx B36「カテゴリー名の部分一致検索」）。

    `department`はRev1.2で追加（xlsx カテゴリー管理!B35「「部署」プルダウン ※権限：管理者のみ
    表示」）。GroupSearchForm.department参照。
    """

    department = forms.ModelChoiceField(
        label="部署",
        queryset=Department.objects.order_by("branch_code", "section_code"),
        required=False,
        empty_label="(全て)",
        widget=forms.Select(attrs={"style": "padding:4px; width:150px;"}),
    )
    name = forms.CharField(
        label="カテゴリー名",
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "キーワード検索", "style": "padding:4px; width:150px;"}),
    )
    group = forms.ModelChoiceField(
        label="分類",
        queryset=Group.objects.filter(is_deleted=False),
        required=False,
        empty_label="(全て)",
        widget=forms.Select(attrs={"style": "padding:4px; width:150px;"}),
    )
    doc_kbn = forms.ChoiceField(
        label="書類管理区分",
        required=False,
        choices=DOC_KBN_CHOICES_WITH_ALL,
        widget=forms.Select(attrs={"style": "padding:4px; width:150px;"}),
    )


class CategoryForm(forms.ModelForm):
    """screen-cat-regist/edit（xlsx B111「分類管理」メニューで設定した分類名リストを表示、
    B119/B155「カテゴリーコードの重複登録・重複更新は不可」）。

    `department`はRev1.2で追加（xlsx カテゴリー管理!B109「「部署」プルダウン ※権限：管理者のみ
    表示」）。GroupForm.department・show_departmentと同じパターン。
    """

    # GroupFormのdoc_kbnと同じ理由（原本index.html:2890-2923に空選択肢が無い）。
    doc_kbn = forms.ChoiceField(label="書類管理区分", choices=DocKbn.choices)
    department = forms.ModelChoiceField(
        label="部署",
        queryset=Department.objects.order_by("branch_code", "section_code"),
        required=True,
        widget=forms.Select(attrs={"style": "padding:4px; width:150px;"}),
    )

    class Meta:
        model = Category
        fields = ["code", "name", "group", "doc_kbn", "department"]
        labels = {
            "code": "カテゴリーコード", "name": "カテゴリー名", "group": "分類",
            "doc_kbn": "書類管理区分", "department": "部署",
        }
        widgets = {
            "code": forms.TextInput(attrs={"style": "width:100px;"}),
            "group": forms.Select(attrs={"style": "padding:4px; width:150px;"}),
        }

    def __init__(self, *args, show_department=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["group"].queryset = Group.objects.filter(is_deleted=False).order_by("code")
        # 「分類」も原本は空選択肢が無く常に先頭の分類が暗黙選択された状態のため、
        # ModelChoiceFieldの既定の空ラベル（'---------'）を明示的に外す。
        self.fields["group"].empty_label = None
        if not show_department:
            del self.fields["department"]

    def clean_code(self):
        code = self.cleaned_data["code"]
        # xlsx カテゴリー管理!B113(Rev1.1)「半角数字のみ許可する。(全角の場合は登録時に半角へ変換)」。
        code = unicodedata.normalize("NFKC", code)
        if not code.isdigit():
            raise forms.ValidationError("カテゴリーコードは数字のみ入力してください。")
        qs = Category.objects.filter(code=code, is_deleted=False)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("このカテゴリーコードは既に登録されています。")
        return code


PERIOD_UNIT_CHOICES = RetentionPeriodUnit.choices


class RetentionPeriodForm(forms.ModelForm):
    """screen-retention-regist-doc/edit-doc。kbn/doc_nameは一覧画面での選択状態からhidden経由で
    引き継ぐ（原本もタイトルのspanをJSで書き換えるだけで実質は遷移元の文脈依存）。
    xlsx B77/B191「保存期間・表示順の重複登録は不可」はモデルのUniqueConstraint
    （kbn, doc_name, display_order）で保証。「永年」選択時は数値クリア+readonly
    （B73、handlePermanent()相当のJSをテンプレート側で実装）。
    """

    # 原本index.html:3058-3099「期間単位」selectも空選択肢が無く、常に先頭の「ヵ月」が
    # 暗黙に選択された状態（GroupForm.doc_kbnと同じ理由）。
    period_unit = forms.ChoiceField(
        label="期間単位",
        choices=PERIOD_UNIT_CHOICES,
        widget=forms.Select(attrs={"onchange": "handlePermanent(this)", "style": "width:100px;"}),
    )

    class Meta:
        model = RetentionPeriod
        fields = ["kbn", "doc_name", "period_value", "period_unit", "display_order"]
        widgets = {
            "kbn": forms.HiddenInput(),
            "doc_name": forms.HiddenInput(),
            "period_value": forms.TextInput(attrs={"style": "width:50px;", "id": "save-period-txt"}),
            "display_order": forms.TextInput(attrs={"style": "width:50px;"}),
        }
        labels = {"period_value": "保存期間", "display_order": "表示順"}

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("period_unit") == RetentionPeriodUnit.PERMANENT:
            cleaned["period_value"] = None
        elif cleaned.get("period_value") in (None, ""):
            self.add_error("period_value", "「永年」以外を選択した場合は保存期間を入力してください。")
        return cleaned

    def clean_display_order(self):
        display_order = self.cleaned_data["display_order"]
        qs = RetentionPeriod.objects.filter(
            kbn=self.cleaned_data.get("kbn") or self.instance.kbn,
            doc_name=self.cleaned_data.get("doc_name", self.instance.doc_name),
            display_order=display_order,
            is_deleted=False,
        )
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("この表示順は既に使用されています。")
        return display_order
