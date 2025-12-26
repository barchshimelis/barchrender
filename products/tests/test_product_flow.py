from decimal import Decimal
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
        self.wallet.cumulative_total = Decimal('300.00')
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
        self.assertEqual(self.wallet.cumulative_total, Decimal('300.00'))
        self.assertEqual(self.wallet.product_commission, Decimal('0.00'))

        # Simulate completing 10 tasks
        for i in range(1, 11): # Tasks 1 to 10
            initial_current_balance = self.wallet.current_balance
            initial_cumulative_total = self.wallet.cumulative_total
            initial_product_commission = self.wallet.product_commission

            # Get the next product and its calculated price
            next_product, block_reason, task_price = get_next_product_for_user(self.user)
            self.assertIsNone(block_reason, f"Blocked at task {i}: {block_reason}")
            self.assertIsNotNone(next_product)
            self.assertIsNotNone(task_price)
            self.assertGreater(task_price, Decimal('0.00'))

            # Complete the task
            result = complete_product_task(self.user, next_product)
            self.assertIsNone(result.get('warning'))

            # Refresh wallet from DB
            self.wallet.refresh_from_db()

            # Assert balances
            expected_commission = (task_price * self.commission_setting.product_rate / 100).quantize(Decimal('0.01'))
            
            self.assertEqual(self.wallet.current_balance, (initial_current_balance - task_price).quantize(Decimal('0.01')))
            self.assertEqual(self.wallet.product_commission, (initial_product_commission + expected_commission).quantize(Decimal('0.01')))
            self.assertEqual(self.wallet.cumulative_total, (initial_cumulative_total + expected_commission).quantize(Decimal('0.01')))
            
            # Assert task is completed
            task = UserProductTask.objects.get(user=self.user, product=next_product, task_number=i)
            self.assertTrue(task.is_completed)

        # After 10 tasks, current_balance should be 0 (300 - 300)
        # total_commission should be 15 (5% of 300)
        # cumulative_total should be 315 (300 + 15)
        # Note: Due to distribute_value_unevenly, task_price will vary, so we can't assert exact final balances without summing up all task_prices and commissions.
        # We've asserted the incremental changes, which is more robust.
        # Let's check the total tasks completed
        self.assertEqual(UserProductTask.objects.filter(user=self.user, is_completed=True).count(), 10)
