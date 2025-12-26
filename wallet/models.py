
from decimal import Decimal
from django.db import models
from django.conf import settings
from django.utils import timezone

User = settings.AUTH_USER_MODEL

CRYPTO_NETWORK_CHOICES = [
    ('TRX-20', 'TRX-20 (TRON)'),
    ('ERC-20', 'ERC-20 (Ethereum)'),
    ('BEP-20', 'BEP-20 (Binance Smart Chain)'),
    ('Polygon', 'Polygon (MATIC)'),
    ('Solana', 'Solana (SOL)'),
    ('Avalanche', 'Avalanche (AVAX)'),
    ('Fantom', 'Fantom (FTM)'),
    ('Arbitrum', 'Arbitrum (ARB)'),
    ('Optimism', 'Optimism (OP)'),
    ('Cardano', 'Cardano (ADA)'),
]

class UserWalletAddress(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    address = models.CharField(max_length=255, unique=True)
    network = models.CharField(max_length=20, choices=CRYPTO_NETWORK_CHOICES)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "User Wallet Address"
        verbose_name_plural = "User Wallet Addresses"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} | {self.network} | {self.address}"
    


class WalletHistory(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='wallet_history')
    address = models.CharField(max_length=255)
    network = models.CharField(max_length=20, choices=CRYPTO_NETWORK_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)
    changed_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='wallet_changed_by')

    class Meta:
        verbose_name = "Wallet History"
        verbose_name_plural = "Wallet Histories"
        ordering = ['-created_at']
        unique_together = ('address', 'network')

    def __str__(self):
        return f"{self.user.username} | {self.network} | {self.address}"

class WithdrawalConfig(models.Model):
    """
    Configuration model for withdrawal limits and fees.
    Only one instance should exist (singleton pattern).
    """
    min_withdrawal = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("10.00"),
        help_text="Minimum withdrawal amount in USD"
    )
    max_withdrawal = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("10000.00"),
        help_text="Maximum withdrawal amount per transaction in USD"
    )
    daily_withdrawal_limit = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("50000.00"),
        help_text="Maximum total withdrawal amount per day in USD"
    )
    min_leftover_balance = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.05"),
        help_text="Minimum balance that must remain in wallet"
    )
    
    # Network-specific fees (percentage)
    trx20_fee_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("1.00"))
    erc20_fee_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("2.00"))
    bep20_fee_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("1.50"))
    polygon_fee_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("1.00"))
    solana_fee_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("1.00"))
    avalanche_fee_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("1.50"))
    fantom_fee_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("1.00"))
    arbitrum_fee_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("1.50"))
    optimism_fee_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("1.50"))
    cardano_fee_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("1.00"))
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Withdrawal Configuration"
        verbose_name_plural = "Withdrawal Configuration"

    def __str__(self):
        return f"Withdrawal Config (Min: {self.min_withdrawal}, Max: {self.max_withdrawal})"
    
    def get_fee_percent(self, network):
        """Get fee percentage for a specific network"""
        fee_map = {
            'TRX-20': self.trx20_fee_percent,
            'ERC-20': self.erc20_fee_percent,
            'BEP-20': self.bep20_fee_percent,
            'Polygon': self.polygon_fee_percent,
            'Solana': self.solana_fee_percent,
            'Avalanche': self.avalanche_fee_percent,
            'Fantom': self.fantom_fee_percent,
            'Arbitrum': self.arbitrum_fee_percent,
            'Optimism': self.optimism_fee_percent,
            'Cardano': self.cardano_fee_percent,
        }
        return fee_map.get(network, Decimal("1.50"))  # default 1.5%
    
    @classmethod
    def get_config(cls):
        """Get or create the singleton config instance"""
        config, _ = cls.objects.get_or_create(pk=1)
        return config


class UserWithdrawal(models.Model):
    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("PROCESSING", "Processing"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
        ("CANCELLED", "Cancelled"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="withdrawals")
    
    # Amount details
    amount = models.DecimalField(
        max_digits=18, decimal_places=8,
        help_text="Requested withdrawal amount"
    )
    fee_amount = models.DecimalField(
        max_digits=18, decimal_places=8, default=Decimal("0.0"),
        help_text="Transaction fee amount"
    )
    net_amount = models.DecimalField(
        max_digits=18, decimal_places=8, default=Decimal("0.0"),
        help_text="Net amount after fees (amount - fee_amount)"
    )
    
    # Network and wallet info
    network = models.CharField(max_length=20, choices=CRYPTO_NETWORK_CHOICES)
    wallet_address = models.CharField(
        max_length=255, default='',
        help_text="Wallet address where funds will be sent"
    )
    
    # Balance snapshot at time of withdrawal
    balance_at_request = models.DecimalField(
        max_digits=18, decimal_places=8, default=Decimal("0.0"),
        help_text="User's balance at time of withdrawal request"
    )
    
    # Status and tracking
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default="PENDING")
    transaction_hash = models.CharField(
        max_length=255, blank=True, null=True,
        help_text="Blockchain transaction hash (filled on approval)"
    )
    
    # Admin notes and actions
    admin_notes = models.TextField(
        blank=True, null=True,
        help_text="Admin notes or rejection reason"
    )
    processed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="processed_withdrawals",
        help_text="Admin who processed this withdrawal"
    )
    processed_at = models.DateTimeField(
        null=True, blank=True,
        help_text="When the withdrawal was approved/rejected"
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "User Withdrawal"
        verbose_name_plural = "User Withdrawals"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"{self.user.username} | {self.amount} {self.network} | {self.status}"
    
    @property
    def fee_percentage(self):
        """Calculate fee percentage"""
        if self.amount > 0:
            return (self.fee_amount / self.amount * 100).quantize(Decimal("0.01"))
        return Decimal("0.00")
    
    def calculate_fee(self, config=None):
        """Calculate withdrawal fee based on network"""
        if config is None:
            config = WithdrawalConfig.get_config()
        
        fee_percent = config.get_fee_percent(self.network)
        fee = (self.amount * fee_percent / 100).quantize(Decimal("0.00000001"))
        return fee
