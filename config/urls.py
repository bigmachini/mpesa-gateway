from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/v1/auth/', include('apps.accounts.urls')),
    path('api/v1/shortcodes/', include('apps.shortcodes.urls')),
    path('api/v1/daraja/', include('apps.daraja.urls')),
    path('api/v1/mpesa/', include('apps.daraja.callback_urls')),
    path('api/v1/transactions/', include('apps.transactions.urls')),
    path('api/v1/wallet/', include('apps.wallets.urls')),
    path('api/v1/webhooks/', include('apps.webhooks.urls')),
    path('api/v1/withdrawals/', include('apps.withdrawals.urls')),
]
