from decimal import Decimal
from unittest.mock import patch
from django.test import TestCase
from django.contrib.auth.models import User
from products.models import Product, UserProductTask
from balance.models import Wallet
from commission.models import CommissionSetting
from stoppoints.models import StopPoint, StopPointProgress
from products.utils import get_next_product_for_user, complete_product_task, get_daily_task_limit

class ProductFlowTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='aaaaaa', password='password')
        self.wallet, _ = Wallet.objects.get_or_create(user=self.user)
        self.wallet.current_balance = Decimal('300.00')
        self.wallet.save()

        self.commission_setting, _ = CommissionSetting.objects.get_or_create(user=self.user)
        self.commission_setting.product_rate = Decimal('5.00') # 5%
        self.commission_setting.daily_task_limit = 30
        self.commission_setting.save()

        # Create enough products for the test scenario
        for i in range(1, 35): # 30 tasks + some buffer
            Product.objects.create(name=f'Product {i}', price=Decimal('10.00')) # Base price, will be overridden by utils

        # Create stoppoint at Task 11
        StopPoint.objects.create(user=self.user, point=11, required_balance=Decimal('800.00'), order=1)
        StopPointProgress.objects.get_or_create(user=self.user) # Ensure progress object exists

    def test_task_completion_and_balance_updates_slice1(self):
        # Initial balances
        self.assertEqual(self.wallet.current_balance, Decimal('300.00'))
        self.assertEqual(self.wallet.product_commission, Decimal('0.00'))

        # Simulate completing 10 tasks
        for i in range(1, 11): # Tasks 1 to 10
            initial_current_balance = self.wallet.current_balance

            # Get the next product and its calculated price
            next_product, block_reason, display_price, real_price, is_fake = get_next_product_for_user(self.user)
            self.assertIsNone(block_reason, f"Blocked at task {i}: {block_reason}")
            self.assertIsNotNone(next_product)
            task_price = real_price if is_fake else display_price
            self.assertIsNotNone(task_price)
            self.assertGreater(task_price, Decimal('0.00'))

            # Complete the task
            result = complete_product_task(self.user, next_product)
            self.assertIsNone(result.get('warning'))

            # Refresh wallet from DB
            self.wallet.refresh_from_db()

            # Since task_price already reflects the commission slice, it is fully added to the balance
            expected_balance_growth = (initial_current_balance + task_price).quantize(Decimal('0.01'))
            self.assertEqual(self.wallet.current_balance, expected_balance_growth)

            # Assert task is completed
            task = UserProductTask.objects.get(user=self.user, product=next_product, task_number=i)
            self.assertTrue(task.is_completed)

        # After 10 tasks, current_balance should equal starting balance plus total commissions (price returns net to zero)
        # total_commission should be 15 (5% of 300)
        # Note: Due to distribute_value_unevenly, task_price will vary, so we can't assert exact final balances without summing up all task_prices and commissions.
        # We've asserted the incremental changes, which is more robust.
        # Let's check the total tasks completed
        self.assertEqual(UserProductTask.objects.filter(user=self.user, is_completed=True).count(), 10)

    @patch('products.utils.distribute_value_unevenly')
    def test_post_stop_slice_consumes_persisted_shares(self, mock_distribute):
        slice_user = User.objects.create_user(username='slice_user', password='password')
        wallet, _ = Wallet.objects.get_or_create(user=slice_user)
        wallet.current_balance = Decimal('0.00')
        wallet.save(update_fields=['current_balance'])

        CommissionSetting.objects.create(user=slice_user, product_rate=Decimal('10.00'), daily_task_limit=10)

        products = []
        for i in range(1, 15):
            products.append(Product.objects.create(name=f'Slice Product {i}', price=Decimal('10.00')))

        cleared_stop = StopPoint.objects.create(
            user=slice_user,
            point=4,
            required_balance=Decimal('200.00'),
            required_balance_remaining=Decimal('0.00'),
            special_bonus_amount=Decimal('100.00'),
            bonus_disbursed=True,
            status='approved',
            order=1,
        )

        StopPoint.objects.create(
            user=slice_user,
            point=8,
            required_balance=Decimal('0.00'),
            special_bonus_amount=Decimal('0.00'),
            order=2,
        )

        progress, _ = StopPointProgress.objects.get_or_create(user=slice_user)
        progress.last_cleared = cleared_stop
        progress.save(update_fields=['last_cleared'])

        for task_number in range(1, 5):
            UserProductTask.objects.create(
                user=slice_user,
                product=products[task_number - 1],
                task_number=task_number,
                is_completed=True,
                price=Decimal('1.00'),
            )

        base_shares = [Decimal('120.00'), Decimal('90.00'), Decimal('90.00')]
        mock_distribute.return_value = base_shares.copy()

        expected_prices = [share * Decimal('0.10') for share in base_shares]

        for index, expected in enumerate(expected_prices, start=5):
            next_product, block_reason, display_price, real_price, is_fake = get_next_product_for_user(slice_user)
            self.assertFalse(is_fake)
            self.assertIsNone(block_reason)
            task_price = display_price
            self.assertEqual(task_price, expected.quantize(Decimal('0.01')))

            result = complete_product_task(slice_user, next_product)
            self.assertIsNone(result.get('warning'))

            latest_task = UserProductTask.objects.get(user=slice_user, product=next_product, task_number=index)
            self.assertTrue(latest_task.is_completed)

        mock_distribute.assert_called_once()

        progress.refresh_from_db()
        self.assertIsNone(progress.active_slice_shares)
