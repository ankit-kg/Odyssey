from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any, Callable, TypeVar


T = TypeVar("T")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def from_utc_timestamp(ts: float | int) -> datetime:
    return datetime.fromtimestamp(float(ts), tz=timezone.utc)


def to_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).isoformat()


def safe_jsonable(value: Any) -> Any:
    """
    Convert common PRAW objects into something JSON-serializable.
    This is intentionally lossy; the goal is to preserve the raw-ish shape
    without failing inserts due to non-serializable objects.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, (list, tuple)):
        return [safe_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): safe_jsonable(v) for k, v in value.items()}

    # PRAW models often expose a dict of primitive fields
    if hasattr(value, "__dict__"):
        d = {}
        for k, v in vars(value).items():
            # Drop known non-serializable / noisy fields
            if k in {"_reddit", "reddit", "subreddit", "author", "mod"}:
                continue
            d[str(k)] = safe_jsonable(v)
        return d

    return str(value)


def ensure_jsonable_dict(d: dict[str, Any]) -> dict[str, Any]:
    out = safe_jsonable(d)
    # Validate it can actually serialize
    json.dumps(out)
    return out  # type: ignore[return-value]


def with_retry_once(fn: Callable[[], T], *, on_retry_sleep_s: float = 2.0) -> T:
    """
    Required behavior: retry exactly once; if it fails again, raise.
    """
    try:
        return fn()
    except Exception:
        time.sleep(on_retry_sleep_s)
        return fn()


