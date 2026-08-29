from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.test import APITestCase

from .models import PrayerLog, Profile


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
