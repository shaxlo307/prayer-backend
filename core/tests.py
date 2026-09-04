from datetime import date, timedelta

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.test import APITestCase

from .models import PrayerLog, Profile, QadaDebt
from .qada import (
    QadaSetupIncomplete,
    calculate_qada_debt,
    compute_bulugh_date,
    recalculate_and_store_qada_debt,
)


class ProfileEndpointTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", "alice@example.com", "pass12345")
        self.other_user = User.objects.create_user("bob", "bob@example.com", "pass12345")

    def test_unauthenticated_request_rejected(self):
        response = self.client.get("/api/profiles/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_profile_assigns_requesting_user(self):
        self.client.login(username="alice", password="pass12345")
        response = self.client.post(
            "/api/profiles/",
            {"display_name": "Alice", "madhhab": "hanafi", "city": "Tashkent", "timezone": "Asia/Tashkent"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        profile = Profile.objects.get(id=response.data["id"])
        self.assertEqual(profile.user, self.user)
        self.assertEqual(profile.type, "self")  # default

    def test_user_only_sees_own_account_profiles(self):
        Profile.objects.create(user=self.user, display_name="Alice", type="self")
        Profile.objects.create(user=self.other_user, display_name="Bob", type="self")

        self.client.login(username="alice", password="pass12345")
        response = self.client.get("/api/profiles/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["display_name"], "Alice")

    def test_family_mode_child_profiles_share_parent_account(self):
        """
        Per the reconciled spec: a child profile belongs to the SAME user
        account as the parent's self profile, not a separate user.
        """
        Profile.objects.create(user=self.user, display_name="Alice", type="self")
        Profile.objects.create(
            user=self.user, display_name="Kid", type="child", age=8, qada_enabled=False
        )

        self.client.login(username="alice", password="pass12345")
        response = self.client.get("/api/profiles/")
        names = {p["display_name"] for p in response.data}
        self.assertEqual(names, {"Alice", "Kid"})

        kid = next(p for p in response.data if p["display_name"] == "Kid")
        self.assertEqual(kid["type"], "child")
        self.assertFalse(kid["qada_enabled"])

    def test_only_one_self_profile_per_account(self):
        Profile.objects.create(user=self.user, display_name="Alice", type="self")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Profile.objects.create(user=self.user, display_name="Alice again", type="self")

    def test_multiple_child_profiles_allowed(self):
        Profile.objects.create(user=self.user, display_name="Alice", type="self")
        Profile.objects.create(user=self.user, display_name="Kid 1", type="child")
        Profile.objects.create(user=self.user, display_name="Kid 2", type="child")
        self.assertEqual(Profile.objects.filter(user=self.user, type="child").count(), 2)


class PrayerLogEndpointTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", "alice@example.com", "pass12345")
        self.other_user = User.objects.create_user("bob", "bob@example.com", "pass12345")
        self.profile = Profile.objects.create(user=self.user, display_name="Alice", type="self")
        self.other_profile = Profile.objects.create(
            user=self.other_user, display_name="Bob", type="self"
        )
        self.client.login(username="alice", password="pass12345")

    def test_create_prayer_log_defaults_to_unmarked(self):
        response = self.client.post(
            "/api/prayer-logs/",
            {"profile": self.profile.id, "date": "2026-08-18", "prayer": "fajr"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["status"], "unmarked")

    def test_mark_prayer_done(self):
        response = self.client.post(
            "/api/prayer-logs/",
            {"profile": self.profile.id, "date": "2026-08-18", "prayer": "fajr", "status": "done"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["status"], "done")

    def test_mark_prayer_late(self):
        response = self.client.post(
            "/api/prayer-logs/",
            {"profile": self.profile.id, "date": "2026-08-18", "prayer": "isha", "status": "late"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["status"], "late")

    def test_invalid_status_rejected(self):
        response = self.client.post(
            "/api/prayer-logs/",
            {"profile": self.profile.id, "date": "2026-08-18", "prayer": "fajr", "status": "bogus"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_duplicate_prayer_same_day_rejected(self):
        PrayerLog.objects.create(profile=self.profile, date="2026-08-18", prayer="fajr", status="done")
        response = self.client.post(
            "/api/prayer-logs/",
            {"profile": self.profile.id, "date": "2026-08-18", "prayer": "fajr", "status": "done"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(PrayerLog.objects.count(), 1)

    def test_cannot_log_prayer_to_another_accounts_profile(self):
        response = self.client.post(
            "/api/prayer-logs/",
            {"profile": self.other_profile.id, "date": "2026-08-18", "prayer": "dhuhr", "status": "done"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(PrayerLog.objects.count(), 0)

    def test_user_only_sees_own_prayer_logs(self):
        PrayerLog.objects.create(profile=self.profile, date="2026-08-18", prayer="fajr", status="done")
        PrayerLog.objects.create(
            profile=self.other_profile, date="2026-08-18", prayer="fajr", status="done"
        )
        response = self.client.get("/api/prayer-logs/")
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["profile"], self.profile.id)

    def test_can_log_prayer_for_own_child_profile(self):
        """A parent can log prayers on behalf of a child sharing their account."""
        child = Profile.objects.create(
            user=self.user, display_name="Kid", type="child", qada_enabled=False
        )
        response = self.client.post(
            "/api/prayer-logs/",
            {"profile": child.id, "date": "2026-08-18", "prayer": "asr", "status": "done"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)


class RegisterDeviceEndpointTests(APITestCase):
    """
    Covers the temporary device-account bootstrap (see views.register_device)
    that stands in for real sign-up/login until Day 19.
    """

    def test_register_creates_user_and_self_profile(self):
        response = self.client.post("/api/register/")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("username", response.data)
        self.assertIn("password", response.data)
        self.assertEqual(response.data["profile"]["type"], "self")
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(Profile.objects.count(), 1)

    def test_registered_credentials_authenticate_successfully(self):
        register_response = self.client.post("/api/register/")
        username = register_response.data["username"]
        password = register_response.data["password"]

        self.client.logout()
        logged_in = self.client.login(username=username, password=password)
        self.assertTrue(logged_in)

        response = self.client.get("/api/profiles/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_each_registration_creates_a_distinct_account(self):
        first = self.client.post("/api/register/")
        second = self.client.post("/api/register/")
        self.assertNotEqual(first.data["username"], second.data["username"])
        self.assertEqual(User.objects.count(), 2)

    def test_register_does_not_require_authentication(self):
        # No login() call here at all — this must work from a totally
        # anonymous client, since it's the very first request the app makes.
        response = self.client.post("/api/register/")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)


class ModelConstraintTests(APITestCase):
    """Direct model-level tests, independent of the API layer."""

    def setUp(self):
        self.user = User.objects.create_user("alice", "alice@example.com", "pass12345")
        self.profile = Profile.objects.create(user=self.user, display_name="Alice", type="self")

    def test_profile_cascade_deletes_related_rows(self):
        PrayerLog.objects.create(profile=self.profile, date="2026-08-18", prayer="fajr", status="done")
        self.user.delete()
        self.assertEqual(Profile.objects.count(), 0)
        self.assertEqual(PrayerLog.objects.count(), 0)

    def test_deleting_account_removes_all_family_profiles(self):
        Profile.objects.create(user=self.user, display_name="Kid", type="child")
        self.assertEqual(Profile.objects.filter(user=self.user).count(), 2)
        self.user.delete()
        self.assertEqual(Profile.objects.count(), 0)


class QadaDebtCalculationLogicTests(APITestCase):
    """
    Direct tests of core/qada.py's pure calculation logic (Day 14) --
    independent of the API layer.
    """

    def setUp(self):
        self.user = User.objects.create_user("alice", "alice@example.com", "pass12345")

    def make_profile(self, **overrides):
        defaults = dict(
            user=self.user,
            display_name="Alice",
            type="self",
            birth_date=date(2000, 1, 1),
            bulugh_age=12,
            gender="male",
            practice_start_date=date(2012, 1, 1) + timedelta(days=300),
        )
        defaults.update(overrides)
        return Profile.objects.create(**defaults)

    def test_compute_bulugh_date_simple(self):
        self.assertEqual(
            compute_bulugh_date(date(2000, 5, 15), 12), date(2012, 5, 15)
        )

    def test_compute_bulugh_date_handles_leap_day_birthday(self):
        # 2000 is a leap year (Feb 29 exists); 2000 + 13 = 2013, not a leap
        # year, so Feb 29 must fall back to Feb 28 rather than raising.
        self.assertEqual(
            compute_bulugh_date(date(2000, 2, 29), 13), date(2013, 2, 28)
        )

    def test_raises_when_profile_missing_qada_setup_fields(self):
        profile = self.make_profile(birth_date=None)
        with self.assertRaises(QadaSetupIncomplete):
            calculate_qada_debt(profile)

    def test_male_profile_gets_no_menstruation_deduction(self):
        profile = self.make_profile(gender="male")
        debt = calculate_qada_debt(profile)
        self.assertEqual(
            debt,
            {"fajr": 300, "dhuhr": 300, "asr": 300, "maghrib": 300, "isha": 300},
        )

    def test_missing_gender_gets_no_menstruation_deduction(self):
        profile = self.make_profile(gender=None)
        debt = calculate_qada_debt(profile)
        self.assertEqual(debt["fajr"], 300)

    def test_female_profile_gets_menstruation_deduction_applied_uniformly(self):
        profile = self.make_profile(gender="female")
        debt = calculate_qada_debt(profile)
        # 300 days * 7/30 = 70 exactly; 300 - 70 = 230 for every prayer type.
        self.assertEqual(
            debt,
            {"fajr": 230, "dhuhr": 230, "asr": 230, "maghrib": 230, "isha": 230},
        )

    def test_practice_start_equal_to_bulugh_date_gives_zero_debt(self):
        profile = self.make_profile(practice_start_date=date(2012, 1, 1))
        debt = calculate_qada_debt(profile)
        self.assertEqual(debt["fajr"], 0)

    def test_practice_start_before_bulugh_date_clamps_to_zero_not_negative(self):
        profile = self.make_profile(practice_start_date=date(2011, 1, 1))
        debt = calculate_qada_debt(profile)
        self.assertTrue(all(count == 0 for count in debt.values()))

    def test_recalculate_and_store_creates_rows_matching_calculation(self):
        profile = self.make_profile(gender="female")
        rows = recalculate_and_store_qada_debt(profile)
        self.assertEqual(QadaDebt.objects.filter(profile=profile).count(), 5)
        by_prayer = {r.prayer: r.remaining_count for r in rows}
        self.assertEqual(by_prayer["fajr"], 230)
        
    def test_initial_count_set_equal_to_remaining_count_on_first_calculation(self):
        profile = self.make_profile(gender="female")
        rows = recalculate_and_store_qada_debt(profile)
        fajr = next(r for r in rows if r.prayer == "fajr")
        self.assertEqual(fajr.initial_count, 230)
        self.assertEqual(fajr.initial_count, fajr.remaining_count)

    def test_recalculate_without_force_preserves_already_logged_progress(self):
        profile = self.make_profile(gender="male")
        recalculate_and_store_qada_debt(profile)
        # Simulate Day 16 progress: someone already logged a few qada prayers.
        QadaDebt.objects.filter(profile=profile, prayer="fajr").update(remaining_count=250)

        rows = recalculate_and_store_qada_debt(profile)  # force defaults to False
        by_prayer = {r.prayer: r.remaining_count for r in rows}
        self.assertEqual(by_prayer["fajr"], 250)  # untouched, not reset to 300
        fajr = next(r for r in rows if r.prayer == "fajr")
        self.assertEqual(fajr.initial_count, 300)  # baseline also untouched

    def test_recalculate_with_force_overwrites_existing_rows(self):
        profile = self.make_profile(gender="male")
        recalculate_and_store_qada_debt(profile)
        QadaDebt.objects.filter(profile=profile, prayer="fajr").update(remaining_count=250)

        rows = recalculate_and_store_qada_debt(profile, force=True)
        by_prayer = {r.prayer: r.remaining_count for r in rows}
        self.assertEqual(by_prayer["fajr"], 300)  # recomputed from scratch
        fajr = next(r for r in rows if r.prayer == "fajr")
        self.assertEqual(fajr.initial_count, 300)  # baseline reset too


class QadaDebtEndpointTests(APITestCase):
    """API-level tests for Day 14's calculate-qada-debt action + qada-debt list."""

    def setUp(self):
        self.user = User.objects.create_user("alice", "alice@example.com", "pass12345")
        self.other_user = User.objects.create_user("bob", "bob@example.com", "pass12345")
        self.client.login(username="alice", password="pass12345")

    def make_profile(self, user, **overrides):
        defaults = dict(
            user=user,
            display_name="Alice",
            type="self",
            birth_date=date(2000, 1, 1),
            bulugh_age=12,
            gender="male",
            practice_start_date=date(2012, 1, 1) + timedelta(days=300),
        )
        defaults.update(overrides)
        return Profile.objects.create(**defaults)

    def test_calculate_returns_400_for_incomplete_qada_setup(self):
        profile = self.make_profile(self.user, birth_date=None)
        response = self.client.post(f"/api/profiles/{profile.id}/calculate-qada-debt/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_calculate_returns_correct_initial_debt_per_prayer(self):
        """Matches the roadmap's Day 14 'done when': given a birth date and
        start-of-practice date, the API returns a correct initial debt
        count per prayer type."""
        profile = self.make_profile(self.user, gender="male")
        response = self.client.post(f"/api/profiles/{profile.id}/calculate-qada-debt/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 5)
        counts = {row["prayer"]: row["remaining_count"] for row in response.data}
        self.assertEqual(
            counts,
            {"fajr": 300, "dhuhr": 300, "asr": 300, "maghrib": 300, "isha": 300},
        )

    def test_calculate_applies_menstruation_deduction_for_female_profile(self):
        profile = self.make_profile(self.user, gender="female")
        response = self.client.post(f"/api/profiles/{profile.id}/calculate-qada-debt/")
        counts = {row["prayer"]: row["remaining_count"] for row in response.data}
        self.assertEqual(counts["fajr"], 230)

    def test_second_call_without_force_does_not_reset_logged_progress(self):
        profile = self.make_profile(self.user, gender="male")
        self.client.post(f"/api/profiles/{profile.id}/calculate-qada-debt/")
        QadaDebt.objects.filter(profile=profile, prayer="fajr").update(remaining_count=250)

        response = self.client.post(f"/api/profiles/{profile.id}/calculate-qada-debt/")
        counts = {row["prayer"]: row["remaining_count"] for row in response.data}
        self.assertEqual(counts["fajr"], 250)

    def test_force_true_recomputes_from_scratch(self):
        profile = self.make_profile(self.user, gender="male")
        self.client.post(f"/api/profiles/{profile.id}/calculate-qada-debt/")
        QadaDebt.objects.filter(profile=profile, prayer="fajr").update(remaining_count=250)

        response = self.client.post(
            f"/api/profiles/{profile.id}/calculate-qada-debt/", {"force": True}
        )
        counts = {row["prayer"]: row["remaining_count"] for row in response.data}
        self.assertEqual(counts["fajr"], 300)

    def test_cannot_calculate_debt_for_another_accounts_profile(self):
        other_profile = self.make_profile(self.other_user)
        response = self.client.post(
            f"/api/profiles/{other_profile.id}/calculate-qada-debt/"
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(QadaDebt.objects.filter(profile=other_profile).count(), 0)

    def test_qada_debt_list_only_shows_own_profiles(self):
        own_profile = self.make_profile(self.user, gender="male")
        other_profile = self.make_profile(self.other_user, gender="male")
        recalculate_and_store_qada_debt(own_profile)
        recalculate_and_store_qada_debt(other_profile)

        response = self.client.get("/api/qada-debt/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 5)  # only own_profile's 5 rows
        profile_ids = {row["profile"] for row in response.data}
        self.assertEqual(profile_ids, {own_profile.id})

    def test_qada_debt_rows_are_read_only(self):
        profile = self.make_profile(self.user, gender="male")
        rows = recalculate_and_store_qada_debt(profile)
        row_id = rows[0].id

        response = self.client.patch(
            f"/api/qada-debt/{row_id}/", {"remaining_count": 0}
        )
        # ReadOnlyModelViewSet doesn't expose PATCH at all.
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
