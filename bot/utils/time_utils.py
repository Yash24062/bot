from datetime import datetime, timezone, timedelta

# =========================
#  TIME UTILITY FUNCTIONS
# =========================

def dt_to_millis(dt: datetime) -> int:
    """
    Convert a datetime object (UTC) to milliseconds since epoch.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def millis_to_dt(millis: int) -> datetime:
    """
    Convert milliseconds since epoch to timezone-aware UTC datetime.
    """
    return datetime.fromtimestamp(millis / 1000.0, tz=timezone.utc)


def parse_date(date_str: str, default: datetime = None) -> datetime:
    """
    Parse 'YYYY-MM-DD' string into UTC datetime.
    Returns default (or current UTC time) if invalid or None.
    """
    if not date_str:
        return default or datetime.now(timezone.utc)
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except Exception:
        return default or datetime.now(timezone.utc)


def now_utc() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


def seconds_ago(seconds: int) -> datetime:
    """Return a UTC datetime 'seconds' ago."""
    return datetime.now(timezone.utc) - timedelta(seconds=seconds)
