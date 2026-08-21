from django.urls import path

from permissions import api, views

app_name = "permissions"

urlpatterns = [
    path("", views.AuthorityListView.as_view(), name="authority_list"),
    path("csv/", views.AuthorityCsvExportView.as_view(), name="authority_csv_export"),
    path("<int:pk>/edit/", views.AuthorityEditView.as_view(), name="authority_edit"),
    path("api/options/", api.OptionListAPIView.as_view(), name="api_options"),
]
