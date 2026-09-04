import logging

from django import forms
from django.urls import reverse_lazy

from core.widgets import PopupSelectWidget
from masters.models import DocKbn, Group
from organizations.models import Department
from permissions.models import FLAG_FIELDS, MULTI_FIELDS, PermissionProfile, PermissionRole
from permissions.services import would_orphan_admins

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
# 別途_MULTI_FIELDSで扱う）。permissions.models.FLAG_FIELDS/MULTI_FIELDSが単一の情報源
# （accounts.services.reset_permission_profile_if_neededの安全側リセット対象と共有、
# 2026-08-24重複解消）のため、ここではエイリアスとして参照するだけにする。
_FLAG_FIELDS = FLAG_FIELDS
_MULTI_FIELDS = MULTI_FIELDS


class AuthorityEditForm(forms.ModelForm):
    """screen-authority-edit。フラグの意味を解釈する連動ロジックはpermissions/services.pyに
    集約する方針（本フォームはHTML確定版通りの入力項目をそのまま保存する）。
    """

    class Meta:
        model = PermissionProfile
        fields = ["role"] + _FLAG_FIELDS + _MULTI_FIELDS
        labels = {"role": "システム権限"}
        widgets = {
            # 簡易設計指示書 Rev1.3（権限管理!AI89「画面変更」）で、この3欄の表示用要素が1行inputから
            # 複数行textareaに変更された（選択した分類・部署がカンマ区切りで長くなっても全件見えるように）。
            # display_multiline=True＋vertical-align:topで「選択」ボタンをtextarea上端に揃える。
            "doc_visible_groups": PopupSelectWidget(
                popup_type="group",
                mode="search",
                api_url=API_OPTIONS_URL,
                extra_query={"doc_kbn": DocKbn.DOCUMENT},
                queryset=Group.objects.filter(doc_kbn=DocKbn.DOCUMENT, is_deleted=False),
                label_func=lambda g: g.name,
                multi=True,
                display_multiline=True,
                display_attrs='style="width:200px; display:inline-block; vertical-align:top;"',
            ),
            "contract_visible_departments": PopupSelectWidget(
                popup_type="dept",
                mode="search",
                api_url=API_OPTIONS_URL,
                queryset=Department.objects.all(),
                multi=True,
                display_multiline=True,
                display_attrs='style="width:200px; display:inline-block; vertical-align:top;"',
            ),
            "contract_visible_groups": PopupSelectWidget(
                popup_type="group",
                mode="search",
                api_url=API_OPTIONS_URL,
                extra_query={"doc_kbn": DocKbn.CONTRACT},
                queryset=Group.objects.filter(doc_kbn=DocKbn.CONTRACT, is_deleted=False),
                label_func=lambda g: g.name,
                multi=True,
                display_multiline=True,
                display_attrs='style="width:200px; display:inline-block; vertical-align:top;"',
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
        # Django の ModelForm は blank=True でない CharField(choices) でも、default も initial も
        # 無い場合に空選択肢 ("", "---------") を自動付与する（Field.formfield の include_blank）。
        # xlsx 権限管理!B113-115 はシステム権限を「1:管理者/2:所属長/3:職員 から選択」と定めており
        # 空欄は選択肢に無いため、editable_roles 未指定（管理者が編集）でも必ず PermissionRole の
        # 3値のみに絞る。以前は editable_roles 指定時（所属長が編集）しか choices を上書きしておらず、
        # 管理者編集時のプルダウンに `---------` が出ていた（2026-09-02 ユーザー報告）。
        allowed_roles = editable_roles if editable_roles is not None else {c[0] for c in PermissionRole.choices}
        self.fields["role"].choices = [
            choice for choice in PermissionRole.choices if choice[0] in allowed_roles
        ]

    def clean_role(self):
        """xlsx 権限管理!B222-223「[重要]システム権限の"管理者"が0人にならないようにチェックを掛ける。
        …他の職員を先に"管理者"に設定する必要がある旨、メッセージを表示し更新を中止する」。

        `self.instance.role` はこの時点ではまだ DB の現在値（_post_clean で cleaned_data が
        instance へ反映される前）なので、「現在は管理者だが管理者以外へ下げようとしている」判定に使える。
        """
        new_role = self.cleaned_data["role"]
        if self.instance.pk and would_orphan_admins(self.instance, new_role):
            raise forms.ValidationError(
                "システム権限「管理者」はシステム全体で1人以上必須です。"
                "他の職員を先に「管理者」に設定してから変更してください。"
            )
        return new_role
