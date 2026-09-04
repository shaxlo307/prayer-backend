# Backend — Django + DRF + PostgreSQL

Part of the Waqt prayer tracker project. See `../CLAUDE.md` at the project root for overall context, day-by-day history, and cross-cutting conventions — this file goes deeper on backend-specific implementation detail.

## Stack

- Django (settings in `config/settings.py`, env-driven via `django-environ` + `dj-database-url` — same code runs locally off `.env` and on Railway/Fly off their injected `DATABASE_URL`)
- Django REST Framework, HTTP Basic Auth (not token auth yet — flagged since Day 6 as not final)
- PostgreSQL (local dev db/user conventions: db `prayerapp_db`, user `prayerapp` — password is whatever your local `.env` has, not necessarily `prayerapp_dev`; check before assuming)
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

### `QadaDebt` (table: `qada_debt`) — **read-only API since Day 14**
- `profile` FK, `prayer` enum, `initial_count` (`PositiveIntegerField`, added Day 15 — migration `0003_qadadebt_initial_count`), `remaining_count` (`PositiveIntegerField`)
- Unique on `(profile, prayer)`
- `initial_count` is a fixed baseline set once at calculation time and never touched again by decrements — it exists purely so the Day 15 frontend progress bars can compute percent-complete (`initial_count - remaining_count`), since `remaining_count` alone can't show "how far along" once it starts decreasing.
- Written only by `core/qada.py`'s `recalculate_and_store_qada_debt()` (via `POST /api/profiles/{id}/calculate-qada-debt/`) — never directly through the API, so a client can't set an arbitrary `remaining_count` or `initial_count`. From Day 16 on, qada-log decrements will also write `remaining_count` (but never `initial_count`) on this table.

### `QadaLog` (table: `qada_logs`) — **not yet wired to any API (Day 16)**
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
| `/api/profiles/{id}/calculate-qada-debt/` | POST | `IsAuthenticated` + `IsOwner` | **New Day 14.** Computes the initial qada debt from the profile's qada-setup fields and stores it as 5 `QadaDebt` rows (one per prayer). Returns those rows. `400` if qada setup is incomplete. Idempotent by default — a second call returns the existing rows unchanged (protects future logged progress); pass `{"force": true}` in the body to explicitly recompute and overwrite. |
| `/api/qada-debt/` | GET | `IsAuthenticated` + `IsOwner` | **New Day 14.** `QadaDebtViewSet`, read-only (`ReadOnlyModelViewSet`) — lists the requesting account's own debt rows across all its profiles. Writes only happen via the calculate action above. |
| `/api-auth/` | GET | — | DRF's browsable-API login/logout, dev convenience only |

`IsOwner` permission class (in `core/views.py`) checks `obj.user` for `Profile` objects or `obj.profile.user` for `PrayerLog` objects — same pattern extended to `QadaDebt` objects too (via `obj.profile.user`).

## Qada debt calculation (`core/qada.py`) — Day 14

Implements spec section 3's formula: **total days in the missed window (bulugh date → practice-start date) × 5 prayers/day, minus an estimated menstruation-day deduction if applicable.** (Day 15 note: the resulting count is stored as both `initial_count` and `remaining_count` on first calculation — see the `QadaDebt` model entry above for why they're kept separate.)

- `compute_bulugh_date(birth_date, bulugh_age)` — adds `bulugh_age` years to `birth_date`. Handles the Feb-29-birthday-in-a-non-leap-year edge case by falling back to Feb 28 (`date.replace()` would otherwise raise `ValueError`).
- `calculate_qada_debt(profile)` — pure function, returns `{prayer: count}` for all 5 prayers. Raises `QadaSetupIncomplete` if `birth_date`/`bulugh_age`/`practice_start_date` aren't set. `gender` is read but not required — only `"female"` triggers the menstruation deduction; anything else (male, unset, future values) means zero deduction, not an error. Missed days are clamped at 0 (a practice-start date at or before the bulugh date owes nothing — not treated as invalid input).
- **Menstruation deduction is an adjustable estimate, not a fiqh ruling**: `MENSTRUATION_CYCLE_DAYS = 30`, `MENSTRUATION_DURATION_DAYS = 7` (module-level constants) — deduction = `round(missed_days * 7 / 30)`, applied uniformly across all 5 prayer types since a menstruating woman is exempt from all 5 daily prayers during that time, not just some, and those exempted prayers are never owed as qada. Real menstruation length varies a lot person to person (Hanafi fiqh's own Hayd range is 3-10 days per cycle) — this was chosen as a commonly-cited average after checking how comparable qada-tracking apps handle the same estimate, not derived from this app's own research. A future iteration could let the person enter their own average cycle numbers instead of relying on fixed constants.
- `recalculate_and_store_qada_debt(profile, force=False)` — computes + persists as `QadaDebt` rows. **Idempotent by default**: if rows already exist for the profile, returns them unchanged unless `force=True`. This matters once Day 16 wires up qada-prayer logging (which decrements `remaining_count`) — without this guard, reopening the qada setup screen and recalculating would silently wipe out logged progress. `force=True` is for an intentional full recompute (e.g. the person corrected a qada-setup field).

**Verified live**, not just via Django's test client: registered a device, PATCHed qada setup fields (female, birth date 2000-01-01, bulugh age 12 → bulugh date 2012-01-01, practice start 2013-01-01 → 366 missed days since 2012 was a leap year), called `calculate-qada-debt` against a real running server + real Postgres, got `281` per prayer (`366 - round(366×7/30) = 366 - 85 = 281`) — matches the formula by hand.

## Settings gotchas (`config/settings.py`)

- `ALLOWED_HOSTS` is forced to `["*"]` whenever `DEBUG=True` — added Day 12 after a real bug where testing from a physical phone hit the machine's LAN IP (not "localhost") and Django rejected it with `DisallowedHost`. This never applies in production since Railway/Fly always set `DEBUG=False` with their own explicit `ALLOWED_HOSTS`.
- `CORS_ALLOW_ALL_ORIGINS` defaults to `DEBUG`'s value — fine for dev, tighten for production via `CORS_ALLOWED_ORIGINS`.
- `DATABASE_URL` env var takes priority if set (Railway/Fly auto-inject this); falls back to discrete `DB_NAME`/`DB_USER`/etc. for local dev.

## Testing

- Django's test framework, in `core/tests.py`. **40 tests, all passing** as of Day 15 (was 39 as of Day 14; Day 15 extended the existing `test_recalculate_and_store_creates_rows_matching_calculation`/`test_recalculate_without_force_preserves_already_logged_progress`/`test_recalculate_with_force_overwrites_existing_rows` tests to also assert `initial_count` behavior, plus one new dedicated test — no new test class needed since this was a small model addition, not new logic).
- Covers: profile ownership + family-mode visibility (one account, multiple profiles), the one-self-profile-per-account constraint, prayer-log uniqueness + 3-state status validation, cross-account data isolation, cascade deletes, the `register_device` endpoint, `QadaDebtCalculationLogicTests` (pure `core/qada.py` logic — bulugh-date math including the leap-day edge case, missing-fields error, male/female/unset-gender deduction behavior, zero-clamping, idempotent-vs-forced recalculation, and now `initial_count` staying fixed across recalculation) plus `QadaDebtEndpointTests` (the `calculate-qada-debt` action and `qada-debt` list endpoint, including cross-account isolation and that the list endpoint is read-only).
- Run: `python manage.py test core` (or `python manage.py test core -v 2` for verbose per-test output)
- **When adding a feature, add tests in the same session** — this project's working convention, not optional.
- **Verification note (Day 15)**: the full 40-test suite was actually run against a real PostgreSQL instance, `makemigrations --check --dry-run` confirmed no pending migrations after applying `0003`, and the endpoint was re-smoke-tested live (register → qada setup PATCH → list [empty] → calculate → list [populated with matching `initial_count`/`remaining_count`]) against a real `runserver` process.

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

## Known backend gaps (Day 16+ work)

- `QadaDebt` now has read + calculate endpoints (Day 14) and a frontend display screen (Day 15), but **`QadaLog` (individual qada-prayer completions) still has zero API surface** — Day 16's "log a qada prayer, decrement debt by 1" needs a `QadaLogSerializer`/endpoint that both creates a `QadaLog` row and decrements the matching `QadaDebt.remaining_count` (probably in one transaction, mirroring `recalculate_and_store_qada_debt`'s pattern in `core/qada.py`) — importantly, it must decrement `remaining_count` only and leave `initial_count` untouched.
- No endpoint yet computes the spec's "estimated completion date = remaining debt ÷ average qada-prayers-logged-per-day over the last 2 weeks" — that's Day 17, and depends on `QadaLog` existing first (Day 16).
- Streak calculation: no cron/scheduled job or on-write logic exists yet to populate `current_streak`/`longest_streak`.
- Notification settings: model only, no endpoints, no actual push notification integration (APNs/FCM) anywhere.
- No pagination or date-range filtering on `/api/prayer-logs/` — returns the full history every time. Fine for now; will need attention as usage grows.
- The menstruation-day estimate (`core/qada.py`'s `MENSTRUATION_CYCLE_DAYS`/`MENSTRUATION_DURATION_DAYS`) is a fixed, non-personalized constant — a real improvement later would let the person enter their own average cycle/duration instead.