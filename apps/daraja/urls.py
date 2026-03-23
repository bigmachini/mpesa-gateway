from django.urls import path

from .views import STKPushView, STKStatusView

urlpatterns = [
    path('stk-push/', STKPushView.as_view(), name='stk-push'),
    path('stk-push/<str:checkout_request_id>/', STKStatusView.as_view(), name='stk-status'),
]
