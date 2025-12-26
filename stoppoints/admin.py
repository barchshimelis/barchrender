# stoppoints/admin.py
from django.contrib import admin, messages
from .models import StopPoint, StopPointProgress

@admin.action(description="Approve selected stop points")
def approve_stop_points(modeladmin, request, queryset):
    for sp in queryset:
        sp.status = 'approved'
        sp.save()
        progress, _ = StopPointProgress.objects.get_or_create(user=sp.user)
        progress.is_stopped = False
        progress.last_cleared = sp
        progress.save()
    messages.success(request, "Selected stop points approved. Users can continue tasks.")

@admin.action(description="Reject selected stop points")
def reject_stop_points(modeladmin, request, queryset):
    for sp in queryset:
        sp.status = 'rejected'
        sp.save()
        progress, _ = StopPointProgress.objects.get_or_create(user=sp.user)
        progress.is_stopped = True
        progress.save()
    messages.warning(request, "Selected stop points rejected. Users remain stopped.")

@admin.register(StopPoint)
class StopPointAdmin(admin.ModelAdmin):
    list_display = ('user', 'point', 'required_balance', 'status', 'order')
    list_filter = ('status', 'user')
    search_fields = ('user__username', 'point')
    list_editable = ('point', 'required_balance', 'order')
    ordering = ('user', 'order')
    actions = [approve_stop_points, reject_stop_points]

@admin.register(StopPointProgress)
class StopPointProgressAdmin(admin.ModelAdmin):
    list_display = ('user', 'last_cleared', 'is_stopped')
    search_fields = ('user__username',)
    raw_id_fields = ('user', 'last_cleared')
