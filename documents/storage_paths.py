import logging
import uuid

logger = logging.getLogger(__name__)


def document_upload_path(instance, filename):
    """documents.Document.file の保存先パスを生成する。

    HTML/xlsxはUI項目のみを規定しており、保存先ディレクトリ構成そのものはバックエンド実装の
    裁量事項（画面上に現れないため）。年・部署・カテゴリーで階層化し、運用時にファイルシステム上
    からも目的のファイルをある程度追いやすくする。ファイル名の先頭にUUIDを付与するのは、
    同名ファイルの上書き事故を防ぐため（部署をまたいで同じファイル名がアップロードされるのは
    珍しくない）。元のファイル名はそのまま残す（監査・利用者が保存後もファイル名から中身を
    推測できるようにするため、UUIDだけのランダム名にはしない）。

    呼び出し元（documents.views）は必ずDocument.department/categoryを設定してから
    file.save()を呼ぶため、ここでは両者のNoneチェックをしていない（未設定のままここに
    到達するのは呼び出し順序の実装バグなので、握りつぶさずAttributeErrorで気付ける方が良い、
    という判断）。また、filenameはユーザー由来の信頼できない文字列だが、Django 5.2の
    FileField/Storageがパストラバーサル対策（validate_file_name）を内部で行うため、
    ここでは追加のサニタイズを行っていない。
    """
    department = instance.department
    category = instance.category
    ext_uuid = uuid.uuid4().hex
    return (
        f"documents/{instance.year}/"
        f"{department.branch_code}-{department.section_code}/"
        f"{category.code}/{ext_uuid}_{filename}"
    )


def document_searchable_upload_path(instance, filename):
    """documents.Document.searchable_file（OCRテキスト埋め込み済みの検索用PDF、
    settings.OCR_EMBED_TEXT_TO_PDF）の保存先パス。原本（document_upload_path）とは別ディレクトリ
    （searchable/）に置き、原本を上書きしない設計であることをパス構成からも分かるようにする。"""
    department = instance.department
    category = instance.category
    ext_uuid = uuid.uuid4().hex
    return (
        f"documents/{instance.year}/"
        f"{department.branch_code}-{department.section_code}/"
        f"{category.code}/searchable/{ext_uuid}_{filename}"
    )
