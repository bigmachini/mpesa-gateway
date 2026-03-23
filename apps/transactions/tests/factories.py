import factory
from django.utils import timezone

from apps.shortcodes.tests.factories import ShortcodeFactory
from apps.transactions.models import Transaction


class TransactionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Transaction

    shortcode = factory.SubFactory(ShortcodeFactory)
    transaction_type = 'c2b_paybill'
    status = 'completed'
    mpesa_receipt_number = factory.Sequence(lambda n: f'LGR{n:08d}')
    msisdn = '254708374149'
    amount = factory.LazyFunction(lambda: __import__('decimal').Decimal('100.00'))
    account_reference = 'INV001'
    bill_ref_number = 'INV001'
    raw_payload = factory.LazyFunction(dict)
    transaction_time = factory.LazyFunction(timezone.now)
