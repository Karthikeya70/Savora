"""
Simple per-IP token-bucket rate limiter. No extra dependencies.
For multi-worker deployments, replace _buckets with Redis counters.
"""
import time
from collections import defaultdict

from fastapi import Request
from fastapi.responses import JSONResponse

RATE   = 15   # requests per window
WINDOW = 60   # seconds

# {ip: [tokens_remaining, last_refill_time]}
_buckets: dict[str, list] = defaultdict(lambda: [float(RATE), time.time()])


def check(request: Request) -> JSONResponse | None:
    """Return a 429 JSONResponse if caller is over the limit, else None."""
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
    return None
