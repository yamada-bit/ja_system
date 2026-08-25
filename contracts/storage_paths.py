import uuid

from core import storage_paths


def contract_upload_path(instance, filename):
    """contracts.Contract.file の保存先パスを生成する。実体はcore.storage_paths.
    build_hierarchical_upload_pathに集約済み（documents.storage_paths.document_upload_pathとの
    重複をコード監査で発見、2026-08-25修正）。
    """
    return storage_paths.build_hierarchical_upload_path(instance, filename, root="contracts")


def contract_searchable_upload_path(instance, filename):
    """contracts.Contract.searchable_file（OCRテキスト埋め込み済みの検索用PDF、
    settings.OCR_EMBED_TEXT_TO_PDF）の保存先パス。原本（contract_upload_path）とは別ディレクトリ
    （searchable/）に置き、原本を上書きしない設計であることをパス構成からも分かるようにする。
    実体はcore.storage_paths.build_hierarchical_upload_pathに集約済み（documents.storage_paths.
    document_searchable_upload_pathとの重複をコード監査で発見、2026-08-25修正）。
    """
    return storage_paths.build_hierarchical_upload_path(instance, filename, root="contracts", searchable=True)


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
