from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from decimal import Decimal

from products.models import Product, UserProductTask
from products.utils import complete_product_task
from commission.models import CommissionSetting, Commission
from balance.models import Wallet

User = get_user_model()


class Command(BaseCommand):
    help = 'Simulate referral commission applied twice to verify idempotency'

    def handle(self, *args, **options):
        # Clean up any previous test records to avoid conflicts
        Commission.objects.filter(product_name__icontains='SimProduct').delete()
        Product.objects.filter(name__icontains='SimProduct').delete()
        User.objects.filter(username__in=['sim_referrer', 'sim_referred']).delete()

        # Create users
        referrer = User.objects.create(username='sim_referrer')
        referred = User.objects.create(username='sim_referred')

        # Wire referral
        try:
            referred.referred_by = referrer
            referred.save()
        except Exception:
            # Some custom user models may require different attribute handling
            pass

        # Create commission settings
        CommissionSetting.objects.update_or_create(user=referrer, defaults={'product_rate': Decimal('0.00'), 'referral_rate': Decimal('5.00')})
        CommissionSetting.objects.update_or_create(user=referred, defaults={'product_rate': Decimal('10.00'), 'referral_rate': Decimal('0.00')})

        # Ensure wallets
        Wallet.objects.update_or_create(user=referrer, defaults={'current_balance': Decimal('0.00'), 'product_commission': Decimal('0.00'), 'referral_commission': Decimal('0.00'), 'cumulative_total': Decimal('0.00')})
        Wallet.objects.update_or_create(user=referred, defaults={'current_balance': Decimal('100.00'), 'product_commission': Decimal('0.00'), 'referral_commission': Decimal('0.00'), 'cumulative_total': Decimal('0.00')})

        # Create product
        product = Product.objects.create(name='SimProduct', price=Decimal('10.00'), is_active=True)

        # Create a task for referred user
        task = UserProductTask.objects.create(user=referred, product=product, is_completed=False)

        self.stdout.write('---- Running first completion ----')
        res1 = complete_product_task(referred, product)
        self.stdout.write(str(res1))

        # Show referrer wallet & commissions
        ref_wallet = Wallet.objects.get(user=referrer)
        self.stdout.write(f"Referrer wallet after first run: referral_commission={ref_wallet.referral_commission} cumulative_total={ref_wallet.cumulative_total}")
        ref_commissions = Commission.objects.filter(user=referrer, commission_type='referral', triggered_by=referred)
        self.stdout.write(f"Referral commission rows after first run: {ref_commissions.count()}")

        self.stdout.write('---- Running second completion (should be idempotent) ----')
        # Simulate a duplicate call: ensure task is not completed so function will run; create new task
        # For safety, create another task instance for the same product
        task2 = UserProductTask.objects.create(user=referred, product=product, is_completed=False)
        res2 = complete_product_task(referred, product)
        self.stdout.write(str(res2))

        ref_wallet.refresh_from_db()
        self.stdout.write(f"Referrer wallet after second run: referral_commission={ref_wallet.referral_commission} cumulative_total={ref_wallet.cumulative_total}")
        ref_commissions = Commission.objects.filter(user=referrer, commission_type='referral', triggered_by=referred)
        self.stdout.write(f"Referral commission rows after second run: {ref_commissions.count()}")

        self.stdout.write('---- Commission details ----')
        for c in ref_commissions:
            self.stdout.write(f"Commission: amount={c.amount}, product={c.product_name}, triggered_by={c.triggered_by}")
