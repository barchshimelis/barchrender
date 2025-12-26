from django.contrib import admin
from .models import Product, FeaturedImage


@admin.register(FeaturedImage)
class FeaturedImageAdmin(admin.ModelAdmin):
    list_display = ("title", "display_order", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("title", "description", "link_url")
    ordering = ("display_order", "-created_at")
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (None, {
            "fields": (
                "title",
                "description",
                "image",
                "link_url",
                "display_order",
                "is_active",
            )
        }),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )

