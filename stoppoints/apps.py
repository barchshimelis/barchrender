from django.apps import AppConfig


class StoppointsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'stoppoints'

    def ready(self):
        import stoppoints.signals
