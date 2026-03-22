import factory
from django.contrib.auth.hashers import make_password

from apps.accounts.models import Client


class ClientFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Client

    username = factory.Sequence(lambda n: f"client{n}")
    email = factory.Sequence(lambda n: f"client{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    business_name = factory.Sequence(lambda n: f"Business {n}")
    phone_number = factory.Sequence(lambda n: f"+2547{n:08d}")
    tier = "byoc"
    is_active = True  # active by default in tests; override where needed
