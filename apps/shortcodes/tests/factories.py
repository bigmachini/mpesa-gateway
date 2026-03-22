import factory

from apps.accounts.tests.factories import ClientFactory
from apps.shortcodes.models import Shortcode


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
