from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model

from products.models import Product, UserProductTask
from products.utils import complete_product_task
from commission.models import Commission, CommissionSetting
from balance.models import Wallet

User = get_user_model()


class ReferralIdempotencyTest(TestCase):
    def setUp(self):
        # Create users
        self.referrer = User.objects.create(username='test_referrer')
        self.referred = User.objects.create(username='test_referred')

        # Wire referral
        try:
            self.referred.referred_by = self.referrer
            self.referred.save()
        except Exception:
            # Some custom user models may differ; ignore if attribute not present
            pass

        # Commission settings
        CommissionSetting.objects.update_or_create(user=self.referrer, defaults={'product_rate': Decimal('0.00'), 'referral_rate': Decimal('5.00')})
        CommissionSetting.objects.update_or_create(user=self.referred, defaults={'product_rate': Decimal('10.00'), 'referral_rate': Decimal('0.00')})

        # Wallets
        Wallet.objects.update_or_create(user=self.referrer, defaults={'current_balance': Decimal('0.00'), 'product_commission': Decimal('0.00'), 'referral_commission': Decimal('0.00'), 'cumulative_total': Decimal('0.00')})
        Wallet.objects.update_or_create(user=self.referred, defaults={'current_balance': Decimal('100.00'), 'product_commission': Decimal('0.00'), 'referral_commission': Decimal('0.00'), 'cumulative_total': Decimal('0.00')})

        # Product
        self.product = Product.objects.create(name='TestProduct', price=Decimal('10.00'), is_active=True)

    def test_referral_applied_only_once_when_triggered_twice(self):
        # Create first task and complete
        UserProductTask.objects.create(user=self.referred, product=self.product, is_completed=False)
        res1 = complete_product_task(self.referred, self.product)
        self.assertIn('product_commission', res1)

        # After first run, one referral commission should exist
        ref_commissions = Commission.objects.filter(user=self.referrer, commission_type='referral', triggered_by=self.referred)
        self.assertEqual(ref_commissions.count(), 1)

        # Create second task for same product and run again (simulate duplicate trigger)
        UserProductTask.objects.create(user=self.referred, product=self.product, is_completed=False)
        res2 = complete_product_task(self.referred, self.product)
        self.assertIn('product_commission', res2)

        # Referral commission should still be 1 and wallet should not be double-incremented
        ref_commissions = Commission.objects.filter(user=self.referrer, commission_type='referral', triggered_by=self.referred)
        self.assertEqual(ref_commissions.count(), 1)

        ref_wallet = Wallet.objects.get(user=self.referrer)
        # referral_rate is 5% of 10.00 = 0.50
        self.assertEqual(ref_wallet.referral_commission, Decimal('0.50'))
