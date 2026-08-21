from django.urls import path

from core import views

app_name = "core"

urlpatterns = [
    path("", views.MenuView.as_view(), name="menu"),
    path("settings/", views.SettingsMenuView.as_view(), name="settings"),
    path("settings/other/", views.OtherSettingsView.as_view(), name="other_settings"),
    path("settings/other/main/<int:pk>/edit/", views.OtherMainEditView.as_view(), name="other_main_edit"),
    path("settings/other/logout/edit/", views.OtherLogoutEditView.as_view(), name="other_logout_edit"),
]
