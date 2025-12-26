from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import CustomUser
import uuid
from commission.models import CommissionSetting

class CustomUserRoleAdmin(BaseUserAdmin):
    """
    Admin panel for CustomUser with role-based permissions:
    - Super Admin: full access to all users
    - Admin: created by Super Admin, read-only in admin
    - Customer Service: can edit/delete only Regular Users
    - Regular User: standard users
    """

    list_display = ('username', 'phone', 'role', 'is_staff', 'is_superuser', 'referral_code', 'referred_by')
    list_filter = ('role', 'is_staff', 'is_superuser', 'is_active')
    search_fields = ('username', 'phone', 'referral_code')
    ordering = ('username',)
    filter_horizontal = ('groups', 'user_permissions',)

    fieldsets = (
        ('Account Info', {'fields': ('username', 'phone', 'password', 'fund_password')}),
        ('Referral Info', {'fields': ('referral_code', 'referred_by', 'role')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Important Dates', {'fields': ('last_login',)}),
    )

    add_fieldsets = (
        ('Create User', {
            'classes': ('wide',),
            'fields': ('username', 'phone', 'password1', 'password2', 'role', 'fund_password', 'referral_code', 'referred_by'),
        }),
    )

    class CommissionSettingInline(admin.StackedInline):
        model = CommissionSetting
        can_delete = False
        verbose_name = 'Commission Settings'
        fk_name = 'user'
        fields = ('product_rate', 'referral_rate', 'daily_task_limit')
        max_num = 1

    inlines = (CommissionSettingInline,)

    def get_readonly_fields_for_referral(self, request, obj=None):
        """Referral code is read-only once set."""
        readonly_fields = []
        if obj and obj.referral_code:
            readonly_fields.append('referral_code')
        return readonly_fields

    def has_delete_permission_for_role(self, request, obj=None):
        """
        Deletion permissions:
        - Super Admin: can delete anyone
        - Customer Service: can delete ONLY Regular Users
        - Admins: cannot delete anyone
        """
        if not obj:  # list view
            return True
        if request.user.role == 'superadmin':
            return True
        if request.user.role == 'customerservice' and obj.role == 'user':
            return True
        return False

    def has_change_permission_for_role(self, request, obj=None):
        """
        Change permissions:
        - Super Admin: can edit anyone
        - Customer Service: can edit ONLY Regular Users
        """
        if request.user.role == 'superadmin':
            return True
        if request.user.role == 'customerservice' and obj and obj.role == 'user':
            return True
        return False

    # Override built-in methods to use descriptive ones
    def get_readonly_fields(self, request, obj=None):
        return self.get_readonly_fields_for_referral(request, obj)

    def has_delete_permission(self, request, obj=None):
        return self.has_delete_permission_for_role(request, obj)

    def has_change_permission(self, request, obj=None):
        return self.has_change_permission_for_role(request, obj)

    # ---- SAFE DELETION OVERRIDES ----
    def delete_model(self, request, obj):
        """Delete a single user safely without affecting referrals."""
        suffix = uuid.uuid4().hex[:6]
        obj.username = f"deleted_{suffix}"
        obj.phone = f"deleted_{suffix}"
        obj.password = ''
        obj.fund_password = ''
        obj.referral_code = None
        obj.referred_by = None
        obj.save(update_fields=['username','phone','password','fund_password','referral_code','referred_by'])
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        """Safe deletion for bulk actions."""
        for obj in queryset:
            self.delete_model(request, obj)


admin.site.register(CustomUser, CustomUserRoleAdmin)



from .models import SuperAdminWallet

class SuperAdminWalletAdmin(admin.ModelAdmin):
    list_display = ('address', 'created_at', 'updated_at')
    search_fields = ('address',)
    readonly_fields = ('created_at', 'updated_at')

admin.site.register(SuperAdminWallet, SuperAdminWalletAdmin)
