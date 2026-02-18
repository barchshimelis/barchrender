from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from balance.models import Wallet
from balance.utils import handle_stop_point_recharge
from stoppoints.models import StopPoint
from stoppoints.utils import ensure_stop_point_snapshot

User = get_user_model()


class StopPointRechargeTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="sp_user", password="password")
        self.wallet, _ = Wallet.objects.get_or_create(user=self.user)
        self.wallet.current_balance = Decimal("100.00")
        self.wallet.save(update_fields=["current_balance"])

    def _apply_recharge(self, amount):
        amount = Decimal(amount)
        self.wallet.current_balance += amount
        self.wallet.save(update_fields=["current_balance"])
        return handle_stop_point_recharge(self.user, self.wallet, amount)

    def test_partial_then_full_recharge_preserves_locked_price(self):
        stop_point = StopPoint.objects.create(
            user=self.user,
            point=5,
            required_balance=Decimal("500.00"),
            special_bonus_amount=Decimal("100.00"),
            order=1,
        )

        ensure_stop_point_snapshot(stop_point, self.wallet.current_balance)
        stop_point.refresh_from_db()

        locked_price = stop_point.locked_task_price
        estimated_balance = stop_point.estimated_balance_snapshot

        remaining = self._apply_recharge(Decimal("200.00"))
        self.assertEqual(remaining, Decimal("300.00"))

        stop_point.refresh_from_db()
        self.assertEqual(stop_point.required_balance_remaining, Decimal("300.00"))
        self.assertEqual(stop_point.locked_task_price, locked_price)
        self.assertEqual(stop_point.estimated_balance_snapshot, estimated_balance)
        self.assertFalse(stop_point.bonus_disbursed)
        self.assertEqual(stop_point.status, "pending")

        remaining = self._apply_recharge(Decimal("300.00"))
        self.assertEqual(remaining, Decimal("0.00"))

        stop_point.refresh_from_db()
        self.wallet.refresh_from_db()

        self.assertEqual(stop_point.required_balance_remaining, Decimal("0.00"))
        self.assertEqual(stop_point.locked_task_price, locked_price)
        self.assertTrue(stop_point.bonus_disbursed)
        self.assertEqual(stop_point.status, "approved")
        self.assertEqual(self.wallet.current_balance, Decimal("700.00"))
