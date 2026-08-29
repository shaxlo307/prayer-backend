# Backend — Django + DRF + PostgreSQL

Part of the Waqt prayer tracker project. See `../CLAUDE.md` at the project root for overall context, day-by-day history, and cross-cutting conventions — this file goes deeper on backend-specific implementation detail.

## Stack

- Django (settings in `config/settings.py`, env-driven via `django-environ` + `dj-database-url` — same code runs locally off `.env` and on Railway/Fly off their injected `DATABASE_URL`)
- Django REST Framework, HTTP Basic Auth (not token auth yet — flagged since Day 6 as not final)
- PostgreSQL (local dev db/user conventions: db `prayerapp_db`, user `prayerapp`, password `prayerapp_dev` — see `.env.example`)
- WhiteNoise for static files, `django-cors-headers` for the Expo app's cross-origin calls
- Deployment: `Procfile` (release phase runs migrations, then gunicorn), `runtime.txt`

## ⚠️ Critical: the temporary device-registration endpoint

`POST /api/register/` (in `core/views.py`, function `register_device`) is **intentional scaffolding**, not a mistake to "clean up." The build roadmap doesn't introduce real sign-up/login until Day 19, but the mobile app needed persistent identity starting Day 10. This endpoint:
- Requires no auth (`AllowAny`)
- Generates a random `username`/`password`, creates a Django `User` + a `self` `Profile`
- Returns the credentials once; the app stores them client-side (`expo-secure-store`) and reuses them via Basic Auth on every subsequent request

**When Day 19 (real parent account creation) is built**, this needs explicit reconciliation — decide whether device-registered accounts get claimed/upgraded, or whether new real accounts coexist alongside old device accounts. Don't rip this out casually; check with the person building the app first, since the mobile app's `lib/session.ts` depends on it existing.

## Data model (`core/models.py`) — full detail

7 tables total: `auth_user` (Django built-in) + 6 custom.

### `Profile` (table: `profiles`)
- `user` — **ForeignKey** to `auth_user` (NOT OneToOne — this was a deliberate Day 7.5 reconciliation decision). One account can own multiple profiles.
- `type` — `CharField`, choices `self`/`child` (`ProfileType` enum)
- `display_name` — `CharField`
- `age` — `PositiveSmallIntegerField`, nullable. Only shapes reminder tone for child profiles, nothing else — do not confuse with `birth_date` below.
- `qada_enabled` — `BooleanField`, default `True`. Toggle off for children just building the habit.
- `birth_date`, `gender` (`male`/`female`, nullable), `bulugh_age` (nullable), `practice_start_date` (nullable) — qada debt calculation inputs. **Day 13 will build the UI for these; the fields already exist, no migration needed.**
- `madhhab` — `hanafi`/`shafi` (the latter covers Shafi'i/Maliki/Hanbali combined per the spec)
- `calculation_method` — `PositiveSmallIntegerField`, default `2` (Aladhan API method ID — 2 is ISNA)
- `latitude`, `longitude` — `DecimalField`, nullable
- `city` — `CharField`, blank-ok
- `timezone` — `CharField`, default `"UTC"`
- **Constraint**: partial unique index on `(user, type)` where `type='self'` — exactly one self-profile per account, unlimited child profiles. Named `one_self_profile_per_user` in the migration.

### `PrayerLog` (table: `prayer_logs`)
- `profile` FK, `date`, `prayer` (enum: `fajr`/`dhuhr`/`asr`/`maghrib`/`isha`)
- `status` — **3-state enum** `unmarked`/`done`/`late` (NOT a boolean — this was a Day 7.5 reconciliation change from the original boolean `completed` field)
- **Constraint**: unique on `(profile, date, prayer)` — the DB itself prevents duplicate rows for the same prayer/day.

### `QadaDebt` (table: `qada_debt`) — **not yet wired to any API**
- `profile` FK, `prayer` enum, `remaining_count` (`PositiveIntegerField`)
- Unique on `(profile, prayer)`

### `QadaLog` (table: `qada_logs`) — **not yet wired to any API**
- `profile` FK, `prayer` enum, `logged_at` (auto timestamp) — append-only history of qada catch-up prayers

### `Streak` (table: `streaks`) — **model exists, no calculation logic populates it yet**
- `profile` (OneToOne), `current_streak`, `longest_streak`, `last_calculated_date`

### `NotificationSettings` (table: `notification_settings`) — **model exists, completely unused**
- `profile` (OneToOne), `enabled` (bool), `tone` (`standard`/`gentle`), `muted_by_parent` (bool)

## API endpoints (`config/urls.py`, `core/views.py`)

| Endpoint | Method(s) | Auth | Notes |
|---|---|---|---|
| `/api/health/` | GET | none | Liveness check, confirms DB connection too |
| `/api/register/` | POST | none | Temporary device bootstrap — see warning above |
| `/api/profiles/` | GET, POST, PATCH, DELETE | `IsAuthenticated` + `IsOwner` | `ProfileViewSet`; `get_queryset` returns all profiles where `user=request.user` (covers self + all children automatically, since they share the same `user` FK) |
| `/api/prayer-logs/` | GET, POST, PATCH, DELETE | `IsAuthenticated` + `IsOwner` | `PrayerLogViewSet`; serializer's `validate_profile` blocks writing to a profile outside your own account |
| `/api-auth/` | GET | — | DRF's browsable-API login/logout, dev convenience only |

`IsOwner` permission class (in `core/views.py`) checks `obj.user` for `Profile` objects or `obj.profile.user` for `PrayerLog` objects — same pattern if new owned models get their own viewsets later.

## Settings gotchas (`config/settings.py`)

- `ALLOWED_HOSTS` is forced to `["*"]` whenever `DEBUG=True` — added Day 12 after a real bug where testing from a physical phone hit the machine's LAN IP (not "localhost") and Django rejected it with `DisallowedHost`. This never applies in production since Railway/Fly always set `DEBUG=False` with their own explicit `ALLOWED_HOSTS`.
- `CORS_ALLOW_ALL_ORIGINS` defaults to `DEBUG`'s value — fine for dev, tighten for production via `CORS_ALLOWED_ORIGINS`.
- `DATABASE_URL` env var takes priority if set (Railway/Fly auto-inject this); falls back to discrete `DB_NAME`/`DB_USER`/etc. for local dev.

## Testing

- Django's test framework, in `core/tests.py`. **20 tests, all passing** as of Day 12.
- Covers: profile ownership + family-mode visibility (one account, multiple profiles), the one-self-profile-per-account constraint, prayer-log uniqueness + 3-state status validation, cross-account data isolation, cascade deletes, and the `register_device` endpoint (including that it needs no auth and each call creates a distinct account).
- Run: `python manage.py test core` (or `python manage.py test core -v 2` for verbose per-test output)
- **When adding a feature, add tests in the same session** — this project's working convention, not optional.

## Local dev setup

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
# PostgreSQL must be running with a db/user matching your .env
# (defaults: db=prayerapp_db, user=prayerapp, password=prayerapp_dev)
python manage.py migrate
python manage.py runserver 0.0.0.0:8000   # 0.0.0.0 matters — needed for phone/LAN access
```

Health check: `curl http://127.0.0.1:8000/api/health/` should return `{"status": "ok", ...}`.

## Known backend gaps (Day 13+ work)

- Qada tracker has models but **zero API surface** — Day 13 needs serializers + a viewset (or custom endpoints) for `QadaDebt`/`QadaLog`, plus the actual debt-calculation logic (total days in missed window × 5 prayers, minus menstruation-day estimates, per the spec).
- Streak calculation: no cron/scheduled job or on-write logic exists yet to populate `current_streak`/`longest_streak`.
- Notification settings: model only, no endpoints, no actual push notification integration (APNs/FCM) anywhere.
- No pagination or date-range filtering on `/api/prayer-logs/` — returns the full history every time. Fine for now; will need attention as usage grows.