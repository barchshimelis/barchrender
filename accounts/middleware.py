from django.utils import timezone
from django.shortcuts import redirect
from django.contrib import messages
from django.urls import reverse


class AdminActivityMiddleware:
    """Track activity timestamps and enforce freeze rules for staff roles."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            try:
                user_role = getattr(request.user, 'role', None)

                # Only admins and customer service reps are forcefully logged out when frozen
                if user_role in ['admin', 'customerservice'] and getattr(request.user, 'is_frozen', False):
                    from django.contrib.auth import logout

                    logout(request)
                    messages.error(request, 'account violated organization rules... ')
                    if user_role == 'admin':
                        return redirect('accounts:adminlogin')
                    return redirect('accounts:customerservicelogin')

                # Update last_activity for any authenticated user model that supports it
                if hasattr(request.user, 'last_activity'):
                    request.user.last_activity = timezone.now()
                    request.user.save(update_fields=['last_activity'])
            except AttributeError:
                pass

        response = self.get_response(request)
        return response
