from django.urls import path

from .views import TransactionDetailView, TransactionListView, TransactionSummaryView

urlpatterns = [
    path('', TransactionListView.as_view(), name='transaction-list'),
    path('summary/', TransactionSummaryView.as_view(), name='transaction-summary'),
    path('<uuid:uid>/', TransactionDetailView.as_view(), name='transaction-detail'),
]
