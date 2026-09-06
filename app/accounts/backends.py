from django.contrib.auth.backends import ModelBackend

from .models import User


class StatusAwareModelBackend(ModelBackend):
    def user_can_authenticate(self, user):
        return (
            super().user_can_authenticate(user)
            and user.status == User.Status.ACTIVE
        )
