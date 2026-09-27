from django.conf import settings
from .storage_quota import QuotaFileSystemStorage


private_media_storage = QuotaFileSystemStorage(
    location=settings.PRIVATE_MEDIA_ROOT,
    base_url=None,
)
