from django import template
from django.conf import settings
from django.templatetags.static import static

register = template.Library()


@register.simple_tag
def js_static(path):
    """`static`のラッパー。DEBUG時（dev環境、ソース直配信）はそのまま、本番（DEBUG=False）は
    `.min.js`を参照する（RELEASE_PREP_NOTES.md「1.」static/js minify対応）。`.min.js`自体は
    リリース時に`core.management.commands.minify_static_js`で生成する生成物のため、
    このタグはパス文字列を組み立てるだけで生成の有無は関知しない。
    """
    if not settings.DEBUG and path.endswith(".js") and not path.endswith(".min.js"):
        path = f"{path[:-len('.js')]}.min.js"
    return static(path)
