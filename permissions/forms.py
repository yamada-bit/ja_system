import logging

from django import forms
from django.urls import reverse_lazy

from core.widgets import PopupSelectWidget
from masters.models import DocKbn, Group
from organizations.models import Department
from permissions.models import PermissionProfile, PermissionRole

logger = logging.getLogger(__name__)

API_OPTIONS_URL = reverse_lazy("permissions:api_options")


class AuthoritySearchForm(forms.Form):
    """screen-authority-list検索パネル（xlsx 権限管理!B39「氏名はスペース区切りの複合検索は不要」）。"""

    department = forms.ModelChoiceField(
        label="部署",
        # 他の部署プルダウン（accounts/forms.py, organizations/api.py, core/api.py等）と同じく
        # 本支所コード→部課コード順に統一する。
        queryset=Department.objects.order_by("branch_code", "section_code"),
        required=False,
        empty_label="(全て)",
        widget=forms.Select(attrs={"style": "padding:4px; width:150px;"}),
    )
    name = forms.CharField(
        label="氏名",
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "キーワード検索", "style": "padding:4px; width:150px;"}),
    )


# 権限管理編集フォームのON/OFFチェックボックス項目（xlsx 権限管理シート、Rev1.1でB167-215に再編）。
# 原本index.html:2555-2565（screen-authority-edit）の列順「文書-保存満了日変更／文書-ダウンロード／
# 契約書-ダウンロード／電子決裁3項目」に合わせている（部門間閲覧設定・分類表示は複数選択のため
# 別途_MULTI_FIELDSで扱う）。
_FLAG_FIELDS = [
    "doc_retention_edit",
    "doc_download",
    "contract_edit",
    "contract_download",
    "eapproval_view_setting",
    "eapproval_doc_name_manage",
    "eapproval_retention",
]

_MULTI_FIELDS = ["doc_visible_groups", "contract_visible_departments", "contract_visible_groups"]


class AuthorityEditForm(forms.ModelForm):
    """screen-authority-edit。フラグの意味を解釈する連動ロジックはpermissions/services.pyに
    集約する方針（本フォームはHTML確定版通りの入力項目をそのまま保存する）。
    """

    class Meta:
        model = PermissionProfile
        fields = ["role"] + _FLAG_FIELDS + _MULTI_FIELDS
        labels = {"role": "システム権限"}
        widgets = {
            "doc_visible_groups": PopupSelectWidget(
                popup_type="group",
                mode="search",
                api_url=API_OPTIONS_URL,
                extra_query={"doc_kbn": DocKbn.DOCUMENT},
                queryset=Group.objects.filter(doc_kbn=DocKbn.DOCUMENT, is_deleted=False),
                label_func=lambda g: g.name,
                multi=True,
                display_attrs='style="width:200px; display:inline-block;"',
            ),
            "contract_visible_departments": PopupSelectWidget(
                popup_type="dept",
                mode="search",
                api_url=API_OPTIONS_URL,
                queryset=Department.objects.all(),
                multi=True,
                display_attrs='style="width:200px; display:inline-block;"',
            ),
            "contract_visible_groups": PopupSelectWidget(
                popup_type="group",
                mode="search",
                api_url=API_OPTIONS_URL,
                extra_query={"doc_kbn": DocKbn.CONTRACT},
                queryset=Group.objects.filter(doc_kbn=DocKbn.CONTRACT, is_deleted=False),
                label_func=lambda g: g.name,
                multi=True,
                display_attrs='style="width:200px; display:inline-block;"',
            ),
        }

    def __init__(self, *args, editable_roles=None, show_contract_visible_departments=True, **kwargs):
        """editable_rolesを指定すると`role`フィールドの選択肢をその値に絞り込む
        （xlsx 権限管理!B113/115「所属長はロールを"職員(一般)"のみ選択可」）。ChoiceFieldの
        `choices`自体を絞るため、選択肢に無い値をPOSTしても`is_valid()`が弾く
        （テンプレート側の見た目の絞り込みだけに頼らない）。

        `show_contract_visible_departments=False`の場合は`contract_visible_departments`
        フィールド自体をself.fieldsから取り除く（xlsx 権限管理!H182「※権限：管理者のみ表示」、
        Rev1.2で追加。以前は管理者・所属長どちらも編集可能だった）。ModelForm._save_m2m()は
        self.fieldsに存在しないM2Mフィールドを保存対象から除外するため、テンプレート側で
        非表示にするだけでなくフォーム自体から外すことで、所属長がPOSTデータを直接細工しても
        この項目を変更できないようにする（サーバー側での強制）。
        """
        super().__init__(*args, **kwargs)
        for name in _FLAG_FIELDS:
            self.fields[name].label = self.instance._meta.get_field(name).verbose_name
        for name in _MULTI_FIELDS:
            self.fields[name].required = False
        if not show_contract_visible_departments:
            del self.fields["contract_visible_departments"]
        if editable_roles is not None:
            self.fields["role"].choices = [
                choice for choice in PermissionRole.choices if choice[0] in editable_roles
            ]
