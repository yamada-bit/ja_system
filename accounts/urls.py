from django.urls import path

from accounts import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", views.LogoutView.as_view(), name="logout"),
    path("staff/", views.StaffListView.as_view(), name="staff_list"),
    path("staff/csv/", views.StaffCsvExportView.as_view(), name="staff_csv_export"),
    path("staff/csv/import/", views.StaffCsvImportView.as_view(), name="staff_csv_import"),
    path("staff/regist/", views.StaffRegistView.as_view(), name="staff_regist"),
    path("staff/<int:pk>/", views.StaffDetailView.as_view(), name="staff_detail"),
    path("staff/<int:pk>/edit/", views.StaffEditView.as_view(), name="staff_edit"),
]
