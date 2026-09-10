import uuid


def build_hierarchical_upload_path(instance, filename, *, root):
    """documents.Document.file / contracts.Contract.file の保存先パスを生成する共通ロジック。
    documents.storage_paths.document_upload_path / contracts.storage_paths.contract_upload_path が
    ルートディレクトリ名（"documents"/"contracts"）以外完全に同一実装のまま重複していたため集約した
    （品質レビューで発見、2026-08-25修正。旧 searchable_file 用の `searchable=` 分岐は
    searchable_file 廃止に伴い撤去、2026-09-11、監査 案3）。

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

    `root`は"documents"/"contracts"。
    """
    department = instance.department
    category = instance.category
    ext_uuid = uuid.uuid4().hex
    return (
        f"{root}/{instance.year}/"
        f"{department.branch_code}-{department.section_code}/"
        f"{category.code}/{ext_uuid}_{filename}"
    )
