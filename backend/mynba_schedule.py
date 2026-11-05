"""
The weekly lock: when gameplans (and, if the league wants, roster moves) stop
changing before a sim, and when they open again.

Commissioners set it on the Rules tab as a day before the sim plus a time of
day, Eastern: `gameplan_lock_days` (0 = sim day itself) and
`gameplan_lock_minute` (minutes after midnight, 900 = 3:00 PM). The lock holds
until the end of sim day.

The server has no tzdata, and the league only ever runs on Eastern time, so US
DST is computed directly: second Sunday of March 2 AM to first Sunday of
November 2 AM. No imports from the other mynba modules, so any of them can use it.
"""
from datetime import datetime, date, time, timedelta

DEFAULT_LOCK_DAYS = 2        # Thursday before a Saturday sim
DEFAULT_LOCK_MINUTE = 23 * 60 + 59


def _nth_sunday(year, month, n):
    first = date(year, month, 1)
    first_sunday = first + timedelta(days=(6 - first.weekday()) % 7)
    return first_sunday + timedelta(weeks=n - 1)


def _eastern_offset(local_dt):
    """UTC offset for a naive Eastern wall-clock time."""
    start = datetime.combine(_nth_sunday(local_dt.year, 3, 2), time(2))
    end = datetime.combine(_nth_sunday(local_dt.year, 11, 1), time(2))
    return timedelta(hours=-4) if start <= local_dt < end else timedelta(hours=-5)


def utc_to_eastern(utc_dt):
    # DST starts 2 AM EST (07:00 UTC) and ends 2 AM EDT (06:00 UTC).
    start = datetime.combine(_nth_sunday(utc_dt.year, 3, 2), time(7))
    end = datetime.combine(_nth_sunday(utc_dt.year, 11, 1), time(6))
    return utc_dt + (timedelta(hours=-4) if start <= utc_dt < end else timedelta(hours=-5))


def eastern_to_utc(local_dt):
    return local_dt - _eastern_offset(local_dt)


def iso(dt):
    return dt.isoformat() + "Z" if dt else None


def format_minute(minute):
    """900 -> "3:00 PM"."""
    hour, mins = divmod(int(minute) % 1440, 60)
    return f"{hour % 12 or 12}:{mins:02d} {'AM' if hour < 12 else 'PM'}"


def lock_settings(league):
    days = league.gameplan_lock_days if league.gameplan_lock_days is not None else DEFAULT_LOCK_DAYS
    minute = getattr(league, "gameplan_lock_minute", None)
    minute = DEFAULT_LOCK_MINUTE if minute is None else minute
    return max(0, min(6, days)), max(0, min(1439, minute))


def lock_status(league, now_utc=None):
    """Whether the weekly lock is on right now, and the next deadline."""
    now_utc = now_utc or datetime.utcnow()
    local = utc_to_eastern(now_utc)
    sim_weekday = league.sim_weekday if league.sim_weekday is not None else 5
    lock_days, lock_minute = lock_settings(league)
    at = time(lock_minute // 60, lock_minute % 60)

    # The coming sim day, counting today if today is sim day.
    sim_date = local.date() + timedelta(days=(sim_weekday - local.weekday()) % 7)
    lock_start = datetime.combine(sim_date - timedelta(days=lock_days), at)
    unlock_at = datetime.combine(sim_date + timedelta(days=1), time(0))
    scheduled_lock = lock_start <= local < unlock_at

    if scheduled_lock:
        next_sim = sim_date + timedelta(days=7)
        next_deadline = datetime.combine(next_sim - timedelta(days=lock_days), at)
    else:
        next_sim = sim_date
        next_deadline = lock_start

    override = league.gameplan_lock_override
    locked = scheduled_lock if override is None else bool(override)
    return {
        "locked": locked,
        "override": override,
        "rosters_lock": bool(getattr(league, "lock_roster_moves", False)),
        "sim_date": (sim_date if scheduled_lock else next_sim).isoformat(),
        # The moment edits stop, as UTC, and as GMs see it: "Sat Oct 24, 3:00 PM ET".
        "deadline_utc": iso(eastern_to_utc(next_deadline)),
        "deadline_label": f"{next_deadline.strftime('%a %b')} {next_deadline.day}, {format_minute(lock_minute)} ET",
        "unlocks_at_utc": iso(eastern_to_utc(unlock_at)) if locked and override is None else None,
    }


def roster_lock_message(league, now_utc=None):
    """Why roster moves are blocked right now, or None.

    Covers both the commissioner's trade-deadline switch and the weekly lock
    (when the league has roster moves follow it).
    """
    if league.trades_locked:
        reason = f" ({league.trades_locked_reason})" if league.trades_locked_reason else ""
        return f"Trading is locked right now{reason}."
    if getattr(league, "lock_roster_moves", False) and lock_status(league, now_utc)["locked"]:
        return "Rosters are locked until after the sim."
    return None
