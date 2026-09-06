from django.apps import AppConfig


class PrivacyConfig(AppConfig):
    name = "privacy"

    def ready(self):
        from . import signals  # noqa: F401
