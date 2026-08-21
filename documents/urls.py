from django.urls import path

from documents import api, views

app_name = "documents"

urlpatterns = [
    path("upload/step1/", views.UploadStep1View.as_view(), name="upload_step1"),
    path("upload/chunk/", api.ChunkUploadAPIView.as_view(), name="upload_chunk"),
    path("upload/step2/", views.UploadStep2View.as_view(), name="upload_step2"),
    path("upload/step2/preview/<int:index>/", views.PendingPreviewView.as_view(), name="upload_step2_preview"),
    path("search/", views.SearchView.as_view(), name="search"),
    path("api/options/", api.OptionListAPIView.as_view(), name="api_options"),
    path("api/<int:pk>/", api.DetailAPIView.as_view(), name="api_detail"),
    path("<int:pk>/edit/", views.DocumentEditView.as_view(), name="edit"),
    path("<int:pk>/download/", views.DownloadView.as_view(), name="download"),
    path("<int:pk>/preview/", views.PreviewView.as_view(), name="preview"),
    path("bulk-download/", views.BulkDownloadView.as_view(), name="bulk_download"),
    path("bulk-edit/start/", views.BulkEditStartView.as_view(), name="bulk_edit_start"),
    path("bulk-edit/", views.BulkEditView.as_view(), name="bulk_edit"),
    path("<int:pk>/delete/", views.DeleteView.as_view(), name="delete"),
]
