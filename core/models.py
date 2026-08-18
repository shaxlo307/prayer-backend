from django.conf import settings
from django.db import models


class Prayer(models.TextChoices):
    FAJR = "fajr", "Fajr"
    DHUHR = "dhuhr", "Dhuhr"
    ASR = "asr", "Asr"
    MAGHRIB = "maghrib", "Maghrib"
    ISHA = "isha", "Isha"


class Madhhab(models.TextChoices):
    HANAFI = "hanafi", "Hanafi"
    SHAFI = "shafi", "Shafi'i / Maliki / Hanbali"


class Gender(models.TextChoices):
    MALE = "male", "Male"
    FEMALE = "female", "Female"


class Profile(models.Model):
    """
    App-specific data layered on top of Django's built-in auth user.
    Supports both solo accounts and family mode via the self-referential
    `parent` field: a child profile's `parent` points at the managing
    parent's profile. Solo/parent profiles have `parent = None`.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="children",
        help_text="Set for child profiles managed under a parent's family mode account.",
    )

    display_name = models.CharField(max_length=100)

    # Qada setup fields (filled in during Day 13's qada setup flow)
    birth_date = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=10, choices=Gender.choices, null=True, blank=True)
    bulugh_age = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Age of religious maturity used as the qada calculation start point.",
    )
    practice_start_date = models.DateField(
        null=True,
        blank=True,
        help_text="Date the user began actively praying / being accountable for qada.",
    )

    # Prayer-time calculation preferences (used by the Aladhan API integration)
    madhhab = models.CharField(max_length=10, choices=Madhhab.choices, default=Madhhab.SHAFI)
    calculation_method = models.PositiveSmallIntegerField(
        default=2, help_text="Aladhan API calculation method ID."
    )
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    city = models.CharField(max_length=120, blank=True)
    timezone = models.CharField(max_length=64, default="UTC")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "profiles"

    def __str__(self):
        return self.display_name or self.user.username


class PrayerLog(models.Model):
    """
    One row per prayer per day per profile — today-forward logging (tapping
    a prayer as done). Historical backlog before the user started tracking
    lives in QadaDebt/QadaLog instead.
    """

    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="prayer_logs")
    date = models.DateField()
    prayer = models.CharField(max_length=10, choices=Prayer.choices)
    completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "prayer_logs"
        constraints = [
            models.UniqueConstraint(
                fields=["profile", "date", "prayer"], name="unique_prayer_log_per_day"
            )
        ]
        indexes = [models.Index(fields=["profile", "date"])]

    def __str__(self):
        return f"{self.profile} — {self.prayer} on {self.date}"


class QadaDebt(models.Model):
    """
    Running total of missed prayers owed per prayer type. One row per
    profile per prayer; `owed_count` is decremented as QadaLog entries
    are recorded and recalculated from birth_date/bulugh_age/practice_start_date.
    """

    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="qada_debts")
    prayer = models.CharField(max_length=10, choices=Prayer.choices)
    owed_count = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "qada_debt"
        constraints = [
            models.UniqueConstraint(fields=["profile", "prayer"], name="unique_qada_debt_per_prayer")
        ]

    def __str__(self):
        return f"{self.profile} owes {self.owed_count} {self.prayer}"


class QadaLog(models.Model):
    """Individual qada (make-up prayer) completions, paid down against QadaDebt."""

    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="qada_logs")
    prayer = models.CharField(max_length=10, choices=Prayer.choices)
    logged_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "qada_logs"
        indexes = [models.Index(fields=["profile", "prayer"])]

    def __str__(self):
        return f"{self.profile} paid down 1 {self.prayer} qada"


class Streak(models.Model):
    """Current/longest streak of days with all 5 prayers completed on time."""

    profile = models.OneToOneField(Profile, on_delete=models.CASCADE, related_name="streak")
    current_streak = models.PositiveIntegerField(default=0)
    longest_streak = models.PositiveIntegerField(default=0)
    last_completed_date = models.DateField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "streaks"

    def __str__(self):
        return f"{self.profile}: {self.current_streak} day streak"


class NotificationSettings(models.Model):
    """Per-profile notification preferences."""

    profile = models.OneToOneField(
        Profile, on_delete=models.CASCADE, related_name="notification_settings"
    )
    fajr_enabled = models.BooleanField(default=True)
    dhuhr_enabled = models.BooleanField(default=True)
    asr_enabled = models.BooleanField(default=True)
    maghrib_enabled = models.BooleanField(default=True)
    isha_enabled = models.BooleanField(default=True)
    reminder_minutes_before = models.PositiveSmallIntegerField(default=10)
    qada_reminders_enabled = models.BooleanField(default=True)
    family_digest_enabled = models.BooleanField(
        default=False, help_text="For parent profiles: daily summary of children's progress."
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "notification_settings"

    def __str__(self):
        return f"Notification settings for {self.profile}"
