from django.contrib.auth.models import AbstractUser
from django.db import models


class Client(AbstractUser):
    TIER_CHOICES = [
        ('byoc', 'Bring Your Own Credentials'),
        ('shared', 'Shared Till'),
    ]

    business_name = models.CharField(max_length=255)
    phone_number = models.CharField(max_length=20)
    email = models.EmailField(unique=True)
    tier = models.CharField(max_length=20, choices=TIER_CHOICES, default='byoc')
    is_active = models.BooleanField(default=False)  # activated after admin approval
    created_at = models.DateTimeField(auto_now_add=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username', 'business_name', 'phone_number']

    def __str__(self):
        return f"{self.business_name} ({self.email})"
