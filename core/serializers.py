from rest_framework import serializers

from .models import PrayerLog, Profile, QadaDebt


class ProfileSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        model = Profile
        fields = [
            "id",
            "username",
            "type",
            "display_name",
            "age",
            "qada_enabled",
            "birth_date",
            "gender",
            "bulugh_age",
            "practice_start_date",
            "madhhab",
            "calculation_method",
            "latitude",
            "longitude",
            "city",
            "timezone",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class PrayerLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = PrayerLog
        fields = [
            "id",
            "profile",
            "date",
            "prayer",
            "status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_profile(self, profile):
        """Prevent logging prayers to a profile outside your own account."""
        request = self.context.get("request")
        if request and profile.user != request.user:
            raise serializers.ValidationError(
                "You can only log prayers to a profile in your own account."
            )
        return profile


class QadaDebtSerializer(serializers.ModelSerializer):
    """
    Read-only: rows are written only via the calculation logic
    (core/qada.py) and, from Day 16 on, qada-log decrements -- never
    directly through this serializer, so a client can't set an arbitrary
    remaining_count by PATCHing it.
    """

    class Meta:
        model = QadaDebt
        fields = ["id", "profile", "prayer", "initial_count", "remaining_count", "updated_at"]
        read_only_fields = fields
