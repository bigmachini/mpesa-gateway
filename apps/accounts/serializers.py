from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import Client


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, validators=[validate_password])

    class Meta:
        model = Client
        fields = ['email', 'username', 'password', 'business_name', 'phone_number']

    def create(self, validated_data):
        return Client.objects.create_user(is_active=False, **validated_data)


class ProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = Client
        fields = ['id', 'email', 'username', 'business_name', 'phone_number', 'tier', 'is_active', 'created_at']
        read_only_fields = ['id', 'email', 'tier', 'is_active', 'created_at']


class ClientTokenObtainPairSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        data = super().validate(attrs)
        data['tier'] = self.user.tier
        data['business_name'] = self.user.business_name
        return data
