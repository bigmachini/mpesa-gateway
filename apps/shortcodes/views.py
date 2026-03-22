from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Shortcode
from .serializers import ShortcodeSerializer, WebhookURLSerializer


class ShortcodeListCreateView(generics.ListCreateAPIView):
    serializer_class = ShortcodeSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Shortcode.objects.filter(client=self.request.user)

    def perform_create(self, serializer):
        serializer.save(client=self.request.user)


class ShortcodeDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ShortcodeSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = 'uid'

    def get_queryset(self):
        return Shortcode.objects.filter(client=self.request.user)


class CallbackURLsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, uid):
        shortcode = generics.get_object_or_404(
            Shortcode, uid=uid, client=request.user
        )
        return Response(shortcode.get_callback_urls())


class WebhookURLView(generics.UpdateAPIView):
    serializer_class = WebhookURLSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = 'uid'
    http_method_names = ['put', 'patch']

    def get_queryset(self):
        return Shortcode.objects.filter(client=self.request.user)
