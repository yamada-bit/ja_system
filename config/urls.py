from django.contrib import admin
from django.urls import include, path

from core.views import HealthCheckView

urlpatterns = [
    path('admin/', admin.site.urls),
    # core.urlsのapp_name配下ではなくここに直接置く。監視ツール・ロードバランサは職員番号
    # ログインの文脈を持たず、core:menu等の画面群とは別の運用インフラとして扱うため
    # （core.views.HealthCheckViewのdocstring参照）。
    path('healthz/', HealthCheckView.as_view(), name='healthz'),
    path('accounts/', include('accounts.urls')),
    path('documents/', include('documents.urls')),
    path('contracts/', include('contracts.urls')),
    path('organizations/', include('organizations.urls')),
    path('permissions/', include('permissions.urls')),
    path('masters/', include('masters.urls')),
    path('audit/', include('audit.urls')),
    path('', include('core.urls')),
]
