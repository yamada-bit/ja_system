import logging
import unicodedata

from django.contrib.auth.forms import AuthenticationForm
from django import forms

from accounts.models import Employee, Position, Rank
from organizations.models import Department
from organizations.services import branch_choices, section_choices

logger = logging.getLogger(__name__)


class LoginForm(AuthenticationForm):
    """screen-loginに対応するログインフォーム。id属性をHTML確定版（`login-user`/`login-pass`）に
    合わせているのは、パスワード表示切替アイコンのJS（`pass-toggle-icon`）が
    `document.getElementById('login-pass')`を参照する構造をそのまま踏襲するため。
    """

    username = forms.CharField(
        label="職員番号",
        widget=forms.TextInput(attrs={"id": "login-user", "placeholder": "例：123456", "autofocus": True}),
    )
    password = forms.CharField(
        label="パスワード",
        widget=forms.PasswordInput(attrs={"id": "login-pass"}),
    )

    error_messages = {
        **AuthenticationForm.error_messages,
        "inactive": "退職済みの職員はログインできません。",
    }

    def confirm_login_allowed(self, user):
        """xlsx ログイン画面!B39-42「退職している職員はログイン不可とする」に対応。
        HTML確定版（プロトタイプJS）はこの照合ロジック自体を持たない（常にログイン成功する
        モック）ため、要確認事項として棚卸し表に記録した上でここで実装する。
        """
        if user.is_retired:
            logger.warning("退職済み職員のログイン試行: employee_no=%s", user.employee_no)
            raise forms.ValidationError(
                self.error_messages["inactive"],
                code="inactive",
            )
        super().confirm_login_allowed(user)


class StaffCsvImportForm(forms.Form):
    """screen-staff-list「CSV取込」（xlsx 職員マスタ!B93-95、Rev1.1でレイアウト画像に
    所属長フラグ列が追加された。accounts.csv_import_services.import_staff_csv参照）。"""

    csv_file = forms.FileField(label="取込用CSVファイル")

    def clean_csv_file(self):
        csv_file = self.cleaned_data["csv_file"]
        if not csv_file.name.lower().endswith(".csv"):
            raise forms.ValidationError("CSVファイル（拡張子.csv）を選択してください。")
        return csv_file


class StaffSearchForm(forms.Form):
    """screen-staff-list検索パネル（xlsx 職員マスタ!B44「氏名はスペース区切りの複合検索は不要」）。"""

    branch_code = forms.ChoiceField(
        label="本支所", required=False, choices=[],
        widget=forms.Select(attrs={"style": "padding:4px; width:150px;"}),
    )
    section_code = forms.ChoiceField(
        label="部課", required=False, choices=[],
        widget=forms.Select(attrs={"style": "padding:4px; width:150px;"}),
    )
    name = forms.CharField(
        label="氏名", required=False,
        widget=forms.TextInput(attrs={"placeholder": "キーワード検索", "style": "padding:4px; width:150px;"}),
    )
    include_retired = forms.BooleanField(label="退職者を含める", required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["branch_code"].choices = branch_choices()
        self.fields["section_code"].choices = section_choices()


class StaffRegistForm(forms.ModelForm):
    """screen-staff-regist。本支所/部課は原本では固定サンプルのプルダウンだが、xlsx注記
    （SCREENS_INVENTORY_WAVE2.md screen-staff-regist）通り実際のorganizations.Departmentから
    動的に選択肢を生成する。本支所→部課の連動選択はテンプレート側のJSで行い、このフォームは
    最終的に確定したDepartmentのpkのみをhidden inputとして受け取る（`department`フィールド）。

    パスワード入力欄は原本HTML自体に存在しない（xlsx B184「登録時のパスワード初期値はjaXXXX」の
    通り、ビュー側で自動生成してset_passwordする）。
    """

    department = forms.ModelChoiceField(
        label="所属部署", queryset=Department.objects.all(), widget=forms.HiddenInput()
    )
    # 原本index.html:1970,1987「(選択してください)」。Django ModelFormの既定のblank選択肢
    # （BLANK_CHOICE_DASH="---------"）のままだと原本の案内文言と食い違うため明示的に指定する。
    rank = forms.ChoiceField(label="職階", choices=[("", "(選択してください)")] + list(Rank.choices))
    position = forms.ChoiceField(label="役職", choices=[("", "(選択してください)")] + list(Position.choices))

    class Meta:
        model = Employee
        fields = ["employee_no", "name", "department", "rank", "position"]
        labels = {"employee_no": "職員番号", "name": "氏名", "rank": "職階", "position": "役職"}

    def clean_employee_no(self):
        employee_no = self.cleaned_data["employee_no"]
        # xlsx 職員マスタ!B173(Rev1.1)「半角数字のみ許可する。(全角の場合は登録時に半角へ変換)」。
        # NFKC正規化で全角数字を半角に変換した上で、数字以外が残っていればエラーとする。
        employee_no = unicodedata.normalize("NFKC", employee_no)
        if not employee_no.isdigit():
            raise forms.ValidationError("職員番号は数字のみ入力してください。")
        # xlsx 職員マスタ!B175(Rev1.1)「職員番号0000の登録も許可(可能)とする。※管理者扱いとしたい為」。
        # CharFieldの標準blank/requiredチェックは空文字列のみを弾くため、"0000"はここまで通過する。
        # xlsx 職員マスタ!B166「既に存在している職員番号の場合は登録時にエラーとする」。
        # unique=Trueでも保証されるが、ModelForm標準のエラー文言より分かりやすい文言にするため
        # 明示的にチェックする。
        if Employee.objects.filter(employee_no=employee_no).exists():
            raise forms.ValidationError("この職員番号は既に登録されています。")
        return employee_no

    def save(self, commit=True):
        employee = super().save(commit=False)
        # xlsx 職員マスタ!B184「登録時のパスワード初期値はja+職員番号下4桁」。
        initial_password = "ja" + employee.employee_no[-4:]
        employee.set_password(initial_password)
        if commit:
            employee.save()
        return employee


class StaffEditForm(forms.ModelForm):
    """screen-staff-edit。職員番号は原本では編集可能なテキスト入力に見えるが、ログインID
    （USERNAME_FIELD）の変更は影響範囲が大きく仕様上の裏付け（バリデーション・移行手順等）が
    どこにも無いため、表示のみ（編集不可）にする（無断で危険な仕様を追加しない判断）。

    パスワードは平文を画面に表示・保持しない（ハッシュ化必須というコーディング規約と、
    原本のダミー値プリフィルをそのまま持ち込まない、というログイン画面と同じ判断）。
    空欄のまま更新すればパスワードは変更されず、入力すれば新しいパスワードとして
    `set_password`する。「リセット」ボタン（`ja`+職員番号下4桁を入力欄にセットするのみ、
    実際の保存は更新ボタン押下時）はテンプレート側JSで原本と同じ挙動を再現する。
    """

    password = forms.CharField(
        label="パスワード", required=False, widget=forms.PasswordInput(render_value=False)
    )
    department = forms.ModelChoiceField(
        label="所属部署", queryset=Department.objects.all(), widget=forms.HiddenInput()
    )
    rank = forms.ChoiceField(label="職階", choices=[("", "(選択してください)")] + list(Rank.choices))
    position = forms.ChoiceField(label="役職", choices=[("", "(選択してください)")] + list(Position.choices))

    class Meta:
        model = Employee
        fields = ["name", "department", "rank", "position", "is_retired"]
        # xlsx記載は無いが、原本index.html:2130「退職(使用不可)」のラベル表記に合わせる
        # （ラベルのみで、機能〈退職フラグの手動設定〉自体は引き続き有効のまま。
        # 原本側にもdisabled属性は無く、機能を無効化する意図ではないと判断、2026-08-19ユーザー指示）。
        labels = {"name": "氏名", "rank": "職階", "position": "役職", "is_retired": "退職(使用不可)"}

    def save(self, commit=True):
        employee = super().save(commit=False)
        new_password = self.cleaned_data.get("password")
        if new_password:
            employee.set_password(new_password)
        if commit:
            employee.save()
        return employee
