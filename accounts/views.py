import uuid

from accounts.models import CustomUser, SuperAdminWallet



import random
import string
from django.utils.translation import gettext as _, get_language, get_language_info
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import get_user_model, authenticate, login
from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth.hashers import make_password
from django.shortcuts import render
from products.models import UserProductTask
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout
from commission.utils import get_total_commission
from balance.models import RechargeHistory, Wallet
from commission.models import Commission, CommissionSetting
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from products.models import Product
from django.db import models
from django.contrib.sessions.models import Session
from django.utils import timezone as tz
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
import json


from notification.utils import notify_superadmins, notify_roles
from notification.models import Notification, AdminDashboardEvent
from chat.session_store import list_sessions
from django.urls import reverse

import uuid
import random
import string
import json
from collections import deque
from datetime import timedelta

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import get_user_model, authenticate, login
from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test, login_required
from django.contrib.auth.hashers import make_password
from django.contrib.auth import logout
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.contrib.sessions.models import Session
from django.db import models
from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.utils import timezone as tz
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods, require_POST, require_GET
from django.urls import reverse

from accounts.models import CustomUser, SuperAdminWallet
from products.models import Product, UserProductTask, FeaturedImage
from balance.models import RechargeHistory, Wallet
from commission.models import Commission, CommissionSetting
from commission.utils import get_total_commission
from notification.utils import notify_superadmins, notify_roles
from notification.models import Notification, AdminDashboardEvent
from wallet.models import UserWithdrawal, UserWalletAddress, CRYPTO_NETWORK_CHOICES

from django.conf import settings
from pathlib import Path

def _load_feature_gallery_images():
    feature_dir = Path(settings.MEDIA_ROOT) / "feature"
    if not feature_dir.exists():
        return []

    media_root = Path(settings.MEDIA_ROOT)
    image_paths = []
    patterns = ("*.jpg", "*.jpeg", "*.png", "*.gif", "*.webp", "*.avif")
    for pattern in patterns:
        image_paths.extend(feature_dir.glob(pattern))

    urls = []
    for image_path in sorted(set(image_paths)):
        try:
            rel_path = image_path.relative_to(media_root).as_posix()
        except ValueError:
            continue
        urls.append(f"{settings.MEDIA_URL}{rel_path}")
    return urls

def superadminlogin(request):
    """
    Super Admin login page.
    Only users with role='superadmin' can log in.
    """
    captcha_prompt = _ensure_login_captcha(request)
    if request.method == "POST":
        captcha_answer = request.POST.get("captcha_answer", "")
        if not _validate_login_captcha(request, captcha_answer):
            messages.error(request, _("Try again"), extra_tags="captcha-warning")
            return redirect('accounts:superadminlogin')
        username = request.POST.get("username")
        password = request.POST.get("password")

        user = authenticate(request, username=username, password=password)
        if user and user.role == 'superadmin':
            login(request, user)
            _clear_login_captcha(request)
            return redirect('accounts:superadmin_dashboard')
  # Redirect to dashboard after login
        else:
            messages.error(request, "Invalid credentials or not a Super Admin.")
            return redirect('accounts:superadminlogin')

    return render(request, "accounts/superadminlogin.html", {
        "captcha_prompt": captcha_prompt,
    })

User = get_user_model()

def _set_login_captcha(request):
    a = random.randint(1, 9)
    b = random.randint(1, 9)
    prompt = f"{a} + {b}"
    request.session['login_captcha_answer'] = str(a + b)
    request.session['login_captcha_prompt'] = prompt
    return prompt

def _ensure_login_captcha(request):
    prompt = request.session.get('login_captcha_prompt')
    if not prompt:
        prompt = _set_login_captcha(request)
    return prompt

def _validate_login_captcha(request, submitted_answer):
    expected = request.session.get('login_captcha_answer')
    is_valid = expected and submitted_answer and submitted_answer.strip() == str(expected)
    _set_login_captcha(request)
    return bool(is_valid)

def _clear_login_captcha(request):
    request.session.pop('login_captcha_answer', None)
    request.session.pop('login_captcha_prompt', None)

DAY_LABELS = [
    (0, "Mon"),
    (1, "Tue"),
    (2, "Wed"),
    (3, "Thu"),
    (4, "Fri"),
    (5, "Sat"),
]

def get_admin_referral_user_ids(admin_user, *, include_direct=True):
    """Return IDs of regular users in an admin's referral network.

    Args:
        admin_user: The admin whose network is being explored.
        include_direct: When False, omit users directly referred by the admin
            while still traversing through them to reach deeper invitees.
    """
    base_qs = CustomUser.objects.filter(role='user')
    first_level = list(base_qs.filter(referred_by=admin_user).values_list('id', flat=True))
    if not first_level:
        return []

    visited = set(first_level)
    collected = set(first_level) if include_direct else set()
    frontier = list(first_level)

    while frontier:
        next_level = list(base_qs.filter(referred_by_id__in=frontier).values_list('id', flat=True))
        frontier = []
        for user_id in next_level:
            if user_id in visited:
                continue
            visited.add(user_id)
            collected.add(user_id)
            frontier.append(user_id)

    return list(collected)

def get_admin_dashboard_network_ids(admin_user):
    """Return IDs (admin + two referral levels) for dashboard alerts."""
    direct_ids = list(CustomUser.objects.filter(referred_by=admin_user).values_list('id', flat=True))
    second_level_ids = list(CustomUser.objects.filter(referred_by__in=direct_ids).values_list('id', flat=True))
    return [admin_user.id] + direct_ids + second_level_ids

def get_admin_notification_counts(admin_user, network_ids=None):
    if network_ids is None:
        network_ids = get_admin_dashboard_network_ids(admin_user)

    pending_balance_requests_count = BalanceRequest.objects.filter(status="pending").count()

    pending_withdrawals_count = UserWithdrawal.objects.filter(
        status='PENDING',
        user_id__in=network_ids
    ).count()
    processing_withdrawals_count = UserWithdrawal.objects.filter(
        status='PROCESSING',
        user_id__in=network_ids
    ).count()

    unread_events_count = get_admin_dashboard_events_queryset(admin_user).filter(is_read=False).count()

    return {
        "pending_balance_requests_count": pending_balance_requests_count,
        "pending_withdrawals_count": pending_withdrawals_count,
        "processing_withdrawals_count": processing_withdrawals_count,
        "total_notifications": unread_events_count,
    }

def get_admin_dashboard_events_queryset(admin_user):
    network_ids = get_admin_dashboard_network_ids(admin_user)
    return AdminDashboardEvent.objects.filter(user_id__in=network_ids)

def build_weekly_activity_for_admin(admin_user):
    """Compile weekly (Mon-Sat) metrics for registrations and withdrawals."""
    user_ids = get_admin_referral_user_ids(admin_user, include_direct=False)

    if not user_ids:
        return []

    registrations = (
        CustomUser.objects.filter(id__in=user_ids, date_joined__isnull=False)
        .annotate(day=TruncDate('date_joined'))
        .values('day')
        .annotate(count=Count('id'))
    )
    registration_map = {entry['day']: entry['count'] for entry in registrations if entry['day']}

    withdrawals = (
        UserWithdrawal.objects.filter(user_id__in=user_ids)
        .values('user_id', 'created_at')
        .order_by('user_id', 'created_at', 'id')
    )
    withdrawal_map = {}
    last_user = None
    rank = 0
    for entry in withdrawals:
        user_id = entry['user_id']
        created_at = entry['created_at']
        if not created_at:
            continue
        if user_id != last_user:
            rank = 1
            last_user = user_id
        else:
            rank += 1
        if rank > 3:
            continue
        day = created_at.date()
        withdrawal_map[(day, rank)] = withdrawal_map.get((day, rank), 0) + 1

    if not registration_map and not withdrawal_map:
        return []

    all_days = list(registration_map.keys()) + [key[0] for key in withdrawal_map.keys()]
    earliest = min(all_days)
    latest = max(all_days)

    start_week = earliest - timedelta(days=earliest.weekday())
    end_week = latest - timedelta(days=latest.weekday())

    weeks = []
    current = start_week
    while current <= end_week:
        week_days = []
        for offset, label in DAY_LABELS:
            day_date = current + timedelta(days=offset)
            metrics = {
                'registrations': registration_map.get(day_date, 0),
                'first_withdrawals': withdrawal_map.get((day_date, 1), 0),
                'second_withdrawals': withdrawal_map.get((day_date, 2), 0),
                'third_withdrawals': withdrawal_map.get((day_date, 3), 0),
            }
            week_days.append({
                'date': day_date,
                'label': label,
                'metrics': metrics,
            })

        week_end = current + timedelta(days=5)
        weeks.append({
            'label': f"{current.strftime('%b %d')} - {week_end.strftime('%b %d, %Y')}",
            'start': current,
            'end': week_end,
            'days': week_days,
        })
        current += timedelta(days=7)

    weeks.sort(key=lambda w: w['start'], reverse=True)
    return weeks

def chunk_weeks(weeks, chunk_size=4):
    for i in range(0, len(weeks), chunk_size):
        yield weeks[i:i + chunk_size]

def get_owner_admin(user):
    current = getattr(user, 'referred_by', None)
    visited = set()
    while current and current.id not in visited:
        visited.add(current.id)
        if current.role == 'admin':
            return current
        current = current.referred_by
    return None

def is_superadmin(user):
    return user.is_authenticated and user.role == 'superadmin'

def generate_admin_referral_code():
    """Generate a unique 6-character uppercase referral code for Admins."""
    return ''.join(random.choices(string.ascii_uppercase, k=6))


@login_required
@user_passes_test(is_superadmin)
def superadmin_dashboard(request):
    from django.contrib.sessions.models import Session
    from django.utils import timezone as tz
    from datetime import timedelta
    
    # Fetch all Admins and Customer Service accounts, sorted by online status
    admins_cs = User.objects.filter(role__in=['admin', 'customerservice'])

    # Fetch the single superadmin wallet (if exists)
    wallet = SuperAdminWallet.objects.first()

    if request.method == "POST":
        action = request.POST.get("action")
        target_id = request.POST.get("user_id")
        target_user = None

        # Fetch target user for delete, reset password, freeze, and unfreeze actions
        if action in ["delete", "reset_password", "freeze", "unfreeze"]:
            target_user = get_object_or_404(User, id=target_id, role__in=['admin', 'customerservice'])

        # Create new Admin or Customer Service
        if action == "create":
            username = request.POST.get("username")
            password = request.POST.get("password")
            role = request.POST.get("role")

            if not all([username, password, role]):
                messages.error(request, "All fields are required.")
            elif role not in ['admin', 'customerservice']:
                messages.error(request, "Invalid role selected.")
            elif User.objects.filter(username=username).exists():
                messages.error(request, "Username already exists.")
            else:
                referral_code = generate_admin_referral_code() if role == "admin" else None
                User.objects.create_user(
                    username=username,
                    password=password,
                    role=role,
                    referral_code=referral_code
                )
                messages.success(request, f"{role.capitalize()} created successfully.")
            return redirect('accounts:superadmin_dashboard')

        # Delete Admin or Customer Service
        elif action == "delete" and target_user:
            target_user.delete()
            messages.success(request, f"{target_user.role.capitalize()} deleted successfully.")
            return redirect('accounts:superadmin_dashboard')

        # Reset password for Admin or Customer Service
        elif action == "reset_password" and target_user:
            new_password = request.POST.get("new_password")
            superadmin_password = request.POST.get("superadmin_password")
            
            if not new_password:
                messages.error(request, "Password cannot be empty.")
            elif not superadmin_password:
                messages.error(request, "Super Admin password is required for security verification.")
            elif not request.user.check_password(superadmin_password):
                messages.error(request, "Invalid Super Admin password. Access denied.")
            else:
                target_user.set_password(new_password)
                target_user.save()
                messages.success(request, f"{target_user.role.capitalize()} password reset successfully.")
            return redirect('accounts:superadmin_dashboard')
        
        # Freeze Admin or Customer Service
        elif action == "freeze" and target_user:
            target_user.is_frozen = True
            target_user.save(update_fields=['is_frozen'])
            
            # Force logout by deleting all active sessions for this user
            all_sessions = Session.objects.filter(expire_date__gte=tz.now())
            for session in all_sessions:
                session_data = session.get_decoded()
                if session_data.get('_auth_user_id') == str(target_user.id):
                    session.delete()
            
            messages.success(request, f"{target_user.role.capitalize()} '{target_user.username}' has been frozen and logged out.")
            return redirect('accounts:superadmin_dashboard')
        
        # Unfreeze Admin or Customer Service
        elif action == "unfreeze" and target_user:
            target_user.is_frozen = False
            target_user.save(update_fields=['is_frozen'])
            messages.success(request, f"{target_user.role.capitalize()} '{target_user.username}' has been unfrozen.")
            return redirect('accounts:superadmin_dashboard')

        # Handle Super Admin Wallet (single wallet logic)
        elif action == "wallet_create":
            address = request.POST.get("address")
            wallet_password = request.POST.get("wallet_password")
            
            if not address:
                messages.error(request, "Wallet address is required.")
            else:
                # If wallet exists and has password, verify it
                if wallet and wallet.wallet_password:
                    if not wallet_password:
                        messages.error(request, "Wallet password is required to update wallet.")
                        return redirect('accounts:superadmin_dashboard')
                    if not wallet.check_wallet_password(wallet_password):
                        messages.error(request, "Incorrect wallet password.")
                        return redirect('accounts:superadmin_dashboard')
                
                if wallet:  # update existing
                    wallet.address = address
                    wallet.save()
                    messages.success(request, "Wallet updated successfully.")
                else:  # create new
                    SuperAdminWallet.objects.create(address=address)
                    messages.success(request, "Wallet created successfully.")
            return redirect('accounts:superadmin_dashboard')
        
        # Set wallet password
        elif action == "set_wallet_password":
            new_wallet_password = request.POST.get("new_wallet_password")
            confirm_password = request.POST.get("confirm_wallet_password")
            
            if not wallet:
                messages.error(request, "Please create a wallet first.")
            elif not new_wallet_password or not confirm_password:
                messages.error(request, "Both password fields are required.")
            elif new_wallet_password != confirm_password:
                messages.error(request, "Passwords do not match.")
            else:
                wallet.set_wallet_password(new_wallet_password)
                messages.success(request, "Wallet password set successfully.")
            return redirect('accounts:superadmin_dashboard')

    # Separate admins and customer service for the template, sorted by online status
    # Online users first (by most recent activity), then offline users (by last seen)
    admins = admins_cs.filter(role='admin').order_by('-last_activity')
    customer_service = admins_cs.filter(role='customerservice').order_by('-last_activity')
    
    # Separate into online and offline for better sorting
    online_threshold = tz.now() - timedelta(minutes=5)
    admins = list(admins)
    admins.sort(key=lambda x: (not (x.last_activity and x.last_activity >= online_threshold), 
                               -(x.last_activity.timestamp() if x.last_activity else 0)))
    for admin in admins:
        weekly_weeks = build_weekly_activity_for_admin(admin)
        admin.weekly_activity_pages = [
            {
                'weeks': page,
                'index': idx + 1,
            }
            for idx, page in enumerate(chunk_weeks(weekly_weeks, 4))
        ]

    customer_service = list(customer_service)
    customer_service.sort(key=lambda x: (not (x.last_activity and x.last_activity >= online_threshold), 
                                         -(x.last_activity.timestamp() if x.last_activity else 0)))

    dashboard_refreshed_at = tz.now()
    admin_stats = {
        "total": len(admins),
        "online": sum(1 for user in admins if user.is_online),
        "frozen": sum(1 for user in admins if user.is_frozen),
    }
    cs_stats = {
        "total": len(customer_service),
        "online": sum(1 for user in customer_service if user.is_online),
        "frozen": sum(1 for user in customer_service if user.is_frozen),
    }
    
    return render(request, "accounts/superadmin_dashboard.html", {
        "admins": admins,
        "customer_service": customer_service,
        "wallet": wallet,
        "admin_stats": admin_stats,
        "cs_stats": cs_stats,
        "dashboard_refreshed_at": dashboard_refreshed_at,
    })

def adminlogin(request):
    """
    Admin login page.
    Only users with role='admin' can log in.
    """
    captcha_prompt = _ensure_login_captcha(request)
    if request.method == "POST":
        captcha_answer = request.POST.get("captcha_answer", "")
        if not _validate_login_captcha(request, captcha_answer):
            messages.error(request, _("Try again"), extra_tags="captcha-warning")
            return redirect('accounts:adminlogin')
        username = request.POST.get("username")
        password = request.POST.get("password")

        user = authenticate(request, username=username, password=password)
        if user and user.role == 'admin':
            login(request, user)
            _clear_login_captcha(request)
            return redirect('accounts:admin_dashboard')

        else:
            messages.error(request, "Invalid credentials or not an Admin.")
            return redirect('accounts:adminlogin')

    return render(request, "accounts/adminlogin.html", {
        "captcha_prompt": captcha_prompt,
    })

def is_admin(user):
    return user.is_authenticated and user.role == 'admin'

def customerservicelogin(request):
    """
    Customer Service login page.
    Only users with role='customerservice' can log in.
    """
    captcha_prompt = _ensure_login_captcha(request)
    if request.method == "POST":
        captcha_answer = request.POST.get("captcha_answer", "")
        if not _validate_login_captcha(request, captcha_answer):
            messages.error(request, _("Try again"), extra_tags="captcha-warning")
            return redirect('accounts:customerservicelogin')
        username = request.POST.get("username")
        password = request.POST.get("password")

        user = authenticate(request, username=username, password=password)
        if user and user.role == 'customerservice':
            login(request, user)
            _clear_login_captcha(request)
            return redirect('accounts:customerservice_dashboard')
        else:
            messages.error(request, "Invalid credentials or not Customer Service.")
            return redirect('accounts:customerservicelogin')

    return render(request, "accounts/customerservicelogin.html", {
        "captcha_prompt": captcha_prompt,
    })

@user_passes_test(lambda u: u.is_authenticated and u.role == 'customerservice')
# at top of your views file






@user_passes_test(lambda u: u.is_authenticated and u.role == 'customerservice')
def customerservice_dashboard(request):
    """
    Customer Service dashboard:
    - View all Regular Users
    - Reset login and fund passwords
    - Delete Regular Users (wipes all fields safely before delete)
      Deleting a user does NOT affect their referrals.
    """
    # Get search query
    search_query = request.GET.get('q', '').strip()
    
    # Start with all regular users
    regular_users = (
        CustomUser.objects
        .filter(role='user')
        .select_related('userwalletaddress', 'referred_by')
        .order_by('-last_activity')
    )
    
    # Apply search filter if query exists
    if search_query:
        regular_users = regular_users.filter(
            Q(username__icontains=search_query) | 
            Q(phone__icontains=search_query)
        )

    regular_users = list(regular_users)
    user_ids = [user.id for user in regular_users]
    wallet_map = {
        wallet.user_id: wallet
        for wallet in Wallet.objects.filter(user_id__in=user_ids)
    }
    for user in regular_users:
        user.owner_admin = get_owner_admin(user)
        user.wallet_snapshot = wallet_map.get(user.id)

    if request.method == "POST":
        action = request.POST.get("action")
        target_id = request.POST.get("user_id")
        target_user = get_object_or_404(CustomUser, id=target_id, role='user')

        if action == "delete":
            # Delete the user completely from database
            target_user.delete()
            messages.success(request, f"User {target_user.username} deleted permanently from database.")
            return redirect('accounts:customerservice_dashboard')

        elif action == "reset_login_password":
            new_password = request.POST.get("new_password")
            if not new_password:
                messages.error(request, "Login password cannot be empty.")
            else:
                target_user.set_password(new_password)
                target_user.save(update_fields=['password'])
                messages.success(request, f"Login password for {target_user.username} reset successfully.")
            return redirect('accounts:customerservice_dashboard')

        elif action == "reset_fund_password":
            new_fund_password = request.POST.get("new_fund_password")
            if not new_fund_password:
                messages.error(request, "Fund password cannot be empty.")
            else:
                target_user.fund_password = new_fund_password
                target_user.save(update_fields=['fund_password'])
                messages.success(request, f"Fund password for {target_user.username} reset successfully.")
            return redirect('accounts:customerservice_dashboard')

        elif action == "freeze":
            target_user.is_frozen = True
            target_user.save(update_fields=['is_frozen'])
            
            # Force logout by deleting all active sessions for this user
            try:
                all_sessions = Session.objects.filter(expire_date__gte=tz.now())
                for session in all_sessions:
                    try:
                        session_data = session.get_decoded()
                        if session_data.get('_auth_user_id') == str(target_user.id):
                            session.delete()
                    except (AttributeError, TypeError):
                        # Skip sessions that can't be decoded
                        continue
            except Exception as e:
                # If session deletion fails, still freeze the user
                pass
            
            messages.success(request, f"User {target_user.username} frozen - organization rule violated.")
            return redirect('accounts:customerservice_dashboard')

        elif action == "unfreeze":
            target_user.is_frozen = False
            target_user.save(update_fields=['is_frozen'])
            messages.success(request, f"User {target_user.username} has been unfrozen.")
            return redirect('accounts:customerservice_dashboard')

        elif action == "update_wallet_address":
            address = request.POST.get("wallet_address", "").strip()
            network = request.POST.get("network", "")
            wallet_obj = getattr(target_user, 'userwalletaddress', None)

            if not address or not network:
                messages.error(request, "Wallet address and network are required.")
            elif network not in dict(CRYPTO_NETWORK_CHOICES):
                messages.error(request, "Invalid network selected.")
            elif UserWalletAddress.objects.filter(address=address).exclude(user=target_user).exists():
                messages.error(request, "This wallet address is already linked to another user.")
            else:
                if wallet_obj:
                    wallet_obj.address = address
                    wallet_obj.network = network
                    wallet_obj.save(update_fields=['address', 'network'])
                    messages.success(request, f"Wallet address updated for {target_user.username}.")
                else:
                    UserWalletAddress.objects.create(user=target_user, address=address, network=network)
                    messages.success(request, f"Wallet address added for {target_user.username}.")
            return redirect('accounts:customerservice_dashboard')

        elif action == "delete_wallet_address":
            wallet_obj = getattr(target_user, 'userwalletaddress', None)
            if wallet_obj:
                wallet_obj.delete()
                messages.success(request, f"Wallet address removed for {target_user.username}.")
            else:
                messages.error(request, "User does not have a wallet address to delete.")
            return redirect('accounts:customerservice_dashboard')

        elif action == "adjust_balance":
            balance_field = request.POST.get("balance_field")
            adjustment_type = request.POST.get("adjustment_type", "").lower()
            amount_raw = (request.POST.get("amount") or "").strip()
            note = (request.POST.get("note") or "").strip()

            field_map = {
                "current_balance": "current_balance",
                "cumulative_total": "cumulative_total",
                "product_commission": "product_commission",
                "referral_commission": "referral_commission",
            }

            if balance_field not in field_map:
                messages.error(request, "Invalid balance field selected.")
                return redirect('accounts:customerservice_dashboard')

            if adjustment_type not in {"credit", "debit"}:
                messages.error(request, "Invalid adjustment type.")
                return redirect('accounts:customerservice_dashboard')

            try:
                amount = Decimal(amount_raw)
            except Exception:
                messages.error(request, "Amount must be a valid number.")
                return redirect('accounts:customerservice_dashboard')

            if amount <= 0:
                messages.error(request, "Amount must be greater than zero.")
                return redirect('accounts:customerservice_dashboard')

            delta = amount if adjustment_type == "credit" else -amount
            note = note[:255] or f"{adjustment_type.title()} ${amount}"

            field_name = field_map[balance_field]

            try:
                with transaction.atomic():
                    wallet = (
                        Wallet.objects.select_for_update()
                        .filter(user=target_user)
                        .first()
                    )
                    if not wallet:
                        wallet = Wallet.objects.create(user=target_user)

                    current_value = getattr(wallet, field_name, Decimal("0.00")) or Decimal("0.00")
                    new_value = current_value + delta
                    if new_value < 0:
                        messages.error(
                            request,
                            f"Cannot debit {field_name.replace('_', ' ')} below $0.00."
                        )
                        raise ValueError("Negative balance not allowed")

                    setattr(wallet, field_name, new_value)
                    wallet.save(update_fields=[field_name])

                    CustomerServiceBalanceAdjustment.objects.create(
                        target_user=target_user,
                        acted_by=request.user,
                        field=field_name,
                        delta=delta,
                        note=note,
                    )
            except ValueError:
                return redirect('accounts:customerservice_dashboard')

            messages.success(
                request,
                f"{adjustment_type.title()} of ${amount} applied to {target_user.username}'s {balance_field.replace('_', ' ')}."
            )
            return redirect('accounts:customerservice_dashboard')

    # Get unread notifications count
    unread_notifications_count = Notification.objects.filter(
        recipient=request.user,
        is_read=False
    ).count()

    guest_threads = list_sessions()
    guest_unread_count = sum(thread.get('unread_for_cs', 0) for thread in guest_threads)
    
    context = {
        "users": regular_users,
        "network_choices": CRYPTO_NETWORK_CHOICES,
        "unread_notifications_count": unread_notifications_count,
        "guest_unread_count": guest_unread_count,
    }
    return render(request, "accounts/customerservice_dashboard.html", context)

@login_required
@user_passes_test(lambda u: u.role == 'customerservice')
@require_GET
def customerservice_guest_unread(request):
    guest_threads = list_sessions()
    guest_unread_count = sum(thread.get('unread_for_cs', 0) for thread in guest_threads)
    active_guest_threads = len(guest_threads)
    return JsonResponse({
        "guest_unread_count": guest_unread_count,
        "active_guest_threads": active_guest_threads,
    })

@user_passes_test(lambda u: u.is_authenticated and u.role == 'customerservice')
def admin_overview_for_cs(request, admin_id):
    admin_user = get_object_or_404(CustomUser, id=admin_id, role='admin')
    user_ids = get_admin_referral_user_ids(admin_user)
    users = CustomUser.objects.filter(id__in=user_ids).select_related('userwalletaddress').order_by('username')
    return render(request, "accounts/cs_admin_overview.html", {
        "admin_user": admin_user,
        "users": users,
    })

def user_register(request):
    """
    Regular User registration:
    - Requires phone, username, password, fund password
    - Accepts Admin or Regular User referral code
    - Admin referral codes can be used unlimited times
    - Regular User referral codes can only be used once
    - Generates own 6-character uppercase referral code
    """
    if request.method == "POST":
        phone = request.POST.get("phone")
        username = request.POST.get("username")
        password = request.POST.get("password")
        fund_password = request.POST.get("fund_password")
        referral_code_input = request.POST.get("referral_code")

        # Validate all fields not empty
        if not all([phone, username, password, fund_password, referral_code_input]):
            messages.error(request, "All fields are required.")
            return redirect('accounts:user_register')

        # -------------------------
        # New input validation rules
        # -------------------------
        import re
        # 1. phone number must be + and numbers only, max 15
        if not re.fullmatch(r'^\+?\d{1,15}$', phone):
            messages.error(request, "Phone number must be numeric and may start with + (max 15 digits).")
            return redirect('accounts:user_register')

        # 2. username length 6–15
        if not (6 <= len(username) <= 15):
            messages.error(request, "Username must be between 6 and 15 characters.")
            return redirect('accounts:user_register')

        # 3. password length 6–15
        if not (6 <= len(password) <= 15):
            messages.error(request, "Password must be between 6 and 15 characters.")
            return redirect('accounts:user_register')

        # 4. fund password length 6–15
        if not (6 <= len(fund_password) <= 15):
            messages.error(request, "Fund password must be between 6 and 15 characters.")
            return redirect('accounts:user_register')

        # 5. referral code exactly 6
        if len(referral_code_input) != 6:
            messages.error(request, "Referral code must be exactly 6 characters.")
            return redirect('accounts:user_register')
        # -------------------------

        # Find owner of referral code
        referrer = User.objects.filter(referral_code=referral_code_input).first()
        if not referrer or referrer.role not in ['admin', 'user']:
            messages.error(request, "Invalid referral code.")
            return redirect('accounts:user_register')

        # Enforce Regular User referral limit (only one user)
        if referrer.role == 'user':
            already_referred = User.objects.filter(referred_by=referrer).exists()
            if already_referred:
                messages.error(request, "This user's referral code has already been used.")
                return redirect('accounts:user_register')

        # Check unique username and phone
        if User.objects.filter(username=username).exists():
            messages.error(request, "Username already exists. Please choose a different username.")
            return redirect('accounts:user_register')

        if User.objects.filter(phone=phone).exists():
            messages.error(request, "Phone number already exists. Please use a different phone number.")
            return redirect('accounts:user_register')

        # Generate own 6-character uppercase referral code
        user_referral_code = ''.join(random.choices(string.ascii_uppercase, k=6))

        # Create Regular User with try-catch for integrity errors
        try:
            new_user = User.objects.create(
                username=username,
                phone=phone,
                password=make_password(password),
                fund_password=fund_password,
                role='user',
                referral_code=user_referral_code,
                referred_by=referrer
            )
        except Exception as e:
            # Handle any database integrity errors
            if "UNIQUE constraint failed" in str(e) and "phone" in str(e):
                messages.error(request, "Phone number already exists. Please use a different phone number.")
            elif "UNIQUE constraint failed" in str(e) and "username" in str(e):
                messages.error(request, "Username already exists. Please choose a different username.")
            else:
                messages.error(request, "Registration failed. Please try again.")
            return redirect('accounts:user_register')

        notify_roles(
            roles=("customerservice",),
            title="New user registration",
            message=f"{new_user.username} joined via referral {referrer.referral_code}.",
            category="user_register",
            target_url=reverse('accounts:customerservice_dashboard'),
            metadata={
                "username": new_user.username,
                "phone": new_user.phone,
                "referrer": getattr(referrer, "username", ""),
                "referrer_role": referrer.role,
                "event": "user_register",
                "status": "created",
                "user_id": new_user.id,
            }
        )

        messages.success(request, "Registration successful! Please login.")
        return redirect('accounts:user_login')  # <-- redirect to user login page

    return render(request, "accounts/user_register.html")


from django.contrib.auth import authenticate, login
from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth import get_user_model

User = get_user_model()

def user_login(request):
    """
    Regular User login:
    - Can login using username or phone
    - Must have role='user'
    - Redirects to products page after successful login
    """
    if request.method == "POST":
        identifier = request.POST.get("identifier")  # phone or username
        password = request.POST.get("password")

        user = None
        try:
            user = User.objects.get(role='user', username=identifier)
        except User.DoesNotExist:
            try:
                user = User.objects.get(role='user', phone=identifier)
            except User.DoesNotExist:
                messages.error(request, "Invalid credentials.")
                return redirect('accounts:user_login')

        if user and user.check_password(password):
            # Check if user is frozen
            if user.is_frozen:
                messages.error(request, "organization rules violated, please contact customserservice .")
                return redirect('accounts:user_login')

            # ensure we authenticate via the default ModelBackend so Django knows the backend
            authenticated = authenticate(request, username=user.username, password=password)
            if authenticated is None:
                messages.error(request, "Unable to authenticate. Please try again.")
                return redirect('accounts:user_login')

            login(request, authenticated)
            return redirect('accounts:index')  # or whatever URL name points to your index view  # Redirect to home dashboard

        else:
            messages.error(request, "Invalid credentials.")
            return redirect('accounts:user_login')

    
    return render(request, 'accounts/user_login.html')
       

@login_required
def profile_view(request):
    return render(request, 'accounts/profile.html')

@login_required
def payment_view(request):
    return render(request, 'accounts/payment.html')

@login_required
def settings_view(request):
    return render(request, 'accounts/settings.html')

@login_required
def faq_view(request):
    return render(request, 'accounts/faq.html')

@login_required
def activities_view(request):
    """
    Display the activities page (used by accounts/activities.html).
    """
    user = request.user
    now = tz.now()
    today = now.date()
    seven_days_ago = now - timedelta(days=7)

    completed_tasks_today = UserProductTask.objects.filter(
        user=user,
        is_completed=True,
        completed_at__date=today
    ).count()

    finance_activity_count = (
        RechargeRequest.objects.filter(user=user, created_at__gte=seven_days_ago).count()
        + UserWithdrawal.objects.filter(user=user, created_at__gte=seven_days_ago).count()
    )

    support_ticket_count = Notification.objects.filter(
        recipient=user,
        created_at__gte=seven_days_ago
    ).count()

    activity_entries = []

    def add_entry(**entry):
        timestamp = entry.get("timestamp")
        if timestamp:
            activity_entries.append(entry)

    # User task completions
    task_qs = (
        UserProductTask.objects.filter(
            user=user,
            is_completed=True,
            completed_at__isnull=False
        )
        .select_related('product')
        .order_by('-completed_at')[:25]
    )
    for task in task_qs:
        product_name = task.product.name if task.product else _("Product task")
        add_entry(
            timestamp=task.completed_at,
            category='task',
            icon_text='T',
            icon_class='task',
            title=_("Task commission earned"),
            description=_("Completed %(product)s task.") % {"product": product_name},
            reference=f"TK-{task.id}",
            status_label=_("Success"),
            status_class='status-success',
            amount=task.price if task.price is not None else None,
        )

    # Recharge requests
    recharge_qs = RechargeRequest.objects.filter(user=user).order_by('-created_at')[:25]
    recharge_status_map = {
        "pending": ("status-pending", _("Pending")),
        "approved": ("status-success", _("Approved")),
        "rejected": ("status-failed", _("Rejected")),
    }
    for recharge in recharge_qs:
        status_class, status_label = recharge_status_map.get(
            recharge.status, ("status-pending", recharge.get_status_display())
        )
        add_entry(
            timestamp=recharge.created_at,
            category='finance',
            icon_text='$',
            icon_class='finance',
            title=_("Recharge request"),
            description=_("Recharge of %(amount)s is %(status)s.") % {
                "amount": recharge.amount,
                "status": recharge.get_status_display(),
            },
            reference=f"RC-{recharge.id}",
            status_label=status_label,
            status_class=status_class,
            amount=recharge.amount,
        )

    # Balance requests (legacy withdrawals)
    balance_qs = BalanceRequest.objects.filter(user=user).order_by('-requested_at')[:25]
    balance_status_map = {
        "pending": ("status-pending", _("Pending")),
        "approved": ("status-success", _("Approved")),
        "rejected": ("status-failed", _("Rejected")),
    }
    for request_entry in balance_qs:
        status_class, status_label = balance_status_map.get(
            request_entry.status, ("status-pending", request_entry.get_status_display())
        )
        add_entry(
            timestamp=request_entry.requested_at,
            category='finance',
            icon_text='$',
            icon_class='finance',
            title=_("Balance request"),
            description=_("Balance request of %(amount)s is %(status)s.") % {
                "amount": request_entry.amount,
                "status": request_entry.get_status_display(),
            },
            reference=f"BR-{request_entry.id}",
            status_label=status_label,
            status_class=status_class,
            amount=request_entry.amount,
        )

    # User withdrawals
    withdrawal_qs = UserWithdrawal.objects.filter(user=user).order_by('-created_at')[:25]
    withdrawal_status_map = {
        "PENDING": ("status-pending", _("Pending")),
        "PROCESSING": ("status-pending", _("Processing")),
        "APPROVED": ("status-success", _("Approved")),
        "REJECTED": ("status-failed", _("Rejected")),
        "CANCELLED": ("status-failed", _("Cancelled")),
    }
    for withdrawal in withdrawal_qs:
        status_class, status_label = withdrawal_status_map.get(
            withdrawal.status, ("status-pending", withdrawal.get_status_display())
        )
        add_entry(
            timestamp=withdrawal.created_at,
            category='finance',
            icon_text='$',
            icon_class='finance',
            title=_("Withdrawal request"),
            description=_("Withdrawal of %(amount)s via %(network)s.") % {
                "amount": withdrawal.amount,
                "network": withdrawal.get_network_display(),
            },
            reference=f"WD-{withdrawal.id}",
            status_label=status_label,
            status_class=status_class,
            amount=withdrawal.amount,
        )

    # System notifications
    notification_qs = Notification.objects.filter(recipient=user).order_by('-created_at')[:25]
    for notification in notification_qs:
        status_class = 'status-success' if notification.is_read else 'status-pending'
        status_label = _("Read") if notification.is_read else _("Unread")
        add_entry(
            timestamp=notification.created_at,
            category='system',
            icon_text='!',
            icon_class='system',
            title=notification.title,
            description=notification.message,
            reference=f"NT-{notification.id}",
            status_label=status_label,
            status_class=status_class,
        )

    activities = sorted(
        activity_entries,
        key=lambda entry: entry["timestamp"],
        reverse=True,
    )[:40]

    recharge_history_qs = RechargeHistory.objects.filter(user=user).order_by('-action_date')[:10]
    recharge_history = []
    for record in recharge_history_qs:
        status_class = 'status-success' if record.status == 'approved' else 'status-failed'
        recharge_history.append({
            "id": f"RH-{record.id}",
            "amount": record.amount,
            "status_label": record.get_status_display(),
            "status_class": status_class,
            "timestamp": record.action_date,
            "voucher_url": record.voucher_file.url if record.voucher_file else None,
        })

    withdraw_history = []
    for withdrawal in withdrawal_qs[:10]:
        status_class, status_label = withdrawal_status_map.get(
            withdrawal.status, ("status-pending", withdrawal.get_status_display())
        )
        withdraw_history.append({
            "id": f"WD-{withdrawal.id}",
            "amount": withdrawal.amount,
            "network": withdrawal.get_network_display(),
            "status_label": status_label,
            "status_class": status_class,
            "timestamp": withdrawal.created_at,
        })

    recharge_latest = recharge_history[:2]
    recharge_more = recharge_history[2:]
    withdraw_latest = withdraw_history[:2]
    withdraw_more = withdraw_history[2:]

    context = {
        'completed_tasks_today': completed_tasks_today,
        'finance_activity_count': finance_activity_count,
        'support_ticket_count': support_ticket_count,
        'activities': activities,
        'recharge_history': recharge_history,
        'withdraw_history': withdraw_history,
        'recharge_latest': recharge_latest,
        'recharge_more': recharge_more,
        'withdraw_latest': withdraw_latest,
        'withdraw_more': withdraw_more,
    }

    return render(request, 'accounts/activities.html', context)

@login_required
def logout_view(request):
    role = getattr(request.user, "role", None)
    logout(request)

    role_redirects = {
        'superadmin': 'accounts:superadminlogin',
        'admin': 'accounts:adminlogin',
        'customerservice': 'accounts:customerservicelogin',
        'user': 'accounts:user_login',
    }
    target = role_redirects.get(role, 'accounts:user_login')
    return redirect(target)

@login_required
def balance_view(request):
    return render(request, 'accounts/balance.html')

from django.contrib.auth.decorators import user_passes_test
from django.contrib import messages
from django.db import transaction
from balance.models import (
    RechargeHistory,
    RechargeRequest,
    Voucher,
    BalanceRequest,
    Wallet,
    CustomerServiceBalanceAdjustment,
)
from stoppoints.models import StopPoint
from django.shortcuts import render, redirect
from django.contrib import messages
from decimal import Decimal
from django.db.models import Sum, Q
from django.shortcuts import render, get_object_or_404, redirect
from accounts.models import CustomUser
from django.contrib.auth.decorators import user_passes_test
from django.contrib import messages
from balance.models import RechargeRequest, Voucher
# (also import approve_recharge / reject_recharge from wherever you defined them)

def is_admin(user):
    return user.is_authenticated and user.role == 'admin'
from balance.models import RechargeRequest, Voucher, BalanceRequest, RechargeHistory
from stoppoints.models import StopPoint
from django.shortcuts import render, redirect
from django.contrib import messages
from decimal import Decimal
from django.db.models import Sum, Q
from django.shortcuts import render
from django.http import JsonResponse

from django.views.decorators.http import require_http_methods
import json


def home_dashboard(request):
    user = request.user
    today = tz.now().date()

    wallet, _ = Wallet.objects.get_or_create(
        user=user,
        defaults={
            'current_balance': Decimal('0.00'),
            'product_commission': Decimal('0.00'),
            'referral_commission': Decimal('0.00'),
            'cumulative_total': Decimal('0.00')
        }
    )

    active_task_exists = UserProductTask.objects.filter(user=user, is_completed=False).exists()
    tasks_completed = UserProductTask.objects.filter(user=user, is_completed=True).count()
    next_task_number = tasks_completed + 1 if tasks_completed is not None else 1
    pending_stop_point = (
        StopPoint.objects
        .filter(user=user, point=next_task_number, status='pending')
        .order_by('order')
        .first()
    )
    is_stop_point_blocked = False
    if pending_stop_point:
        required_balance_value = pending_stop_point.required_balance or Decimal('0.00')
        if wallet.current_balance < required_balance_value:
            is_stop_point_blocked = True

    today_commissions = Commission.objects.filter(
        user=user,
        created_at__date=today
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    featured_products = Product.objects.filter(is_active=True).order_by('?')[:6]
    feature_gallery_images = _load_feature_gallery_images()
    if not feature_gallery_images:
        feature_gallery_images = [
            "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?auto=format&fit=crop&w=320&q=70",
            "https://images.unsplash.com/photo-1512499617640-c2f999098c01?auto=format&fit=crop&w=320&q=70",
            "https://images.unsplash.com/photo-1503602642458-232111445657?auto=format&fit=crop&w=320&q=70",
            "https://images.unsplash.com/photo-1526170375885-4d8ecf77b99f?auto=format&fit=crop&w=320&q=70",
            "https://images.unsplash.com/photo-1517336714731-489689fd1ca8?auto=format&fit=crop&w=320&q=70",
            "https://images.unsplash.com/photo-1470246973918-29a93221c455?auto=format&fit=crop&w=320&q=70",
            "https://images.unsplash.com/photo-1491553895911-0055eca6402d?auto=format&fit=crop&w=320&q=70",
            "https://images.unsplash.com/photo-1505740106531-4243f3831c78?auto=format&fit=crop&w=320&q=70",
            "https://images.unsplash.com/photo-1483985988355-763728e1935b?auto=format&fit=crop&w=320&q=70",
            "https://images.unsplash.com/photo-1441986300917-64674bd600d8?auto=format&fit=crop&w=320&q=70",
        ]

    recent_withdrawals = BalanceRequest.objects.filter(user=user).order_by('-requested_at')[:5]
    recent_recharges = RechargeRequest.objects.filter(user=user).order_by('-created_at')[:5]
    wallet_address = UserWalletAddress.objects.filter(user=user).first()

    mission_cta_label = 'Continue task' if (is_stop_point_blocked or active_task_exists) else 'Start task'

    context = {
        'user': user,
        'wallet': wallet,
        'wallet_address': wallet_address,

        'current_balance': wallet.current_balance,
        'total_balance': wallet.cumulative_total,
        'product_commission': wallet.product_commission,
        'referral_commission': wallet.referral_commission,
        'today_commissions': today_commissions,
        'featured_products': featured_products,
        'recent_withdrawals': recent_withdrawals,
        'recent_recharges': recent_recharges,
        'feature_gallery_images': feature_gallery_images,

        'is_stop_point_blocked': is_stop_point_blocked,
        'mission_cta_label': mission_cta_label,

        'now': tz.now(),
    }
   
    return render(request, 'index.html', context)

def me_view(request):
    wallet = Wallet.objects.filter(user=request.user).only('current_balance').first()
    user_balance = wallet.current_balance if wallet else Decimal('0.00')

    context = {
        'user_balance': user_balance,
        'language_info_list': [
            {
                'code': code,
                'name': get_language_info(code).get('name'),
                'name_local': get_language_info(code).get('name_local'),
            }
            for code, _label in settings.LANGUAGES
        ],
        'current_language_code': get_language(),
    }
    return render(request, 'accounts/me.html', context)


@login_required
@user_passes_test(is_admin)
@require_GET
def admin_dashboard_summary(request):
    """Return live notification counts for the admin dashboard header polling."""
    summary = get_admin_notification_counts(request.user)
    response = {
        "success": True,
        "pending_balance_requests_count": summary["pending_balance_requests_count"],
        "pending_withdrawals_count": summary["pending_withdrawals_count"],
        "processing_withdrawals_count": summary["processing_withdrawals_count"],
        "total_notifications": summary["total_notifications"],
    }
    return JsonResponse(response)


@login_required
@user_passes_test(is_admin)
@require_GET
def admin_dashboard_events(request):
    events = get_admin_dashboard_events_queryset(request.user).order_by('-created_at')[:10]

    data = [
        {
            "id": event.id,
            "event_type": event.event_type,
            "message": event.message,
            "created_at": event.created_at.isoformat(),
            "metadata": event.metadata,
        }
        for event in events
    ]
    return JsonResponse({"success": True, "events": data})


@login_required
@require_GET
def get_recharge_history(request, user_id):
    """
    API endpoint to get recharge history for a specific user.
    Only accessible by admin or the user themselves.
    """
    ...
    """
    API endpoint to get recharge history for a specific user.
    Only accessible by admin or the user themselves.
    """
    # Check if the requesting user is an admin or the same user
    if not (request.user.role in ['admin', 'superadmin'] or request.user.id == user_id):
        return JsonResponse({
            'success': False,
            'error': 'Unauthorized access'
        }, status=403)

    try:
        # Get the user
        user = get_object_or_404(CustomUser, id=user_id)
        
        # Get all recharge history for the user, ordered by most recent first
        history_entries = RechargeHistory.objects.filter(
            user=user
        ).select_related('recharge_request__voucher').order_by('-action_date')
        
        # Prepare the history data
        history_data = []
        for entry in history_entries:
            voucher_url = None

            if entry.voucher_file:
                voucher_url = entry.voucher_file.url
            elif entry.recharge_request_id:
                try:
                    voucher = entry.recharge_request.voucher
                    if getattr(voucher, 'file', None):
                        voucher_url = voucher.file.url
                except Voucher.DoesNotExist:
                    voucher_url = None

            history_data.append({
                'id': entry.id,
                'amount': str(entry.amount) if hasattr(entry, 'amount') else '0.00',
                'status': entry.status if hasattr(entry, 'status') else 'unknown',
                'action_date': entry.action_date.isoformat() if hasattr(entry, 'action_date') else '',
                'display_voucher_url': request.build_absolute_uri(voucher_url) if voucher_url else None,
                'description': f"Recharge of ${entry.amount} - {entry.status.capitalize()}" if hasattr(entry, 'amount') and hasattr(entry, 'status') else 'Recharge'
            })
        
        return JsonResponse({
            'success': True,
            'history': history_data
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

@login_required
@user_passes_test(is_admin)
def admin_dashboard(request):
    # Handle admin actions from the dashboard (e.g., set per-user daily task limit)
    if request.method == 'POST':
        is_json = request.content_type == 'application/json'
        if is_json:
            try:
                data = json.loads(request.body)
            except (TypeError, json.JSONDecodeError):
                data = {}
            action = data.get('action')
        else:
            data = request.POST
            action = data.get('action')

        if action == 'set_daily_limit':
            user_id = data.get('user_id')
            daily_limit = data.get('daily_limit')
            if is_json:
                try:
                    daily_limit_int = int(daily_limit)
                    if daily_limit_int < 1:
                        return JsonResponse({'success': False, 'error': 'Daily limit must be at least 1.'})
                    if daily_limit_int > 60:
                        return JsonResponse({'success': False, 'error': 'Daily limit cannot exceed 60.'})
                    cs, _ = CommissionSetting.objects.get_or_create(user_id=user_id)
                    cs.daily_task_limit = daily_limit_int
                    cs.save(update_fields=['daily_task_limit'])
                    return JsonResponse({'success': True})
                except (TypeError, ValueError):
                    return JsonResponse({'success': False, 'error': 'Invalid daily limit value.'})
            else:
                try:
                    daily_limit_int = int(daily_limit)
                    if daily_limit_int < 1:
                        messages.error(request, 'Daily limit must be at least 1.')
                    elif daily_limit_int > 60:
                        messages.error(request, 'Daily limit cannot exceed 60.')
                    else:
                        cs, _ = CommissionSetting.objects.get_or_create(user_id=user_id)
                        cs.daily_task_limit = daily_limit_int
                        cs.save(update_fields=['daily_task_limit'])
                        messages.success(request, f"Daily task limit updated for user {user_id} to {daily_limit_int}.")
                except (TypeError, ValueError):
                    messages.error(request, 'Invalid daily limit value.')
                return redirect('accounts:admin_dashboard')

    # Get search query and section
    search_query = request.GET.get('q', '').strip()
    current_section = request.GET.get('section', 'section-a')  # Default to section-a
    
    # Validate section parameter
    if current_section not in ['section-a', 'section-b']:
        current_section = 'section-a'

    # Get users referred by this admin or their direct referrals
    users = CustomUser.objects.filter(
        role='user',
        referred_by__in=[request.user] + list(CustomUser.objects.filter(referred_by=request.user).values_list('id', flat=True))
    ).distinct()

    # Apply search
    if search_query:
        users = users.filter(
            Q(username__icontains=search_query) | 
            Q(phone__icontains=search_query)
        )

    # Order by last login first (freshest at top), fallback to recent activity
    users = users.order_by(models.F('last_login').desc(nulls_last=True), '-last_activity')

    # Pagination - 20 users per page with proper page handling
    from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
    
    # Set number of users per page
    users_per_page = 20
    paginator = Paginator(users, users_per_page)
    
    # Get current page number from request, default to 1
    page = request.GET.get('page', 1)
    
    try:
        users = paginator.page(page)
    except PageNotAnInteger:
        # If page is not an integer, deliver first page
        users = paginator.page(1)
    except EmptyPage:
        # If page is out of range, deliver last page of results
        users = paginator.page(paginator.num_pages)
        
    # Get the page range for pagination controls (show max 5 page numbers at a time)
    page_range = paginator.get_elided_page_range(number=users.number, on_each_side=2, on_ends=1)

    # Prefetch related data to avoid N+1 queries
    user_ids = [user.id for user in users]

    # Get all stop points for these users
    stop_points = StopPoint.objects.filter(user_id__in=user_ids).order_by('point')
    stop_points_dict = {}
    for sp in stop_points:
        if sp.user_id not in stop_points_dict:
            stop_points_dict[sp.user_id] = []
        stop_points_dict[sp.user_id].append(sp)

    # Get all pending recharges
    pending_recharges = RechargeRequest.objects.filter(
        user_id__in=user_ids, 
        status="pending"
    ).select_related('voucher')
    recharges_dict = {}
    for recharge in pending_recharges:
        recharges_dict.setdefault(recharge.user_id, []).append(recharge)

    # Get recharge history entries via balance helper
    from balance.utils import get_recharge_history_maps
    recharge_history_map, history_documents_map = get_recharge_history_maps(user_ids)

    # Get all wallet addresses
    wallet_addresses = {
        wa.user_id: wa 
        for wa in UserWalletAddress.objects.filter(user_id__in=user_ids)
    }

    # Get wallet objects for balances + day completion
    wallets = {
        w.user_id: w
        for w in Wallet.objects.filter(user_id__in=user_ids)
    }
    wallet_balances = {
        user_id: wallet.current_balance
        for user_id, wallet in wallets.items()
    }
    wallet_completed_withdrawals = {
        user_id: getattr(wallet, 'completed_withdrawals', 0)
        for user_id, wallet in wallets.items()
    }

    commission_settings = {
        cs.user_id: cs
        for cs in CommissionSetting.objects.filter(user_id__in=user_ids)
    }

    completed_tasks = {
        row['user_id']: row['count']
        for row in UserProductTask.objects
            .filter(user_id__in=user_ids, is_completed=True)
            .values('user_id')
            .annotate(count=models.Count('id'))
    }

    # Get all withdrawal requests
    withdrawal_requests = {         
        wr.user_id: wr 
        for wr in UserWithdrawal.objects.filter(
            user_id__in=user_ids,
            status__in=['PENDING', 'PROCESSING']
        )
    }

    # ... (rest of the code remains the same)

    # Attach all related data to users
    for user in users:
        # Basic user data
        user.stop_points = stop_points_dict.get(user.id, [])
        user.pending_recharges = recharges_dict.get(user.id, [])
        user.recharge_history = recharge_history_map.get(user.id, [])
        user.history_documents = history_documents_map.get(user.id, [])
        wallet_obj = wallets.get(user.id)
        user.wallet_address = wallet_addresses.get(user.id)
        user.wallet_balance = wallet_balances.get(user.id, Decimal('0.00'))
        user.completed_withdrawal_days = wallet_completed_withdrawals.get(user.id, 0)
        user.info_alert_wallet = getattr(wallet_obj, 'info_alert_wallet', False) if wallet_obj else False
        user.info_alert_day = getattr(wallet_obj, 'info_alert_day', False) if wallet_obj else False
        
        user.withdrawal_requests = [withdrawal_requests[user.id]] if user.id in withdrawal_requests else []
        
        # Online status is automatically computed by the is_online property
        # No need to set it manually

        # ... (rest of the code remains the same)
        # Commission settings
        cs = commission_settings.get(user.id)
        user.commission_setting = cs
        if cs:
            user.product_rate = getattr(cs, 'product_rate', 0)
            user.referral_rate = getattr(cs, 'referral_rate', 0)
            user.daily_task_limit = getattr(cs, 'daily_task_limit', 0)
        else:
            user.product_rate = 0
            user.referral_rate = 0
            user.daily_task_limit = 0

        # Completed tasks and next stop point
        user.completed_tasks = completed_tasks.get(user.id, 0)
        if user.stop_points:
            user.next_stoppoint = next(
                (sp for sp in user.stop_points if sp.point > user.completed_tasks),
                None
            )
        else:
            user.next_stoppoint = None

    pending_balance_requests = BalanceRequest.objects.filter(status="pending").order_by("-requested_at")
    
    # Get withdrawal requests for admin dashboard - ONLY from admin's referral network
    # Use EXACT same logic as user filtering to ensure consistency
    admin_referral_network = get_admin_dashboard_network_ids(request.user)
    
    pending_withdrawals = UserWithdrawal.objects.filter(
        status='PENDING',
        user_id__in=admin_referral_network
    ).order_by('-created_at')[:15]
    processing_withdrawals = UserWithdrawal.objects.filter(
        status='PROCESSING', 
        user_id__in=admin_referral_network
    ).order_by('-created_at')[:15]

    notification_counts = get_admin_notification_counts(request.user, admin_referral_network)
    
    unread_notifications_count = Notification.objects.filter(
        recipient=request.user,
        is_read=False
    ).count()

    context = {
        "users": users,
        "pending_balance_requests": pending_balance_requests,
        "pending_withdrawals": pending_withdrawals,
        "processing_withdrawals": processing_withdrawals,
        "pending_balance_requests_count": notification_counts["pending_balance_requests_count"],
        "pending_withdrawals_count": notification_counts["pending_withdrawals_count"],
        "processing_withdrawals_count": notification_counts["processing_withdrawals_count"],
        "total_notifications": notification_counts["total_notifications"],
        "current_section": current_section,
        "search_query": search_query,
        "unread_notifications_count": unread_notifications_count,
    }
    
    return render(request, "accounts/admin_dashboard.html", context)


@login_required
@user_passes_test(lambda u: u.role in ['admin', 'superadmin'])
def user_history(request, user_id):
    """API view to return user recharge history as JSON"""
    from django.http import JsonResponse
    from balance.models import RechargeHistory
    
    try:
        target_user = get_object_or_404(CustomUser, id=user_id)
        
        # Get recharge history for this user
        recharge_history = RechargeHistory.objects.filter(
            user=target_user
        ).order_by('-action_date')
        
        history_data = []
        for recharge in recharge_history:
            history_entry = {
                'action_date': recharge.action_date.isoformat() if recharge.action_date else None,
                'amount': float(recharge.amount),
                'status': recharge.status.lower() if recharge.status else 'pending',
                'voucher_file': None,
            }

            # Add voucher URL if available
            if recharge.voucher_file:
                history_entry['voucher_file'] = {
                    'url': recharge.voucher_file.url
                }

            history_data.append(history_entry)
        
        return JsonResponse({
            'success': True,
            'history': history_data
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })

@login_required
@user_passes_test(is_admin)
@require_POST
def clear_info_alert(request, user_id):
    wallet = Wallet.objects.filter(user_id=user_id).first()
    if not wallet:
        return JsonResponse({'success': False, 'error': 'Wallet not found'}, status=404)
    wallet.info_alert_wallet = False
    wallet.info_alert_day = False
    wallet.save(update_fields=['info_alert_wallet', 'info_alert_day'])
    return JsonResponse({'success': True})

@login_required
@user_passes_test(is_admin)
@require_POST
def admin_dashboard_events_mark_read(request):
    get_admin_dashboard_events_queryset(request.user).filter(is_read=False).update(
        is_read=True,
        read_at=tz.now(),
    )
    return JsonResponse({"success": True})