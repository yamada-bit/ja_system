"""アップロードファイル名の拒否判定（セキュリティレビュー H-3 対応、`core.file_serving` と二重の防御）。

配信側（`core.file_serving`）でインライン配信を PDF＋画像に限定し nosniff/CSP を付与したことで
格納型 XSS 自体は塞いだが、そもそも「ブラウザで同一オリジン実行が可能な能動的コンテンツ」
（HTML・SVG・スクリプト等）は文書管理システムの保管対象として通常ありえないため、
アップロードの入口でも拒否する。

原本 HTML/xlsx はファイル種別を制限していないが、これはユーザー依頼のセキュリティ修正に伴う
意図的な逸脱（review_security.txt H-3、HTML_REIMPL_CHECKLIST_ARCHIVE.md 該当節に記録）。
拒否は「能動的コンテンツ」に限定し、Office 文書・PDF・画像・テキスト・圧縮ファイル等の
通常業務で使う形式には一切影響させない（許可リストではなく拒否リスト方式）。
"""

import os

BLOCKED_UPLOAD_EXTENSIONS = {
    # HTML 系（text/html で開かれ <script> がそのまま実行される）
    ".html", ".htm", ".xhtml", ".xht", ".shtml", ".mht", ".mhtml",
    # SVG（image/svg+xml。<script>・イベントハンドラを内包できる）
    ".svg", ".svgz",
    # スクリプト・レガシー能動コンテンツ
    ".js", ".mjs", ".htc", ".hta", ".swf",
}


def is_blocked_upload_filename(filename: str) -> bool:
    _, ext = os.path.splitext((filename or "").lower())
    return ext in BLOCKED_UPLOAD_EXTENSIONS


def blocked_upload_message(names) -> str | None:
    """`names` に拒否対象が含まれていれば利用者向けメッセージ、無ければ None。"""
    blocked = sorted({n for n in names if is_blocked_upload_filename(n)})
    if not blocked:
        return None
    return (
        "セキュリティ上の理由により、次のファイルは保管できません（HTML・SVG・スクリプト等の"
        "形式は登録できません）: " + "、".join(blocked)
    )
