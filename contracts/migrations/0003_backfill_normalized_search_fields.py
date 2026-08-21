from django.db import migrations

from core.text_normalization import normalize_for_search


def backfill_normalized_fields(apps, schema_editor):
    # documents.migrations.0003と同じ理由（そちらのコメント参照）。
    Contract = apps.get_model("contracts", "Contract")
    contracts = list(Contract.objects.all())
    for contract in contracts:
        contract.title_normalized = normalize_for_search(contract.title)
        contract.memo_normalized = normalize_for_search(contract.memo)
        contract.extracted_text_normalized = normalize_for_search(contract.extracted_text)
    Contract.objects.bulk_update(
        contracts, ["title_normalized", "memo_normalized", "extracted_text_normalized"], batch_size=500
    )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("contracts", "0002_contract_extracted_text_normalized_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_normalized_fields, noop_reverse),
    ]
