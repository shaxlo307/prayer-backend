from django.contrib import admin

from .models import NotificationSettings, PrayerLog, Profile, QadaDebt, QadaLog, Streak


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("display_name", "user", "type", "madhhab", "qada_enabled", "created_at")
    list_filter = ("type", "madhhab", "gender", "qada_enabled")
    search_fields = ("display_name", "user__username")


@admin.register(PrayerLog)
class PrayerLogAdmin(admin.ModelAdmin):
    list_display = ("profile", "date", "prayer", "status")
    list_filter = ("prayer", "status", "date")


@admin.register(QadaDebt)
class QadaDebtAdmin(admin.ModelAdmin):
    list_display = ("profile", "prayer", "remaining_count", "updated_at")
    list_filter = ("prayer",)


@admin.register(QadaLog)
class QadaLogAdmin(admin.ModelAdmin):
    list_display = ("profile", "prayer", "logged_at")
    list_filter = ("prayer",)


@admin.register(Streak)
class StreakAdmin(admin.ModelAdmin):
    list_display = ("profile", "current_streak", "longest_streak", "last_calculated_date")


@admin.register(NotificationSettings)
class NotificationSettingsAdmin(admin.ModelAdmin):
    list_display = ("profile", "enabled", "tone", "muted_by_parent")
    list_filter = ("tone", "muted_by_parent")
