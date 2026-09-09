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
