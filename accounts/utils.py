from django.contrib.auth import get_user_model

User = get_user_model()

def is_admin(user):
    return user.is_authenticated and user.role == 'admin'
