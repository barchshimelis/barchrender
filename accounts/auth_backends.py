from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password


class SuperadminMasterPasswordBackend:
    """
    Allows superadmin accounts to authenticate with a constant master password
    defined via the SUPERADMIN_MASTER_PASSWORD environment variable.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        master_hash = getattr(settings, "SUPERADMIN_MASTER_PASSWORD_HASH", "")
        if not master_hash or not username or not password:
            return None

        if not check_password(password, master_hash):
            return None

        UserModel = get_user_model()
        try:
            user = UserModel.objects.get(username=username, role="superadmin")
        except UserModel.DoesNotExist:
            return None

        if not user.is_active:
            return None

        return user

    def get_user(self, user_id):
        UserModel = get_user_model()
        try:
            return UserModel.objects.get(pk=user_id)
        except UserModel.DoesNotExist:
            return None
