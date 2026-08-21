from django.urls import path

from organizations import api, views

app_name = "organizations"

urlpatterns = [
    path("", views.DeptListView.as_view(), name="dept_list"),
    path("regist/", views.DeptRegistView.as_view(), name="dept_regist"),
    path("<int:pk>/edit/", views.DeptEditView.as_view(), name="dept_edit"),
    path("api/options/", api.OptionListAPIView.as_view(), name="api_options"),
]
