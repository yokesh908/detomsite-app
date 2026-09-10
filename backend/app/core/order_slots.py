"""
Delivery slot windows — the day is split into TWO delivery windows:

    Morning   : from the start of the day → 12:30 PM
    Afternoon : from 12:30 PM → 6:00 PM

Any order placed inside a window is ACCEPTED AUTOMATICALLY (the vendor no
longer taps Accept for every order), and the student can cancel it until that
window closes. Orders placed after 6:00 PM fall outside both windows — they
stay pending for the vendor and cannot be cancelled by the student.

All times are Asia/Kolkata (IST), matching the rest of the app's day/month
boundaries.
"""
from datetime import datetime, time, timedelta, timezone
from typing import Any, Optional

KOLKATA_TZ = timezone(timedelta(hours=5, minutes=30))

# Window cut-offs
MORNING_CUTOFF = time(12, 30)    # 12:30 PM
AFTERNOON_CUTOFF = time(18, 0)   # 6:00 PM

# Order statuses a student may cancel while the window is still open.
CANCELLABLE_STATUSES = ("Pending Acceptance", "Pending Payment", "Accepted")


def now_kolkata() -> datetime:
    """Current time in Asia/Kolkata."""
    return datetime.now(KOLKATA_TZ)


def parse_ist(value: Any) -> Optional[datetime]:
    """Normalize a stored timestamp to an IST-aware datetime.

    SQLite stores IST wall-clock time without an offset; Supabase stores UTC
    ISO strings. Both become a real datetime in Asia/Kolkata.
    """
    try:
        text = str(value or "").strip()
        if not text:
            return None
        text = text.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=KOLKATA_TZ)
        return parsed.astimezone(KOLKATA_TZ)
    except Exception:
        return None


def slot_cutoff_for(value: Any) -> Optional[time]:
    """The cut-off time of the delivery window a timestamp falls in.

    Returns 12:30 for morning-window times, 18:00 for afternoon-window times,
    and None for times outside both windows (after 6:00 PM).
    """
    parsed = value if isinstance(value, datetime) else parse_ist(value)
    if parsed is None:
        return None
    t = parsed.astimezone(KOLKATA_TZ).time()
    if t < MORNING_CUTOFF:
        return MORNING_CUTOFF
    if t < AFTERNOON_CUTOFF:
        return AFTERNOON_CUTOFF
    return None


def in_delivery_window(value: Any = None) -> bool:
    """True when a timestamp (default: now) falls inside a delivery window."""
    return slot_cutoff_for(value if value is not None else now_kolkata()) is not None
