from django.conf import settings
from django.core.files.storage import FileSystemStorage


private_media_storage = FileSystemStorage(
    location=settings.PRIVATE_MEDIA_ROOT,
    base_url=None,
)