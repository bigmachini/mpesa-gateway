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
    # is_active inherits default=True from AbstractUser.
    # New self-registered clients are set inactive by RegisterSerializer
    # and require admin approval before they can log in.
    created_at = models.DateTimeField(auto_now_add=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username', 'business_name', 'phone_number']

    @property
    def company(self):
        """
        Returns the company this user belongs to.
        For Client (company owner), this is self.
        When ClientUser is added later, it will have a company FK —
        using request.user.company in all views means no view changes at that point.
        """
        return self

    def __str__(self):
        return f"{self.business_name} ({self.email})"
