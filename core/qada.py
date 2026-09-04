"""
Day 14: qada debt calculation logic (spec section 3).

Missed-prayer window = bulugh date (birth_date + bulugh_age years) up to
practice_start_date. Each day in that window counts as one missed prayer
per prayer type (5 total per day) -- so the raw debt for EVERY prayer type
starts out equal to the number of days in the window.

For female profiles, an estimated number of menstruation days within the
window is deducted uniformly across all 5 prayer types. This mirrors real
fiqh: a menstruating woman is exempt from all 5 daily prayers during that
time (not just some of them), and unlike prayers missed for other reasons,
those exempted prayers are NOT owed as qada afterward.

The menstruation estimate here is a rough, ADJUSTABLE approximation, not a
fiqh ruling on any individual's cycle. Actual menstruation length is
famously variable (Hanafi fiqh's own Hayd range spans 3-10 days per cycle,
and cycle length varies person to person), so this uses a commonly-cited
average -- 7 bleeding days out of a ~30-day cycle -- as a sensible default.
This matches the spec's explicit framing ("estimated menstruation-day
deductions") and the pattern used by comparable qada-tracking apps
researched for this feature. A future iteration could let the person enter
their own average cycle numbers instead of relying on this constant.
"""

from .models import Gender, Prayer, QadaDebt

MENSTRUATION_CYCLE_DAYS = 30
MENSTRUATION_DURATION_DAYS = 7


class QadaSetupIncomplete(Exception):
    """Raised when a profile is missing a field the calculation needs."""


def compute_bulugh_date(birth_date, bulugh_age):
    """
    birth_date + bulugh_age years, calendar-aware. Falls back to Feb 28
    when a Feb 29 birthday lands on a non-leap year at the target age --
    `date.replace()` would otherwise raise ValueError.
    """
    try:
        return birth_date.replace(year=birth_date.year + bulugh_age)
    except ValueError:
        return birth_date.replace(year=birth_date.year + bulugh_age, day=28)


def calculate_qada_debt(profile):
    """
    Returns a dict of {prayer_code: initial_debt_count} covering all 5
    prayers, per the spec: "Total days in the missed window x 5 prayers/day,
    minus estimated menstruation-day deductions if applicable = initial
    qada debt per prayer type."

    Raises QadaSetupIncomplete if the profile hasn't finished the Day 13
    qada setup fields this calculation depends on. `gender` is NOT required
    here even though it's part of setup -- it only affects whether a
    menstruation deduction applies, so a missing/non-female gender simply
    means no deduction, not an error.
    """
    if not (profile.birth_date and profile.bulugh_age and profile.practice_start_date):
        raise QadaSetupIncomplete(
            "Profile is missing birth_date, bulugh_age, or practice_start_date "
            "-- complete qada setup before calculating debt."
        )

    bulugh_date = compute_bulugh_date(profile.birth_date, profile.bulugh_age)

    # Clamped at 0: someone whose practice-start date is before/at their
    # bulugh date (e.g. they started praying right around puberty) owes
    # nothing -- this isn't an error case, just zero debt.
    missed_days = max((profile.practice_start_date - bulugh_date).days, 0)

    menstruation_days = 0
    if profile.gender == Gender.FEMALE:
        menstruation_days = round(
            missed_days * MENSTRUATION_DURATION_DAYS / MENSTRUATION_CYCLE_DAYS
        )

    net_days = max(missed_days - menstruation_days, 0)

    return {prayer: net_days for prayer in Prayer.values}


def recalculate_and_store_qada_debt(profile, force=False):
    """
    Computes the initial qada debt (see calculate_qada_debt) and persists
    it as one QadaDebt row per prayer.

    If QadaDebt rows already exist for this profile and `force` is False,
    they're left untouched and simply returned as-is. This matters once
    Day 16 wires up qada-prayer logging (which decrements remaining_count):
    without this guard, re-running the calculation -- e.g. because the
    setup screen was opened again -- would silently wipe out any progress
    already logged. Pass force=True for an explicit recalculation (e.g.
    the person corrected a qada-setup field and genuinely wants the debt
    recomputed from scratch).
    """
    existing = list(QadaDebt.objects.filter(profile=profile).order_by("prayer"))
    if existing and not force:
        return existing

    debt_by_prayer = calculate_qada_debt(profile)
    rows = []
    for prayer, count in debt_by_prayer.items():
        obj, _ = QadaDebt.objects.update_or_create(
            profile=profile,
            prayer=prayer,
            defaults={"remaining_count": count, "initial_count": count},
        )
        rows.append(obj)
    return sorted(rows, key=lambda r: r.prayer)
