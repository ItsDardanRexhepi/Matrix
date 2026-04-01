"""
Temporal Context — gives agents awareness of time.

Provides current time, date formatting, relative time calculations,
and timezone-aware timestamps for agent responses.
"""

from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo


class TemporalContext:
    """
    Provides time awareness to agents. Injected into the system prompt
    so the agent knows the current date, time, and can reason about time.
    """

    def __init__(self, timezone_name: str = "UTC"):
        try:
            self.tz = ZoneInfo(timezone_name)
        except Exception:
            self.tz = timezone.utc

    @property
    def now(self) -> datetime:
        return datetime.now(self.tz)

    def get_context_string(self) -> str:
        """Return a human-readable time context for injection into prompts."""
        now = self.now
        return (
            f"Current date: {now.strftime('%A, %B %d, %Y')}\n"
            f"Current time: {now.strftime('%I:%M %p %Z')}"
        )

    def relative_time(self, dt: datetime) -> str:
        """Return a human-readable relative time string."""
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
            minutes = seconds // 60
            return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
        if seconds < 86400:
            hours = seconds // 3600
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        days = seconds // 86400
        if days == 1:
            return "yesterday"
        if days < 30:
            return f"{days} days ago"
        months = days // 30
        return f"{months} month{'s' if months != 1 else ''} ago"

    def _format_future(self, diff: timedelta) -> str:
        seconds = int(diff.total_seconds())
        if seconds < 60:
            return "in a moment"
        if seconds < 3600:
            minutes = seconds // 60
            return f"in {minutes} minute{'s' if minutes != 1 else ''}"
        if seconds < 86400:
            hours = seconds // 3600
            return f"in {hours} hour{'s' if hours != 1 else ''}"
        days = seconds // 86400
        if days == 1:
            return "tomorrow"
        return f"in {days} days"

    def parse_natural(self, text: str) -> datetime | None:
        """Parse simple natural language time references."""
        text = text.lower().strip()
        now = self.now

        simple_map = {
            "now": now,
            "today": now.replace(hour=0, minute=0, second=0, microsecond=0),
            "tomorrow": (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0),
            "yesterday": (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0),
        }

        return simple_map.get(text)
