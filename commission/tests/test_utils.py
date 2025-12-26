from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model

from commission.utils import add_referral_commission_atomic
from commission.models import CommissionSetting, Commission
from products.models import Product
from balance.models import Wallet

User = get_user_model()


class CommissionUtilsTest(TestCase):
    def setUp(self):
        self.referrer = User.objects.create(username='c_referrer')
        self.referred = User.objects.create(username='c_referred')

        CommissionSetting.objects.update_or_create(user=self.referrer, defaults={'product_rate': Decimal('0.00'), 'referral_rate': Decimal('5.00')})
        Wallet.objects.update_or_create(user=self.referrer, defaults={'current_balance': Decimal('0.00'), 'product_commission': Decimal('0.00'), 'referral_commission': Decimal('0.00'), 'cumulative_total': Decimal('0.00')})

        self.product = Product.objects.create(name='CProduct', price=Decimal('10.00'), is_active=True)

    def test_add_referral_commission_atomic_idempotent(self):
        amt1 = add_referral_commission_atomic(self.referrer, self.referred, self.product)
        amt2 = add_referral_commission_atomic(self.referrer, self.referred, self.product)

        self.assertEqual(amt1, amt2)

        rows = Commission.objects.filter(user=self.referrer, commission_type='referral', triggered_by=self.referred)
        self.assertEqual(rows.count(), 1)

        wallet = Wallet.objects.get(user=self.referrer)
        self.assertEqual(wallet.referral_commission, Decimal('0.50'))
