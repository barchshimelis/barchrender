from django.utils import timezone
from django.shortcuts import redirect
from django.contrib import messages
from django.urls import reverse


class AdminActivityMiddleware:
    """Track activity timestamps and enforce freeze rules for staff roles."""

    def __init__(self, get_response):
        self.get_response = get_response

    def clear_user_sessions(self, user):
        """Clear all sessions for user across all devices"""
        from django.contrib.sessions.models import Session
        sessions = Session.objects.filter(
            session_data__contains=str(user.id)
        )
        sessions.delete()

    def __call__(self, request):
        if request.user.is_authenticated:
            try:
                user_role = getattr(request.user, 'role', None)

                # Force logout all frozen users (admin, customerservice, regular users)
                if getattr(request.user, 'is_frozen', False):
                    from django.contrib.auth import logout

                    # Clear all sessions for this user
                    self.clear_user_sessions(request.user)
                    
                    # Force logout
                    logout(request)
                    
                    # Role-specific redirect and message
                    if user_role == 'admin':
                        messages.error(request, "Your account has been frozen. Please contact customer service.")
                        return redirect('accounts:adminlogin')
                    elif user_role == 'customerservice':
                        messages.error(request, "Your account has been frozen. Please contact customer service.")
                        return redirect('accounts:customerservicelogin')
                    else:  # regular user
                        messages.error(request, "Your account is frozen. Please contact customer service.")
                        return redirect('accounts:user_login')

                # Update last_activity for any authenticated user model that supports it
                if hasattr(request.user, 'last_activity'):
                    request.user.last_activity = timezone.now()
                    request.user.save(update_fields=['last_activity'])
            except AttributeError:
                pass

        response = self.get_response(request)
        return response
