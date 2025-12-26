from django.contrib import admin
from .models import CommissionSetting, Commission

@admin.register(CommissionSetting)
class CommissionSettingAdmin(admin.ModelAdmin):
    list_display = ("user", "product_rate", "updated_at")
    list_editable = ("product_rate",)  # allows dynamic rate change in admin
    search_fields = ("user__username",)
    list_filter = ("updated_at",)


@admin.register(Commission)
class CommissionAdmin(admin.ModelAdmin):
    list_display = ("user", "product_name", "amount", "created_at")
    search_fields = ("user__username", "product_name")
    list_filter = ("created_at",)
