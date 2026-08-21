from django.urls import path

from masters import views

app_name = "masters"

urlpatterns = [
    path("class/", views.GroupListView.as_view(), name="class_list"),
    path("class/regist/", views.GroupRegistView.as_view(), name="class_regist"),
    path("class/<int:pk>/edit/", views.GroupEditView.as_view(), name="class_edit"),
    path("class/<int:pk>/delete/", views.GroupDeleteView.as_view(), name="class_delete"),
    path("cat/", views.CategoryListView.as_view(), name="cat_list"),
    path("cat/regist/", views.CategoryRegistView.as_view(), name="cat_regist"),
    path("cat/<int:pk>/edit/", views.CategoryEditView.as_view(), name="cat_edit"),
    path("cat/<int:pk>/delete/", views.CategoryDeleteView.as_view(), name="cat_delete"),
    path("retention/", views.RetentionListView.as_view(), name="retention_list"),
    path("retention/regist/", views.RetentionRegistView.as_view(), name="retention_regist"),
    path("retention/<int:pk>/edit/", views.RetentionEditView.as_view(), name="retention_edit"),
    path("retention/<int:pk>/delete/", views.RetentionDeleteView.as_view(), name="retention_delete"),
]
