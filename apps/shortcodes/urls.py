from django.urls import path

from .views import (
    CallbackURLsView, PaymentReferenceListCreateView,
    ShortcodeDetailView, ShortcodeListCreateView, WebhookURLView,
)

urlpatterns = [
    path('', ShortcodeListCreateView.as_view(), name='shortcode-list'),
    path('<uuid:uid>/', ShortcodeDetailView.as_view(), name='shortcode-detail'),
    path('<uuid:uid>/callback-urls/', CallbackURLsView.as_view(), name='shortcode-callback-urls'),
    path('<uuid:uid>/webhook/', WebhookURLView.as_view(), name='shortcode-webhook'),
    path('<uuid:uid>/payment-references/', PaymentReferenceListCreateView.as_view(), name='payment-reference-list'),
]
