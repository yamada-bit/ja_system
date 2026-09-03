import logging

from django import forms
from django.urls import reverse_lazy

from core.widgets import PopupSelectWidget
from organizations.models import Department
from organizations.services import branch_choices, section_choices

logger = logging.getLogger(__name__)

API_OPTIONS_URL = reverse_lazy("organizations:api_options")


class DeptSearchForm(forms.Form):
    """screen-dept-list検索パネル。原本の本支所/部課selectは選択肢のvalueが全て空文字という
    実装不備の静的モック（SCREENS_INVENTORY_WAVE2.md参照）だったため、実データから distinct な
    本支所コード・部課コードの選択肢を都度生成する（原本の見た目＝「本支所名」「部課名」の
    ドロップダウンという構造は維持しつつ、実際に絞り込める値を持たせる）。
    """

    branch_code = forms.ChoiceField(label="本支所", required=False, choices=[])
    section_code = forms.ChoiceField(label="部課", required=False, choices=[])

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["branch_code"].choices = branch_choices()
        self.fields["section_code"].choices = section_choices()


class DeptRegistForm(forms.ModelForm):
    """screen-dept-regist。xlsx 部署管理!B87「既に存在している"本支所コード+部課コード"の場合は
    登録時にエラーとする」はモデルの`UniqueConstraint`で保証される。B88「本支所コードと本支所名が
    既存で部課コードと部課名が無い場合は、その本支所への部課追加として新規登録する」は、
    本支所を独立テーブルに正規化していない設計（Department docstring参照）上、単に新しい
    Departmentレコードを1件作成するだけで自然に満たされる（特別な分岐は不要）。
    """

    class Meta:
        model = Department
        fields = ["branch_code", "branch_name", "section_code", "section_name"]
        labels = {
            "branch_code": "本支所コード",
            "branch_name": "本支所名",
            "section_code": "部課コード",
            "section_name": "部課名",
        }

    def clean(self):
        cleaned = super().clean()
        branch_code = cleaned.get("branch_code")
        section_code = cleaned.get("section_code")
        if branch_code and section_code:
            if Department.objects.filter(branch_code=branch_code, section_code=section_code).exists():
                raise forms.ValidationError(
                    "指定の本支所コード・部課コードの組み合わせは既に登録されています。"
                )
        return cleaned


class DeptEditForm(forms.ModelForm):
    """screen-dept-edit。xlsx 部署管理!B107「各名称のみ、変更可とする」に対応し、コード類は
    フォームに含めない（テンプレート側で表示のみ）。

    「部署統合・分割」（ラジオ+ポップアップでの対象部署選択）はRev1.1で仕様が確定した
    （部署管理!B209-212「統合/分割前の部署分も閲覧可能なように、閲覧部署範囲テーブルを更新する」）。
    実際の閲覧部署範囲テーブル更新はorganizations.services.apply_dept_action（view側でform.save()後に
    呼ぶ）が行うため、本フォームは`dept_action`が`merge`/`split`の場合に`dept_action_target`が
    最低1件選択されていること・編集中の部署自体を含まないことを検証する。統合・分割の対象ポップアップ
    にも編集中の部署は出さない（__init__参照。2026-09-03ユーザー依頼）。
    """

    dept_action = forms.ChoiceField(
        label="部署統合・分割",
        choices=[("none", "通常"), ("merge", "統合する"), ("split", "分割する")],
        initial="none",
        required=False,
        widget=forms.RadioSelect,
    )
    # 原本index.html `openPopupPopup(this, 'dept', 'search')`（mode='search'）をそのまま踏襲。
    # このmodeはJS側でチェックボックス（複数選択）のポップアップになるためMultipleChoiceFieldにする。
    # 選択結果はview側のapply_dept_action（閲覧部署範囲テーブル更新）で実際に使う（Rev1.1で確定）。
    dept_action_target = forms.ModelMultipleChoiceField(
        label="対象部署",
        queryset=Department.objects.all(),
        required=False,
        widget=PopupSelectWidget(
            popup_type="dept", mode="search", api_url=API_OPTIONS_URL, queryset=Department.objects.all(), multi=True,
            display_attrs="",
        ),
    )

    class Meta:
        model = Department
        fields = ["branch_name", "section_name"]
        labels = {"branch_name": "本支所名", "section_name": "部課名"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 統合・分割の対象部署ポップアップから「編集中の部署自体」を除外する。統合は存続部署A
        # の編集画面で吸収される部署Bを選ぶ、分割は分割元の部署Bの編集画面で分割先を選ぶ運用の
        # ため、いずれも編集中の部署自体は選択肢に出さない（2026-09-03ユーザー依頼）。
        # clean()の自己参照チェックはAPI直叩き・パラメータ改ざんに対する多重防御として残す。
        # extra_queryは組み立て済みのapi_urlに`?exclude=<pk>`を付け、ポップアップ本体を描画する
        # organizations.api.OptionListAPIView側でも同じ部署を除外させる（フォームのqueryset
        # 差し替えだけではpopup-selectが直接APIを叩くため効かない。permissions側doc_kbnと同じ方式）。
        if self.instance.pk:
            self.fields["dept_action_target"].queryset = Department.objects.exclude(
                pk=self.instance.pk
            )
            self.fields["dept_action_target"].widget.extra_query = {"exclude": self.instance.pk}

    def clean(self):
        cleaned = super().clean()
        action = cleaned.get("dept_action")
        if action in ("merge", "split"):
            targets = cleaned.get("dept_action_target")
            if not targets:
                target_label = "統合する部署" if action == "merge" else "分割する部署"
                raise forms.ValidationError(f"{target_label}を選択してください。")
            if self.instance.pk and any(t.pk == self.instance.pk for t in targets):
                raise forms.ValidationError("対象部署にこの部署自体は選択できません。")
        return cleaned
