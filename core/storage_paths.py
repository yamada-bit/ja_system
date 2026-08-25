import uuid


def build_hierarchical_upload_path(instance, filename, *, root, searchable=False):
    """documents.Document.file/searchable_fileおよびcontracts.Contract.file/searchable_fileの
    保存先パスを生成する共通ロジック。documents.storage_paths.document_upload_path/
    document_searchable_upload_path/contracts.storage_paths.contract_upload_path/
    contract_searchable_upload_pathの計4関数が、ルートディレクトリ名（"documents"/"contracts"）と
    searchable用サブディレクトリの有無以外完全に同一実装のまま重複していたため集約した
    （品質レビューで発見、2026-08-25修正）。

    HTML/xlsxはUI項目のみを規定しており、保存先ディレクトリ構成そのものはバックエンド実装の
    裁量事項（画面上に現れないため）。年・部署・カテゴリーで階層化し、運用時にファイルシステム上
    からも目的のファイルをある程度追いやすくする。ファイル名の先頭にUUIDを付与するのは、同名
    ファイルの上書き事故を防ぐため（部署をまたいで同じファイル名がアップロードされるのは珍しく
    ない）。元のファイル名はそのまま残す（監査・利用者が保存後もファイル名から中身を推測できる
    ようにするため、UUIDだけのランダム名にはしない）。

    呼び出し元（documents/contracts.views）は必ずDocument/Contract.department/categoryを設定
    してからfile.save()を呼ぶため、ここでは両者のNoneチェックをしていない（未設定のままここに
    到達するのは呼び出し順序の実装バグなので、握りつぶさずAttributeErrorで気付ける方が良い、
    という判断）。また、filenameはユーザー由来の信頼できない文字列だが、Django 5.2の
    FileField/Storageがパストラバーサル対策（validate_file_name）を内部で行うため、ここでは
    追加のサニタイズを行っていない。

    `root`は"documents"/"contracts"、`searchable`はOCRテキスト埋め込み済み検索用PDF
    （settings.OCR_EMBED_TEXT_TO_PDF）用に原本とは別ディレクトリ（searchable/）へ置くかどうか。
    """
    department = instance.department
    category = instance.category
    ext_uuid = uuid.uuid4().hex
    searchable_segment = "searchable/" if searchable else ""
    return (
        f"{root}/{instance.year}/"
        f"{department.branch_code}-{department.section_code}/"
        f"{category.code}/{searchable_segment}{ext_uuid}_{filename}"
    )
