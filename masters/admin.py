from django.contrib import admin

from core.admin import ReadOnlyModelAdmin

from .models import Category, Group, RetentionPeriod, SystemSetting


@admin.register(Group)
class GroupAdmin(ReadOnlyModelAdmin):
    list_display = ("code", "name", "doc_kbn", "department", "is_deleted", "updated_at")
    list_filter = ("doc_kbn", "is_deleted")
    search_fields = ("code", "name")


@admin.register(Category)
class CategoryAdmin(ReadOnlyModelAdmin):
    list_display = ("code", "name", "group", "doc_kbn", "department", "is_deleted", "updated_at")
    list_filter = ("doc_kbn", "is_deleted")
    search_fields = ("code", "name")


@admin.register(RetentionPeriod)
class RetentionPeriodAdmin(ReadOnlyModelAdmin):
    list_display = ("kbn", "doc_name", "period_value", "period_unit", "display_order", "is_deleted")
    list_filter = ("kbn", "period_unit", "is_deleted")


@admin.register(SystemSetting)
class SystemSettingAdmin(admin.ModelAdmin):
    """システム設定（シングルトン）。

    `session_idle_timeout_minutes`はその他設定＞自動ログアウト時間タブで管理者が変更できるが、
    それ以外の運用値（.env経由へ移行済み）を含め、この行自体を追加・削除する経路はアプリ側に
    無い。誤って複数行になったり削除されたりするとメニューの自動ログアウト編集画面が壊れるため、
    管理サイトでは「変更」のみ許可し、行が既に存在する場合の「追加」と「削除」は禁止する。
    """

    list_display = ("__str__", "session_idle_timeout_minutes")

    def has_add_permission(self, request):
        return not SystemSetting.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
