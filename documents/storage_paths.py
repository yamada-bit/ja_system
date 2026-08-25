from core import storage_paths


def document_upload_path(instance, filename):
    """documents.Document.file の保存先パスを生成する。実体はcore.storage_paths.
    build_hierarchical_upload_pathに集約済み（contracts.storage_paths.contract_upload_pathとの
    重複をコード監査で発見、2026-08-25修正）。
    """
    return storage_paths.build_hierarchical_upload_path(instance, filename, root="documents")


def document_searchable_upload_path(instance, filename):
    """documents.Document.searchable_file（OCRテキスト埋め込み済みの検索用PDF、
    settings.OCR_EMBED_TEXT_TO_PDF）の保存先パス。原本（document_upload_path）とは別ディレクトリ
    （searchable/）に置き、原本を上書きしない設計であることをパス構成からも分かるようにする。
    実体はcore.storage_paths.build_hierarchical_upload_pathに集約済み（contracts.storage_paths.
    contract_searchable_upload_pathとの重複をコード監査で発見、2026-08-25修正）。
    """
    return storage_paths.build_hierarchical_upload_path(instance, filename, root="documents", searchable=True)
