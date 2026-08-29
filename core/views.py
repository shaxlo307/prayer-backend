import secrets
import string

from django.contrib.auth.models import User
from django.http import JsonResponse
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from .models import PrayerLog, Profile
from .serializers import PrayerLogSerializer, ProfileSerializer


class IsOwner(permissions.BasePermission):
    """Restricts access to objects owned by the requesting user's profile."""

    def has_object_permission(self, request, view, obj):
        # Profile objects have `.user`; PrayerLog objects have `.profile.user`.
        owner_user = obj.user if isinstance(obj, Profile) else obj.profile.user
        return owner_user == request.user


class ProfileViewSet(viewsets.ModelViewSet):
    """
    Create and manage profiles. A user only ever sees/edits their own
    profile(s) — themself plus any children they manage in family mode.
    """

    serializer_class = ProfileSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwner]

    def get_queryset(self):
        # All profiles belonging to this account: their own `self` profile
        # plus any `child` profiles — both share the same `user` FK now.
        return Profile.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class PrayerLogViewSet(viewsets.ModelViewSet):
    """Read and write prayer log entries (mark a prayer done/undone)."""

    serializer_class = PrayerLogSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwner]

    def get_queryset(self):
        return PrayerLog.objects.filter(profile__user=self.request.user).order_by(
            "-date", "prayer"
        )

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["request"] = self.request
        return context


@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def register_device(request):
    """
    TEMPORARY device-account bootstrap.

    The roadmap doesn't build real sign-up/login until Day 19 (family
    mode's parent account creation), but every authenticated endpoint needs
    *some* identity before then. This silently provisions a throwaway User
    + a `self` Profile and returns Basic Auth credentials for the app to
    store locally (see lib/session.ts on the Expo side).

    This is scaffolding, not the final auth design — Day 19 should replace
    or migrate accounts created this way once real sign-up/login exists.
    """
    alphabet = string.ascii_letters + string.digits
    username = "device-" + "".join(secrets.choice(alphabet) for _ in range(16))
    password = "".join(secrets.choice(alphabet) for _ in range(24))

    user = User.objects.create_user(username=username, password=password)
    profile = Profile.objects.create(user=user, type="self", display_name="Me")

    return Response(
        {
            "username": username,
            "password": password,
            "profile": ProfileSerializer(profile).data,
        },
        status=status.HTTP_201_CREATED,
    )


def health_check(request):
    """Simple liveness endpoint: confirms the API + DB connection are up."""
    from django.db import connection

    db_ok = True
    try:
        connection.ensure_connection()
    except Exception:
        db_ok = False

    return JsonResponse(
        {
            "status": "ok",
            "service": "prayer-app-backend",
            "database": "connected" if db_ok else "unreachable",
        }
    )
