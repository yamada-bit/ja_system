from django.db import migrations

from core.text_normalization import normalize_for_search


def backfill_normalized_fields(apps, schema_editor):
    # 0002で追加したシャドウカラムはDocument.save()で自動生成されるが、それはPythonの
    # save()経由の場合のみ有効なため、マイグレーション追加前から存在する既存レコードには
    # 反映されていない。ここで一括計算して埋める（bulk_updateはinstance.save()を経由しない
    # ためモデル側のsave()オーバーライドに頼れず、明示的にここで正規化する必要がある）。
    Document = apps.get_model("documents", "Document")
    documents = list(Document.objects.all())
    for document in documents:
        document.title_normalized = normalize_for_search(document.title)
        document.memo_normalized = normalize_for_search(document.memo)
        document.extracted_text_normalized = normalize_for_search(document.extracted_text)
    Document.objects.bulk_update(
        documents, ["title_normalized", "memo_normalized", "extracted_text_normalized"], batch_size=500
    )


def noop_reverse(apps, schema_editor):
    # 正規化カラムを空に戻す意味が無いため、逆マイグレーションは何もしない
    # （0002のRemoveFieldがカラム自体を削除するため十分）。
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("documents", "0002_document_extracted_text_normalized_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_normalized_fields, noop_reverse),
    ]
