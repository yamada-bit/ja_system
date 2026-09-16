import logging
from pathlib import Path

import rjsmin
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """static/js/*.js から同名の *.min.js を生成する（RELEASE_PREP_NOTES.md「1.」）。

    本番リリース時、collectstaticの前に実行する運用（ManifestStaticFilesStorageはソースに
    実在するファイルにしかハッシュ名を付けないため、collectstatic前に.min.jsが物理的に
    存在している必要がある）。dev環境（STATICFILES_DIRS直配信、collectstatic不要）では
    実行不要——core.templatetags.js_static.js_staticがDEBUG=Trueの間はソースをそのまま参照する。
    """

    help = "static/js/*.js をrjsminで圧縮し、同名の*.min.jsを生成する（collectstaticの前に実行）。"

    def handle(self, *args, **options):
        js_dir = Path(settings.BASE_DIR) / "static" / "js"
        source_files = sorted(p for p in js_dir.glob("*.js") if not p.name.endswith(".min.js"))
        if not source_files:
            raise CommandError(f"minify対象のJSファイルが見つかりません: {js_dir}")

        for src in source_files:
            dest = src.with_name(f"{src.stem}.min.js")
            try:
                source_text = src.read_text(encoding="utf-8")
            except OSError:
                logger.exception("JSファイルの読み込みに失敗しました: %s", src)
                raise CommandError(f"読み込みに失敗しました: {src}")

            minified = rjsmin.jsmin(source_text)

            try:
                dest.write_text(minified, encoding="utf-8")
            except OSError:
                logger.exception("minifyファイルの書き込みに失敗しました: %s", dest)
                raise CommandError(f"書き込みに失敗しました: {dest}")

            logger.info("JSファイルをminifyしました: %s -> %s", src.name, dest.name)
            self.stdout.write(self.style.SUCCESS(f"{src.name} -> {dest.name}"))
