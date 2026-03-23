from decimal import Decimal

from django.db.models import Count, Q, Sum
from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.shortcodes.models import Shortcode

from .models import Transaction
from .serializers import TransactionSerializer


class TransactionListView(generics.ListAPIView):
    """
    Read-only list of all transactions across all shortcodes owned by the company.

    Query params:
      shortcode  — filter by shortcode uid
      status     — pending | completed | failed
      type       — c2b_paybill | c2b_till | stk_push
      date_from  — ISO 8601 date (transaction_time >=)
      date_to    — ISO 8601 date (transaction_time <=)
    """
    serializer_class = TransactionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        company_shortcodes = Shortcode.objects.filter(
            client=self.request.user.company
        ).values_list('id', flat=True)

        qs = Transaction.objects.filter(
            shortcode_id__in=company_shortcodes
        ).select_related('shortcode')

        params = self.request.query_params

        if uid := params.get('shortcode'):
            qs = qs.filter(shortcode__uid=uid)

        if status := params.get('status'):
            qs = qs.filter(status=status)

        if txn_type := params.get('type'):
            qs = qs.filter(transaction_type=txn_type)

        if date_from := params.get('date_from'):
            qs = qs.filter(transaction_time__date__gte=date_from)

        if date_to := params.get('date_to'):
            qs = qs.filter(transaction_time__date__lte=date_to)

        return qs


class TransactionDetailView(generics.RetrieveAPIView):
    serializer_class = TransactionSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = 'uid'

    def get_queryset(self):
        company_shortcodes = Shortcode.objects.filter(
            client=self.request.user.company
        ).values_list('id', flat=True)
        return Transaction.objects.filter(
            shortcode_id__in=company_shortcodes
        ).select_related('shortcode')


class TransactionSummaryView(APIView):
    """
    Aggregated statistics for all transactions owned by the company.

    Response:
      total_received      — sum of completed transaction amounts
      total_count         — total number of transactions (all statuses)
      completed_count
      pending_count
      failed_count
      by_type             — breakdown per transaction_type (count + total)
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        company_shortcodes = Shortcode.objects.filter(
            client=request.user.company
        ).values_list('id', flat=True)

        qs = Transaction.objects.filter(shortcode_id__in=company_shortcodes)

        totals = qs.aggregate(
            total_count=Count('id'),
            completed_count=Count('id', filter=Q(status='completed')),
            pending_count=Count('id', filter=Q(status='pending')),
            failed_count=Count('id', filter=Q(status='failed')),
            total_received=Sum('amount', filter=Q(status='completed')),
        )

        by_type = {}
        for txn_type, _ in Transaction.TRANSACTION_TYPES:
            agg = qs.filter(transaction_type=txn_type).aggregate(
                count=Count('id'),
                total=Sum('amount', filter=Q(status='completed')),
            )
            by_type[txn_type] = {
                'count': agg['count'],
                'total': agg['total'] or Decimal('0'),
            }

        return Response({
            'total_received': totals['total_received'] or Decimal('0'),
            'total_count': totals['total_count'],
            'completed_count': totals['completed_count'],
            'pending_count': totals['pending_count'],
            'failed_count': totals['failed_count'],
            'by_type': by_type,
        })
