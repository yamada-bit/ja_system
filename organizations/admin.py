from django.contrib import admin

from core.admin import ReadOnlyModelAdmin

from .models import Department, DepartmentViewScope, MenuItemSetting


@admin.register(Department)
class DepartmentAdmin(ReadOnlyModelAdmin):
    list_display = ("branch_code", "branch_name", "section_code", "section_name", "updated_at")
    search_fields = ("branch_code", "branch_name", "section_code", "section_name")


@admin.register(DepartmentViewScope)
class DepartmentViewScopeAdmin(ReadOnlyModelAdmin):
    list_display = ("viewer_department", "visible_department", "action", "created_at")
    list_filter = ("action",)


@admin.register(MenuItemSetting)
class MenuItemSettingAdmin(ReadOnlyModelAdmin):
    list_display = (
        "department",
        "show_search_document",
        "show_search_contract",
        "show_search_eapproval",
        "show_storage_document",
        "show_storage_contract",
    )
