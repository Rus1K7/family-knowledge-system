from django.apps import AppConfig


class HeritageConfig(AppConfig):
    name = "heritage"

    def ready(self):
        from . import signals  # noqa: F401
