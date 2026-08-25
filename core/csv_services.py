import logging

logger = logging.getLogger(__name__)

# CSVインジェクション（CSVファイルをExcel等で開いた際、セルの内容が数式として解釈・実行されて
# しまう）対策。OWASP CSV Injection Prevention Cheat Sheetの推奨に倣い、これらの文字で始まる値は
# 数式の可能性があるとみなし、先頭にシングルクォートを付与してExcel側にテキストとして扱わせる。
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def sanitize_csv_cell(value):
    """CSV1セル分の値を、Excel等で開いた際の数式インジェクションを防ぐ形にエスケープする。

    文書タイトル・イベントメッセージ等、職員が自由入力した文字列がそのままCSV出力される
    画面（audit.views.AuditLogCsvExportView、accounts.views.StaffCsvExportView、
    permissions.views.AuthorityCsvExportView）で共通して使う。数値等の非文字列値はそのまま返す
    （csv.writer側でstr()される）。
    """
    text = value if isinstance(value, str) else str(value)
    if text.startswith(_FORMULA_PREFIXES):
        return "'" + text
    return value


def sanitize_csv_row(row):
    """1行分（イテラブル）の各セルにsanitize_csv_cellを適用する。"""
    return [sanitize_csv_cell(cell) for cell in row]
