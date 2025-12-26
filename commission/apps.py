from django.apps import AppConfig

class CommissionConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "commission"

    def ready(self):
        import commission.signals
