import os

# 保管画面２・編集画面のPDFモックプレビューを、対象がラスター画像／PDFの場合のみ実データの
# <img>／<iframe>表示に切り替えるための判定用（documents/contracts両アプリで共用）。DB・保留
# ファイルのいずれにも元ファイルのMIME種別を保持するフィールドが無いため拡張子ベースの簡易判定に
# 留める。SVGはインラインscriptを含められるため、ブラウザに直接読み込ませる用途では対象外にする。
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
PDF_EXTENSION = ".pdf"


def is_image_filename(filename):
    _, ext = os.path.splitext(filename.lower())
    return ext in IMAGE_EXTENSIONS


def is_pdf_filename(filename):
    _, ext = os.path.splitext(filename.lower())
    return ext == PDF_EXTENSION


def get_preview_kind(filename):
    """保管画面２・編集画面のプレビュー種別を返す（"image"/"pdf"/None）。Noneの場合、
    テンプレート側は原本通りの擬似PDF文言モックのままにする。"""
    if is_image_filename(filename):
        return "image"
    if is_pdf_filename(filename):
        return "pdf"
    return None
