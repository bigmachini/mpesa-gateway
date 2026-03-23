import factory
from django.utils import timezone

from apps.accounts.tests.factories import ClientFactory
from apps.shortcodes.models import PaymentReference, Shortcode


class ShortcodeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Shortcode

    client = factory.SubFactory(ClientFactory)
    shortcode_type = 'paybill'
    tier = 'byoc'
    shortcode_number = factory.Sequence(lambda n: f"60000{n}")
    display_name = factory.Sequence(lambda n: f"Store Paybill {n}")
    consumer_key = 'test-consumer-key'
    consumer_secret = 'test-consumer-secret'
    passkey = 'test-passkey'
    initiator_name = ''
    is_active = True
    enable_c2b_validation = False
    validation_mode = ''
    validation_webhook_url = None


class PaymentReferenceFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PaymentReference

    shortcode = factory.SubFactory(ShortcodeFactory)
    reference = factory.Sequence(lambda n: f"INV{n:04d}")
    amount = factory.LazyFunction(lambda: __import__('decimal').Decimal('100.00'))
    expires_at = factory.LazyFunction(lambda: timezone.now() + __import__('datetime').timedelta(hours=1))
    is_used = False
