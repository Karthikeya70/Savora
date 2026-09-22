"""
Two limits on the chat, both with no extra dependencies.

1. Per visitor: at most RATE messages per WINDOW seconds from one IP address.
   Stops one person hammering the chat.

2. Whole site, per day: at most DAILY_CHAT_LIMIT messages in total (set it as
   an environment variable). Every chat message costs a little on the AI key,
   so on a public link this is what guarantees a stranger can't run up a big
   bill. Unset means no daily limit, which is fine on your own laptop.

For multi-worker deployments, replace these in-memory counters with Redis.
"""
import os
import time
from collections import defaultdict
from datetime import date

from fastapi import Request
from fastapi.responses import JSONResponse

RATE   = 15   # requests per window
WINDOW = 60   # seconds

# {ip: [tokens_remaining, last_refill_time]}
_buckets: dict[str, list] = defaultdict(lambda: [float(RATE), time.time()])

_daily = {"day": date.today(), "count": 0}


def _daily_limit() -> int | None:
    raw = os.environ.get("DAILY_CHAT_LIMIT", "").strip()
    return int(raw) if raw.isdigit() else None


def check(request: Request) -> JSONResponse | None:
    """Return a 429 JSONResponse if the caller is over a limit, else None."""
    limit = _daily_limit()
    if limit is not None:
        today = date.today()
        if _daily["day"] != today:
            _daily.update(day=today, count=0)
        if _daily["count"] >= limit:
            return JSONResponse(
                status_code=429,
                content={"error": "This demo has reached its message limit for today. Please try again tomorrow."},
                headers={"Retry-After": "3600"},
            )

    ip = (request.client.host if request.client else None) or "unknown"
    bucket = _buckets[ip]
    now    = time.time()

    # Proportional refill
    elapsed  = now - bucket[1]
    bucket[0] = min(RATE, bucket[0] + (elapsed / WINDOW) * RATE)
    bucket[1] = now

    if bucket[0] < 1:
        return JSONResponse(
            status_code=429,
            content={"error": "Too many requests — please wait a moment."},
            headers={"Retry-After": "10"},
        )
    bucket[0] -= 1
    if limit is not None:
        _daily["count"] += 1
    return None
