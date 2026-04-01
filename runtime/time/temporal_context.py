"""
Temporal Context — gives agents awareness of time.

Default timezone: America/Los_Angeles. Updates on every call — never cached.
Includes helpers for weekday, business hours, day of week, days until date.
"""

from datetime import datetime, timezone, timedelta, date
from zoneinfo import ZoneInfo


class TemporalContext:

    def __init__(self, timezone_name: str = "America/Los_Angeles"):
        try:
            self.tz = ZoneInfo(timezone_name)
        except Exception:
            self.tz = ZoneInfo("America/Los_Angeles")

    @property
    def now(self) -> datetime:
        """Always returns the live current time — never cached."""
        return datetime.now(self.tz)

    def get_context_string(self) -> str:
        """Human-readable time context for injection into prompts. Called fresh every turn."""
        now = self.now
        return (
            f"Current date and time: {now.strftime('%A, %B %d, %Y')} "
            f"at {now.strftime('%I:%M %p %Z')}"
        )

    def is_weekday(self) -> bool:
        return self.now.weekday() < 5

    def is_weekend(self) -> bool:
        return self.now.weekday() >= 5

    def is_business_hours(self) -> bool:
        """Business hours: Monday-Friday, 9 AM - 5 PM in configured timezone."""
        now = self.now
        return now.weekday() < 5 and 9 <= now.hour < 17

    def day_of_week(self) -> str:
        return self.now.strftime("%A")

    def days_until(self, target_date: str) -> int:
        """Calculate days until a target date (YYYY-MM-DD format)."""
        try:
            target = date.fromisoformat(target_date)
            today = self.now.date()
            return (target - today).days
        except ValueError:
            return -1

    def relative_time(self, dt: datetime) -> str:
        now = self.now
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=self.tz)
        diff = now - dt
        if diff < timedelta(0):
            return self._format_future(-diff)
        return self._format_past(diff)

    def _format_past(self, diff: timedelta) -> str:
        seconds = int(diff.total_seconds())
        if seconds < 60:
            return "just now"
        if seconds < 3600:
            m = seconds // 60
            return f"{m} minute{'s' if m != 1 else ''} ago"
        if seconds < 86400:
            h = seconds // 3600
            return f"{h} hour{'s' if h != 1 else ''} ago"
        d = seconds // 86400
        if d == 1:
            return "yesterday"
        if d < 30:
            return f"{d} days ago"
        mo = d // 30
        return f"{mo} month{'s' if mo != 1 else ''} ago"

    def _format_future(self, diff: timedelta) -> str:
        seconds = int(diff.total_seconds())
        if seconds < 60:
            return "in a moment"
        if seconds < 3600:
            m = seconds // 60
            return f"in {m} minute{'s' if m != 1 else ''}"
        if seconds < 86400:
            h = seconds // 3600
            return f"in {h} hour{'s' if h != 1 else ''}"
        d = seconds // 86400
        if d == 1:
            return "tomorrow"
        return f"in {d} days"
