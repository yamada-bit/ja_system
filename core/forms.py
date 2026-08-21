import datetime
import logging
import re

from django import forms
from django.db.models import Min

from masters.models import SystemSetting
from organizations.models import MenuItemSetting

logger = logging.getLogger(__name__)

# xlsx その他設定!B152(Rev1.1)「半角英数6桁以上とする。記号、全角文字が含まれる場合は
# 更新時にエラーとする。」
_PASSWORD_PATTERN = re.compile(r"^[A-Za-z0-9]{6,}$")


def year_choices_with_existing(existing_year=None, ahead=1, behind=5):
    """screen-storage2「年」選択肢（documents/contracts.UploadStep2Form共通）。値のハードコードを
    避けるため実行時の直近年を基準に動的生成する（既定は現在年+1〜現在年-4の6件）。

    existing_yearには編集対象（DocumentEditView/ContractEditView）が現在保持している年を渡す。
    これが直近ウィンドウの外（保存期間が長く何年も前に登録された文書・契約書等）にある場合、
    値を外さず選択肢に追加する。追加しないと、その年に一致するoptionが存在せず<select>の
    どのoptionにもselected属性が付かない。HTML仕様上ブラウザはこの場合先頭のoptionを自動選択
    して表示してしまうため、利用者が年欄に一切触れずメモ欄修正等だけ行ってフォームを送信すると、
    年が意図せず（多くの場合、直近ウィンドウの最大値へ）書き換わってしまう
    （原本フィデリティ監査で発見。新規登録時はexisting_year=Noneのため従来通りの挙動）。
    """
    current = datetime.date.today().year
    years = list(range(current + ahead, current - behind, -1))
    if existing_year is not None and existing_year not in years:
        years.append(existing_year)
        years.sort(reverse=True)
    return [(y, f"{y} 年") for y in years]


def search_year_choices(kind):
    """screen-search「年」プルダウン／年選択ポップアップの選択肢（xlsx 検索・閲覧・変更
    !B137-140「対象年選択は…今年～文書が保存されている最古の年」、B499「※文書管理と同じ」で
    契約書も同一規則）。documents.forms.SearchForm/contracts.forms.SearchForm、および
    core.api.BaseOptionListAPIView（年選択ポップアップ）で共有する。`kind`は
    masters.DocKbnの値（"document"/"contract"）。
    """
    current = datetime.date.today().year
    oldest = _oldest_saved_year(kind)
    start = oldest if oldest is not None and oldest < current else current
    return [(y, f"{y} 年") for y in range(current, start - 1, -1)]


def _oldest_saved_year(kind):
    # documents/contractsはcore.formsを使う側なので、循環importを避けるためここで遅延import
    # する。ゴミ箱保管中(is_deleted=True)は「保存されている」対象から除く。
    if kind == "contract":
        from contracts.models import Contract

        return Contract.objects.filter(is_deleted=False).aggregate(Min("year"))["year__min"]
    from documents.models import Document

    return Document.objects.filter(is_deleted=False).aggregate(Min("year"))["year__min"]


class OtherPassForm(forms.Form):
    """screen-other-pass。原本は「現在のパスワード」を平文表示するが、ハッシュ化必須の規約上
    実際の値は表示不能（テンプレート側でマスク表示、ログイン画面と同種の必然的な逸脱）。
    確認用パスワードとの一致チェックはxlsx上に明記が無いが、確認欄を設ける目的そのもの
    （入力ミス検知）から見て当然必要な検証のため実装する。

    `employee`はview側から渡す想定（Rev1.1 xlsx その他設定!B150「現在のパスワードと同一の場合は
    更新時にエラーとする」の判定に、ハッシュ比較用の`check_password`が必要なため）。
    """

    new_password = forms.CharField(label="変更後パスワード", widget=forms.PasswordInput)
    new_password_confirm = forms.CharField(label="変更後パスワード(確認)", widget=forms.PasswordInput)

    def __init__(self, *args, employee=None, **kwargs):
        self.employee = employee
        super().__init__(*args, **kwargs)

    def clean_new_password(self):
        new_password = self.cleaned_data["new_password"]
        if not _PASSWORD_PATTERN.match(new_password):
            raise forms.ValidationError("パスワードは半角英数6桁以上で入力してください。")
        if self.employee is not None and self.employee.check_password(new_password):
            raise forms.ValidationError("現在のパスワードと同じパスワードは設定できません。")
        return new_password

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("new_password") and cleaned.get("new_password") != cleaned.get("new_password_confirm"):
            raise forms.ValidationError("変更後パスワードと確認用パスワードが一致しません。")
        return cleaned


class MenuItemSettingForm(forms.ModelForm):
    """screen-other-main-edit。"""

    class Meta:
        model = MenuItemSetting
        fields = [
            "show_search_document",
            "show_search_contract",
            "show_search_eapproval",
            "show_storage_document",
            "show_storage_contract",
        ]


class LogoutTimeForm(forms.ModelForm):
    """screen-other-logout-edit。"""

    class Meta:
        model = SystemSetting
        fields = ["session_idle_timeout_minutes"]
        widgets = {"session_idle_timeout_minutes": forms.TextInput(attrs={"style": "width:50px;"})}
        labels = {"session_idle_timeout_minutes": "時間(分)"}
