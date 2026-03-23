from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import PaymentReference, Shortcode
from .serializers import PaymentReferenceSerializer, ShortcodeSerializer, WebhookURLSerializer


class ShortcodeListCreateView(generics.ListCreateAPIView):
    serializer_class = ShortcodeSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Shortcode.objects.filter(client=self.request.user.company)

    def perform_create(self, serializer):
        serializer.save(client=self.request.user.company)


class ShortcodeDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ShortcodeSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = 'uid'

    def get_queryset(self):
        return Shortcode.objects.filter(client=self.request.user.company)


class CallbackURLsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, uid):
        shortcode = generics.get_object_or_404(
            Shortcode, uid=uid, client=request.user.company
        )
        return Response(shortcode.get_callback_urls())


class WebhookURLView(generics.UpdateAPIView):
    serializer_class = WebhookURLSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = 'uid'
    http_method_names = ['put', 'patch']

    def get_queryset(self):
        return Shortcode.objects.filter(client=self.request.user.company)


class PaymentReferenceListCreateView(generics.ListCreateAPIView):
    """
    List or register pre-payment references for C2B validation.
    Only available for Paybill shortcodes with validation_mode='pre_register'.
    """
    serializer_class = PaymentReferenceSerializer
    permission_classes = [permissions.IsAuthenticated]

    def _get_shortcode(self):
        return generics.get_object_or_404(
            Shortcode,
            uid=self.kwargs['uid'],
            client=self.request.user.company,
            shortcode_type='paybill',
        )

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx['shortcode'] = self._get_shortcode()
        return ctx

    def get_queryset(self):
        shortcode = self._get_shortcode()
        return PaymentReference.objects.filter(shortcode=shortcode)

    def perform_create(self, serializer):
        shortcode = self._get_shortcode()
        serializer.save(shortcode=shortcode)
