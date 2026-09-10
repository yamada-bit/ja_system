from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations


class Migration(migrations.Migration):
    """pg_trgm拡張を有効化する。documents/contracts の *_normalized 列の GinIndex(gin_trgm_ops) が必要とする。

    新ja_db（2026-08-07、Japanese_Japan.utf8ロケールで作成）ではpg_trgmが日本語トライグラムを
    正しく生成できることを手動検証済み。旧ja_db（LC_CTYPE=C）で発生していた問題は新DBでは発生しない。
    """

    initial = True

    dependencies = []

    operations = [
        TrigramExtension(),
    ]
