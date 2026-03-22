from rest_framework import generics, permissions
from rest_framework_simplejwt.views import TokenObtainPairView

from .models import Client
from .serializers import ClientTokenObtainPairSerializer, ProfileSerializer, RegisterSerializer


class RegisterView(generics.CreateAPIView):
    queryset = Client.objects.all()
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]


class LoginView(TokenObtainPairView):
    serializer_class = ClientTokenObtainPairSerializer


class ProfileView(generics.RetrieveUpdateAPIView):
    serializer_class = ProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user
