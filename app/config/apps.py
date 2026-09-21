from django.apps import AppConfig


class ConfigConfig(AppConfig):
    name = "config"
    verbose_name = "Работоспособность приложения"

    def ready(self):
        from . import checks  # noqa: F401
