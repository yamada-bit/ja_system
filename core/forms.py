import datetime
import logging
import re

from django import forms
from django.db.models import Min

from masters.models import Category, Group, SystemSetting
from masters.services import scope_queryset_by_department
from organizations.models import MenuItemSetting
from permissions.services import department_ids_for_group_scope, visible_groups

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


# dept_idsの「未指定（呼び出し側で計算させる）」と「Noneが明示的な計算結果（管理者＝無制限）」を
# 区別するためのセンチネル。第二引数の既定値をNoneにすると、既に計算済みの管理者(None)を
# 渡されたときに二重計算してしまう（dept_ids=Noneはそれ自体が有効な値のため）。
_DEPT_IDS_UNSET = object()


def scoped_group_and_category_querysets(*, doc_kbn, kind, employee, dept_ids=_DEPT_IDS_UNSET):
    """documents.forms/contracts.formsのUploadStep2Form・SearchFormが共通で必要とする
    「保管/検索フォームで選択できる分類(masters.Group)・カテゴリー(masters.Category)」の
    クエリセットを2段階で絞り込んで返す（4フォームでほぼ同一のブロックが独立実装されて
    いた重複を解消。コード監査で発見、2026-08-25修正）。

    1. `permissions.services.visible_groups`（所属長への分類ホワイトリスト設定、
       PermissionProfile.doc_visible_groups/contract_visible_groups）。未設定なら無制限。
    2. Rev1.2の部署スコープ（`permissions.services.department_ids_for_group_scope`、
       非管理者は自部署のみ）。

    2は1の結果に対してAND条件で適用するため、1で他部署の分類を明示的に許可していても
    2で対象外部署なら最終的に除外される。この優先順位はユーザーへ確認済み
    （Rev1.2「分類/カテゴリー選択は…自部署の内容を表示」を字義通りの仕様として扱い、
    doc_visible_groups側の他部署許可より部署スコープを常に優先する。2026-08-25確認）。

    `dept_ids`を明示的に渡さない場合は`department_ids_for_group_scope(employee, kind=kind)`で
    都度計算する。contracts.forms.SearchFormのみ、`contract_searchable_department_ids`の
    重複クエリ発行を避けるため呼び出し側で事前計算した値（管理者ならNoneそのもの）を渡す
    （同関数のコメント参照）。
    """
    allowed_groups = visible_groups(employee, kind=kind) if employee is not None else None
    group_qs = allowed_groups if allowed_groups is not None else Group.objects.all()
    group_qs = group_qs.filter(doc_kbn=doc_kbn, is_deleted=False)
    category_qs = Category.objects.filter(doc_kbn=doc_kbn, is_deleted=False)
    if employee is not None:
        if dept_ids is _DEPT_IDS_UNSET:
            dept_ids = department_ids_for_group_scope(employee, kind=kind)
        group_qs = scope_queryset_by_department(group_qs, dept_ids)
        category_qs = scope_queryset_by_department(category_qs, dept_ids)
    return group_qs, category_qs


# 検索フォームのタイトル/フリーワードの一致方式（AND/OR切替）。documents.forms.SearchForm/
# contracts.forms.SearchFormが定数ごと完全に同一実装のまま重複していたため集約した
# （品質レビューで発見、2026-08-25修正）。
MATCH_OR = "or"
MATCH_AND = "and"
MATCH_CHOICES = ((MATCH_OR, "いずれかを含む"), (MATCH_AND, "すべて含む"))

# RadioSelectのバインド済みフォームは、選択肢キーがdataに無いと（未送信時と区別が付かず）
# 一切checkedを付けない。SearchFormは初回アクセス時もrequest.GETで常時バインドする方針
# （accounts.services.filter_staff_querysetのコメント参照）のためinitialが効かず、
# 原本index.html:383,387,395が既定でchecked状態にしているラジオが未選択表示になっていた。
SEARCH_RADIO_DEFAULTS = {"title_match": MATCH_OR, "freeword_match": MATCH_OR, "save_day_kbn": "save"}


def apply_radio_defaults(args, kwargs):
    """documents.forms.SearchForm.__init__/contracts.forms.SearchForm.__init__が共通で行う、
    RadioSelectの既定checked値の補完処理（SEARCH_RADIO_DEFAULTS参照）を集約した
    （品質レビューで発見、2026-08-25修正）。フォームの`__init__(self, *args, **kwargs)`の
    冒頭で`args, kwargs = apply_radio_defaults(args, kwargs)`のように呼び出し、
    戻り値をそのまま`super().__init__(*args, **kwargs)`に渡す。
    """
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
    return args, kwargs


def apply_search_department_default(args, kwargs, department_ids):
    """screen-search（文書/契約書）の検索フォームで、部署名欄にログインユーザーの部署を
    既定セットする（xlsx 検索・閲覧・変更!B47,B417「・ログインユーザーの部署を自動セットする。」
    ＋B48,B418〈Rev1.1、閲覧部署範囲テーブルの旧部署もカンマ区切り〉、原本 index.html:336
    `#search-dept value="総務部"` の静的プリフィルに対応）。

    `apply_radio_defaults`と同じ理由で、`initial`ではなくバインド済みdataへ補完する必要がある：
    SearchFormはSearchViewが初回アクセス時もrequest.GETで常時バインドする方針
    （accounts.services.filter_staff_querysetのコメント参照）のため、disabledでないフィールド
    （＝部署名「選択」ボタンを持つ管理者の部署欄）は`field.initial`が描画に反映されない。
    非管理者は`department`フィールドがdisabled＋`field.initial`済みでこの補完が無くても描画
    されるが、管理者だけ部署欄が空になっていた（保管画面は同種の漏れをARCHIVE「Rev1.1反映」で
    修正済みだったが検索フォーム側へ横展開されていなかった）。値の生成元を一本化するため
    両ロールともこの経路を通す。

    `department`キーがdataに無いときだけ補うので、「選択」ポップアップで部署を選んで検索した
    場合（request.GETにdepartmentあり）や「条件クリア」（クエリ無し＝この既定に戻る）は
    従来どおり。`department_ids`が空（退職者・部署未設定等）なら何もしない。
    `apply_radio_defaults`の後に呼び出し、戻り値をそのまま`super().__init__`へ渡す。
    """
    if not department_ids:
        return args, kwargs
    joined = ",".join(str(i) for i in department_ids)
    if args and args[0] is not None:
        data = args[0].copy()
        data.setdefault("department", joined)
        args = (data,) + args[1:]
    elif kwargs.get("data") is not None:
        data = kwargs["data"].copy()
        data.setdefault("department", joined)
        kwargs["data"] = data
    return args, kwargs


class OtherPassForm(forms.Form):
    """screen-other-pass。「現在のパスワード」欄はRev1.5(原本html6)で画面から削除された
    （それ以前は原本が平文表示、ja_pjはハッシュ化必須の規約でマスク表示していた）。ただし
    「変更後パスワードが現在のものと同一ならエラー」の検証（下記clean_new_password）は
    xlsx その他設定!B150（Rev1.5でも健在）に基づき維持する。
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
