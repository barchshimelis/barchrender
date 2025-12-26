from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.contrib.auth.hashers import make_password, check_password
from django.db import models
from django.utils import timezone
from datetime import timedelta
import uuid

class CustomUserManager(BaseUserManager):
    def create_user(self, username=None, phone=None, password=None, fund_password=None,
                    referred_by=None, role='user', **extra_fields):
        """
        Creates a user. Regular users require phone + username + fund password.
        Admins/CS/Super Admin require username + password.
        """
        if role == 'user':
            if not phone:
                raise ValueError('Regular users must provide a phone number')
            if not username:
                raise ValueError('Regular users must provide a username')
        else:
            if not username:
                raise ValueError(f'{role} must have a username')

        user = self.model(
            username=username,
            phone=phone,
            fund_password=fund_password,
            referred_by=referred_by,
            role=role,
            **extra_fields
        )
        user.set_password(password)

        # Auto-generate referral code for Admin or user if missing
        if not user.referral_code:
            user.referral_code = str(uuid.uuid4()).replace('-', '')[:8]

        user.save(using=self._db)
        return user

    def create_superuser(self, username, password, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(username=username, password=password, role='superadmin', **extra_fields)


class CustomUser(AbstractBaseUser, PermissionsMixin):
    ROLE_CHOICES = [
        ('superadmin', 'Super Admin'),
        ('admin', 'Admin'),
        ('customerservice', 'Customer Service'),
        ('user', 'Regular User'),
    ]

    username = models.CharField(max_length=150, unique=True, null=True, blank=True)
    phone = models.CharField(max_length=20, unique=True, null=True, blank=True)
    fund_password = models.CharField(max_length=128, null=True, blank=True)
    referral_code = models.CharField(max_length=20, unique=True, null=True, blank=True)
    referred_by = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='referrals')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='user')

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_frozen = models.BooleanField(default=False)  # Super admin can freeze admins/CS
    last_activity = models.DateTimeField(null=True, blank=True)  # Track online/offline status
    date_joined = models.DateTimeField(default=timezone.now)

    objects = CustomUserManager()

    # Login fields:
    # - Super Admin, Admin, Customer Service -> username
    # - Regular User -> phone (will handle in auth backend)
    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS = []

    def __str__(self):
        return self.username or self.phone or "User"
    
    def get_full_name(self):
        """Keep compatibility with Django templates expecting this helper."""
        return self.username or self.phone or ""

    def get_short_name(self):
        """Return a short identifier for admin listings."""
        return self.username or self.phone or ""
    
    def set_fund_password(self, raw_password):
        """Hash and store fund password."""
        self.fund_password = make_password(raw_password)
        self.save(update_fields=['fund_password'])

    def check_fund_password(self, raw_password):
        """Verify fund password. Only regular users have fund passwords."""
        if self.role != 'user' or not self.fund_password:
            return False
        return check_password(raw_password, self.fund_password)
    
    @property
    def is_online(self):
        """Treat users as online only if active within the last minute."""
        if not self.last_activity:
            return False
        return timezone.now() - self.last_activity < timedelta(minutes=1)
    
    def get_last_seen_display(self):
        """Return human-readable last seen time."""
        if not self.last_activity:
            return "Never"
        
        diff = timezone.now() - self.last_activity
        
        if diff < timedelta(minutes=1):
            return "Just now"
        elif diff < timedelta(minutes=60):
            mins = int(diff.total_seconds() / 60)
            return f"{mins} min{'s' if mins > 1 else ''} ago"
        elif diff < timedelta(hours=24):
            hours = int(diff.total_seconds() / 3600)
            return f"{hours} hour{'s' if hours > 1 else ''} ago"
        else:
            days = diff.days
            return f"{days} day{'s' if days > 1 else ''} ago"


from django.db import models
from django.contrib.auth.hashers import make_password, check_password

class SuperAdminWallet(models.Model):
    address = models.CharField(max_length=255, unique=True)
    wallet_password = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def set_wallet_password(self, raw_password, set_by=None, notes=""):
        """Hash and set the wallet password, tracking credential metadata."""
        hashed = make_password(raw_password)
        self.wallet_password = hashed
        self.save(update_fields=['wallet_password'])

        credential, _ = SuperAdminWalletCredential.objects.update_or_create(
            wallet=self,
            defaults={
                'password_hash': hashed,
                'set_by': set_by,
                'notes': notes or "",
                'is_active': True,
            },
        )
        # Refresh the reverse relation cache so subsequent checks use the new hash
        self.credential = credential

    def check_wallet_password(self, raw_password):
        """Check if the given password matches the stored hash."""
        credential = getattr(self, "credential", None)
        if credential and credential.password_hash:
            return check_password(raw_password, credential.password_hash)
        if self.wallet_password:
            return check_password(raw_password, self.wallet_password)
        return False

    def has_password(self):
        """Check if wallet has a password set."""
        credential = getattr(self, "credential", None)
        if credential and credential.password_hash:
            return True
        return bool(self.wallet_password)

    class Meta:
        verbose_name = "Super Admin Wallet"
        verbose_name_plural = "Super Admin Wallets"

    def __str__(self):
        return f"Wallet: {self.address[:10]}..."


class SuperAdminWalletCredential(models.Model):
    wallet = models.OneToOneField(
        SuperAdminWallet,
        on_delete=models.CASCADE,
        related_name="credential"
    )
    password_hash = models.CharField(max_length=255)
    set_at = models.DateTimeField(auto_now_add=True)
    set_by = models.ForeignKey(
        CustomUser,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="wallet_credentials_set"
    )
    notes = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Super Admin Wallet Credential"
        verbose_name_plural = "Super Admin Wallet Credentials"

    def __str__(self):
        status = "active" if self.is_active else "inactive"
        return f"Credential for {self.wallet} ({status})"

