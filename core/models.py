from django.conf import settings
from django.db import models
from django.db.models import Q


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


class ProfileType(models.TextChoices):
    SELF = "self", "Self"
    CHILD = "child", "Child"

class Profile(models.Model):
    """
    One row per person tracked in the app. A single account (`user`) can own
    multiple profiles: exactly one `self` profile plus any number of `child`
    profiles — this is how family mode works. A solo user simply has one
    `self` profile and no children.

    Matches the spec's `profiles` table: id, user_id (FK), display_name,
    type (self|child), age, madhhab, qada_enabled, created_at — extended
    with the extra fields the qada calculator and prayer-time API need.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profiles"
    )
    type = models.CharField(max_length=5, choices=ProfileType.choices, default=ProfileType.SELF)

    display_name = models.CharField(max_length=100)

    # Simple, optional — per spec, only used to shape reminder tone for
    # child profiles during onboarding's "add child" step. Distinct from
    # birth_date below, which feeds the qada debt calculation.
    age = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="Optional. Shapes reminder tone only, nothing else."
    )

    qada_enabled = models.BooleanField(
        default=True,
        help_text="Off for children just building the habit; on by default for adult/self profiles.",
    )

    # Qada setup fields (Day 9 / spec section 3) — birth_date/bulugh_age/
    # practice_start_date define the missed-prayer window for debt calc.
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
    madhhab = models.CharField(max_length=10, choices=Madhhab.choices, default=Madhhab.HANAFI)
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
        constraints = [
            # Exactly one "self" profile per account; any number of "child" profiles.
            models.UniqueConstraint(
                fields=["user", "type"],
                condition=Q(type="self"),
                name="one_self_profile_per_user",
            )
        ]

    def __str__(self):
        return self.display_name or f"{self.user}'s profile"


class PrayerStatus(models.TextChoices):
    UNMARKED = "unmarked", "Unmarked"
    DONE = "done", "Done"
    LATE = "late", "Late"


class PrayerLog(models.Model):
    """
    One row per prayer per day per profile. `status` is a 3-state enum per
    the spec (unmarked/done/late) rather than a plain boolean, so the v2
    "late" distinction (deferred, but modeled now) doesn't need a migration
    later.
    """

    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="prayer_logs")
    date = models.DateField()
    prayer = models.CharField(max_length=10, choices=Prayer.choices)
    status = models.CharField(
        max_length=10, choices=PrayerStatus.choices, default=PrayerStatus.UNMARKED
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)  # doubles as the spec's `logged_at`

    class Meta:
        db_table = "prayer_logs"
        constraints = [
            models.UniqueConstraint(
                fields=["profile", "date", "prayer"], name="unique_prayer_log_per_day"
            )
        ]
        indexes = [models.Index(fields=["profile", "date"])]

    def __str__(self):
        return f"{self.profile} — {self.prayer} on {self.date}: {self.status}"


class QadaDebt(models.Model):
    """
    Running total of missed prayers owed per prayer type. One row per
    profile per prayer; `remaining_count` is decremented as QadaLog entries
    are recorded (Day 16). `initial_count` is set once at calculation time
    and left untouched afterward -- it's the fixed baseline the Day 15
    progress bars divide against (remaining_count alone can't show "how
    far along" once it starts decreasing).
    """

    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="qada_debts")
    prayer = models.CharField(max_length=10, choices=Prayer.choices)
    initial_count = models.PositiveIntegerField(
        default=0,
        help_text="Debt computed at calculation time. Fixed baseline for progress-bar percentage; not decremented by logging.",
    )
    remaining_count = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "qada_debt"
        constraints = [
            models.UniqueConstraint(fields=["profile", "prayer"], name="unique_qada_debt_per_prayer")
        ]

    def __str__(self):
        return f"{self.profile} has {self.remaining_count} {self.prayer} remaining"


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
    """Current/longest streak of days with all 5 prayers completed (done or late)."""

    profile = models.OneToOneField(Profile, on_delete=models.CASCADE, related_name="streak")
    current_streak = models.PositiveIntegerField(default=0)
    longest_streak = models.PositiveIntegerField(default=0)
    last_calculated_date = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "streaks"

    def __str__(self):
        return f"{self.profile}: {self.current_streak} day streak"


class NotificationTone(models.TextChoices):
    STANDARD = "standard", "Standard"
    GENTLE = "gentle", "Gentle"


class NotificationSettings(models.Model):
    """
    Per-profile notification preferences. Simplified to match the spec: one
    overall on/off toggle (not per-prayer), a copy tone for adult vs.
    child-friendly wording, and a parent-mute flag for family mode.
    """

    profile = models.OneToOneField(
        Profile, on_delete=models.CASCADE, related_name="notification_settings"
    )
    enabled = models.BooleanField(default=True)
    tone = models.CharField(
        max_length=10, choices=NotificationTone.choices, default=NotificationTone.STANDARD
    )
    muted_by_parent = models.BooleanField(
        default=False, help_text="Parent can mute a child's notifications from the family dashboard."
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "notification_settings"

    def __str__(self):
        return f"Notification settings for {self.profile}"
