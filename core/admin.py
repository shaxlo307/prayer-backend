from django.contrib import admin

# Register your models here.

from .models import NotificationSettings, PrayerLog, Profile, QadaDebt, QadaLog, Streak


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("display_name", "user", "parent", "madhhab", "created_at")
    list_filter = ("madhhab", "gender")
    search_fields = ("display_name", "user__username")


@admin.register(PrayerLog)
class PrayerLogAdmin(admin.ModelAdmin):
    list_display = ("profile", "date", "prayer", "completed")
    list_filter = ("prayer", "completed", "date")


@admin.register(QadaDebt)
class QadaDebtAdmin(admin.ModelAdmin):
    list_display = ("profile", "prayer", "owed_count", "updated_at")
    list_filter = ("prayer",)


@admin.register(QadaLog)
class QadaLogAdmin(admin.ModelAdmin):
    list_display = ("profile", "prayer", "logged_at")
    list_filter = ("prayer",)


@admin.register(Streak)
class StreakAdmin(admin.ModelAdmin):
    list_display = ("profile", "current_streak", "longest_streak", "last_completed_date")


@admin.register(NotificationSettings)
class NotificationSettingsAdmin(admin.ModelAdmin):
    list_display = ("profile", "reminder_minutes_before", "family_digest_enabled")
