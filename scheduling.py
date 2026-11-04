"""Publish-time logic for Thought After 2AM.

Bangladesh time (BST) is UTC+6 all year (no daylight saving).
    Morning slot: 07:00 BST = 01:00 UTC
    Evening slot: 21:00 BST = 15:00 UTC
The GitHub workflow starts one hour earlier (00:00 and 14:00 UTC) so the video has time to
be written, rendered and uploaded before YouTube makes it public.
"""
from datetime import timedelta, timezone

BD_TZ = timezone(timedelta(hours=6))
SLOT_BD_TIME = {"morning": (7, 0), "evening": (21, 0)}

# A manual run needs time to render before the slot, so it targets the next slot at least this far away.
MANUAL_MIN_LEAD = timedelta(minutes=20)
# YouTube requires publishAt to be in the future when the upload request is made.
UPLOAD_MIN_LEAD = timedelta(minutes=3)
# If a run is so late that its slot already passed, publish this long after "now" instead.
LATE_FALLBACK_DELAY = timedelta(minutes=5)


def _as_utc(dt):
    if dt.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    return dt.astimezone(timezone.utc)


def _slot_candidates(slot, now_utc):
    """Slot occurrences on the Bangladesh calendar day before, of, and after `now`."""
    if slot not in SLOT_BD_TIME:
        raise ValueError(f"Unknown slot {slot!r}; expected one of {sorted(SLOT_BD_TIME)}")
    hour, minute = SLOT_BD_TIME[slot]
    today = _as_utc(now_utc).astimezone(BD_TZ).replace(hour=hour, minute=minute, second=0, microsecond=0)
    return [(today + timedelta(days=d)).astimezone(timezone.utc) for d in (-1, 0, 1)]


def choose_publish_time(slot, now_utc, event_name="workflow_dispatch"):
    """Pick the intended publication moment (UTC) for this run.

    schedule          -> the slot occurrence nearest to the run's start. A delayed cron run therefore
                         still aims at "its own" slot instead of jumping 24 hours ahead.
    anything else     -> the next slot occurrence that is at least MANUAL_MIN_LEAD away.
    """
    now_utc = _as_utc(now_utc)
    candidates = _slot_candidates(slot, now_utc)
    if event_name == "schedule":
        return min(candidates, key=lambda c: abs(c - now_utc))
    return min(c for c in candidates if c >= now_utc + MANUAL_MIN_LEAD)


def finalize_publish_time(target_utc, now_utc):
    """Re-check the target right before upload. Returns (publish_time_utc, was_late)."""
    target_utc, now_utc = _as_utc(target_utc), _as_utc(now_utc)
    if target_utc >= now_utc + UPLOAD_MIN_LEAD:
        return target_utc, False
    return (now_utc + LATE_FALLBACK_DELAY).replace(microsecond=0), True


def to_youtube_timestamp(dt):
    """RFC 3339 / ISO 8601 in UTC with a trailing Z, as the YouTube Data API expects."""
    return _as_utc(dt).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def describe(dt):
    dt = _as_utc(dt)
    return f"{dt:%Y-%m-%d %H:%M} UTC / {dt.astimezone(BD_TZ):%Y-%m-%d %H:%M} Bangladesh"
