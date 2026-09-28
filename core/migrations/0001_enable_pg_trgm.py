from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations, models


class Migration(migrations.Migration):
    """pg_trgm拡張を有効化する。documents/contracts の *_normalized 列の GinIndex(gin_trgm_ops) が必要とする。

    新ja_db（2026-08-07、Japanese_Japan.utf8ロケールで作成）ではpg_trgmが日本語トライグラムを
    正しく生成できることを手動検証済み。旧ja_db（LC_CTYPE=C）で発生していた問題は新DBでは発生しない。

    ConsumedFormToken（core.models参照）は本番リリース前のマイグレーション集約方針
    （[[project_migrations_squash_into_0001]]。CLAUDE.md「マイグレーションは0001にまとめる」）に
    従い、`makemigrations`が生成した0002をこの唯一の初期マイグレーションへ手動で合流させた
    （core.double_submit.consume_token()のTOCTOU対策、ユーザー報告2026-09-28、
    docs/HTML_REIMPL_CHECKLIST_ARCHIVE.md参照）。
    """

    initial = True

    dependencies = []

    operations = [
        TrigramExtension(),
        migrations.CreateModel(
            name='ConsumedFormToken',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('token', models.CharField(max_length=32, unique=True, verbose_name='トークン')),
                ('form_id', models.CharField(max_length=100, verbose_name='フォームID')),
                ('consumed_at', models.DateTimeField(auto_now_add=True, db_index=True, verbose_name='消費日時')),
            ],
            options={
                'verbose_name': '二重送信対策トークン消費記録',
                'verbose_name_plural': '二重送信対策トークン消費記録',
            },
        ),
    ]
