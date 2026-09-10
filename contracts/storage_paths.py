from core import storage_paths


def contract_upload_path(instance, filename):
    """contracts.Contract.file の保存先パスを生成する。実体はcore.storage_paths.
    build_hierarchical_upload_pathに集約済み（documents.storage_paths.document_upload_pathとの
    重複をコード監査で発見、2026-08-25修正）。
    """
    return storage_paths.build_hierarchical_upload_path(instance, filename, root="contracts")
