import logging

from django import forms

logger = logging.getLogger(__name__)


class AuditLogSearchForm(forms.Form):
    """screen-log-list検索パネル（xlsx 操作履歴ログ!B36職員番号完全一致、B39職員名部分一致
    〈Rev1.1で全角スペース区切りのフルネーム検索に対応〉、B42イベントメッセージ〈Rev1.1で
    スペース区切りのAND検索に対応〉）。"""

    date_start = forms.DateField(
        label="操作日(開始)", required=False, widget=forms.DateInput(attrs={"type": "date", "style": "width:140px;"})
    )
    date_end = forms.DateField(
        label="操作日(終了)", required=False, widget=forms.DateInput(attrs={"type": "date", "style": "width:140px;"})
    )
    employee_no = forms.CharField(
        label="職員番号",
        required=False,
        widget=forms.TextInput(attrs={"style": "padding:4px; width:50px;"}),
    )
    employee_name = forms.CharField(
        label="職員名",
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "キーワード検索", "style": "padding:4px; width:150px;"}),
    )
    event_message = forms.CharField(
        label="イベントメッセージ",
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "キーワード検索", "style": "padding:4px; width:150px;"}),
    )
    personal_info_flag = forms.BooleanField(label="個人情報書類", required=False)
