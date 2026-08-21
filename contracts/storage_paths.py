import logging
import uuid

logger = logging.getLogger(__name__)


def contract_upload_path(instance, filename):
    """contracts.Contract.file の保存先パスを生成する（documents.storage_paths.document_upload_pathと
    同じ考え方。年・部署・カテゴリーで階層化し、ファイル名冒頭にUUIDを付与して衝突を防ぐ）。

    呼び出し元（contracts.views）は必ずContract.department/categoryを設定してから
    file.save()を呼ぶため、ここでは両者のNoneチェックをしていない（未設定のままここに
    到達するのは呼び出し順序の実装バグなので、握りつぶさずAttributeErrorで気付ける方が良い、
    という判断。documents.storage_paths.document_upload_pathと同じ理由）。また、filenameは
    ユーザー由来の信頼できない文字列だが、Django 5.2のFileField/Storageがパストラバーサル
    対策（validate_file_name）を内部で行うため、ここでは追加のサニタイズを行っていない。
    """
    department = instance.department
    category = instance.category
    ext_uuid = uuid.uuid4().hex
    return (
        f"contracts/{instance.year}/"
        f"{department.branch_code}-{department.section_code}/"
        f"{category.code}/{ext_uuid}_{filename}"
    )


def contract_searchable_upload_path(instance, filename):
    """contracts.Contract.searchable_file（OCRテキスト埋め込み済みの検索用PDF、
    settings.OCR_EMBED_TEXT_TO_PDF）の保存先パス。原本（contract_upload_path）とは別ディレクトリ
    （searchable/）に置き、原本を上書きしない設計であることをパス構成からも分かるようにする。"""
    department = instance.department
    category = instance.category
    ext_uuid = uuid.uuid4().hex
    return (
        f"contracts/{instance.year}/"
        f"{department.branch_code}-{department.section_code}/"
        f"{category.code}/searchable/{ext_uuid}_{filename}"
    )


def related_file_upload_path(instance, filename):
    """contracts.RelatedFile.file（関連書類）の保存先パス。契約書本体（instance.contract）にぶら下げる
    形にする。関連書類自体はAI-OCR等の処理対象外（xlsx 保管!B480）で、フォルダ分けも本体ほど
    細かくする必要はないため、契約書IDのみで階層化する。

    contract_upload_pathと同様、filenameのサニタイズはDjango側のvalidate_file_nameに委ねている。
    instance.contract_idはRelatedFile作成前に必ずcontract.save()済み（contracts.views参照）で
    Noneにならない前提のため、ここでもチェックはしていない。
    """
    ext_uuid = uuid.uuid4().hex
    return f"contracts/related/{instance.contract_id}/{ext_uuid}_{filename}"
