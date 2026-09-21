import http.client
import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from config.proxy_transport import loopback_proxy_v2


class Command(BaseCommand):
    help = "Проверяет HTTP-ответ приложения и доступность базы для Docker."
    requires_system_checks = []

    def handle(self, *args, **options):
        host = next(
            (host.lstrip(".") for host in settings.ALLOWED_HOSTS if host != "*"),
            "127.0.0.1",
        )
        # Connect only to this container. Host follows the configured site name.
        headers = {"Host": host}
        if settings.SECURE_PROXY_SSL_HEADER == ("HTTP_X_FORWARDED_PROTO", "https"):
            headers["X-Forwarded-Proto"] = "https"
        client = http.client.HTTPConnection("127.0.0.1", 8000, timeout=3)
        try:
            if settings.PROXY_PROTOCOL_ENABLED:
                client.connect()
                client.send(loopback_proxy_v2())
            client.request("GET", "/health/", headers=headers)
            response = client.getresponse()
            if response.status != 200 or json.loads(response.read(1024)) != {"status": "ok"}:
                raise CommandError("Приложение или база данных недоступны.")
        except (OSError, http.client.HTTPException, ValueError):
            raise CommandError("Приложение или база данных недоступны.") from None
        finally:
            client.close()
        self.stdout.write("ok")
