"""
What real guests thought of each dish, fed back into the assistant's answers.

This closes the loop the app was missing:

    someone asks  ->  assistant suggests  ->  they order  ->  they rate it
                                    ^                              |
                                    +--- the next person sees it --+

Two rules, both deliberate:

1. Only real ("live") ratings count. Demo data is invented, and telling a
   customer that 9 of 11 guests liked a dish when nobody did would be a lie.
2. Nothing is shown until MIN_RATINGS people have rated a dish. Saying "1 of 1
   guests liked it" is noise, and early ratings swing wildly.
"""
import logging
import time
from collections import defaultdict

from .database import Event, SessionLocal

logger = logging.getLogger("savora.popularity")

MIN_RATINGS = 5     # below this, a "% liked" figure is too shaky to show a customer
MIN_ORDERS  = 5     # below this, don't call a dish popular
CACHE_TTL   = 60    # seconds; ratings change slowly, questions arrive quickly

_cache: dict = {"at": 0.0, "stats": {}}


def _load() -> dict[str, dict]:
    """{dish_name: {orders, ratings, likes, like_rate}} from real activity only."""
    orders  = defaultdict(int)
    likes   = defaultdict(int)
    ratings = defaultdict(int)

    db = SessionLocal()
    try:
        rows = (
            db.query(Event)
            .filter(Event.source == "live")
            .filter(Event.event_type.in_(["order_placed", "dish_rated"]))
            .all()
        )
    except Exception as e:
        logger.warning("Could not read guest feedback: %s", e)
        return {}
    finally:
        db.close()

    for r in rows:
        props = r.properties or {}
        if r.event_type == "order_placed":
            for item in props.get("items", []):
                orders[item.get("dish_name")] += int(item.get("quantity") or 1)
        else:
            ratings[r.dish_name] += 1
            if props.get("liked"):
                likes[r.dish_name] += 1

    return {
        name: {
            "orders":    orders.get(name, 0),
            "ratings":   ratings.get(name, 0),
            "likes":     likes.get(name, 0),
            "like_rate": likes.get(name, 0) / ratings[name] if ratings.get(name) else None,
        }
        for name in set(orders) | set(ratings)
        if name
    }


def snapshot(force: bool = False) -> dict[str, dict]:
    """Cached view of guest feedback, refreshed at most once every CACHE_TTL."""
    now = time.time()
    if force or now - _cache["at"] > CACHE_TTL:
        _cache["stats"] = _load()
        _cache["at"] = now
    return _cache["stats"]


NO_FEEDBACK = "no guest ratings yet — say nothing about what guests thought of this dish"


def describe(dish_name: str, stats: dict | None = None) -> str:
    """
    One short, factual line about a dish.

    Either real counts ("9 of 11 guests who rated this liked it") or an explicit
    statement that there is no feedback. Saying "no ratings yet" out loud matters:
    when the line was simply left out for unrated dishes, the assistant filled the
    silence and claimed guests had loved a dish nobody had rated.
    """
    s = (stats if stats is not None else snapshot()).get(dish_name)
    if not s:
        return NO_FEEDBACK

    parts = []
    if s["ratings"] >= MIN_RATINGS:
        parts.append(f"{s['likes']} of {s['ratings']} guests who rated this liked it")
    if s["orders"] >= MIN_ORDERS:
        parts.append(f"ordered {s['orders']} times recently")
    return "; ".join(parts) or NO_FEEDBACK


# Phrases that claim guests have an opinion. Used to check the assistant isn't
# inventing feedback for dishes that have none.
_CLAIM_PATTERNS = [
    r"guests?\s+(?:who\s+rated|rated|loved|enjoyed|liked)",
    r"(?:most|many|several|all)\s+(?:guests?|customers?|people|diners?)",
    r"(?:customers?|people|diners?)\s+(?:who\s+rated|rated|love|loved|enjoyed|liked)",
    r"\b(?:highly|well)[- ]rated\b",
    r"\bcrowd[- ]favou?rite\b",
    r"\b\d+\s*(?:of|out of)\s*\d+\s*(?:guests?|customers?|people)",
]


def unsupported_claim(answer: str, mentioned: list[str], stats: dict | None = None) -> bool:
    """
    True if the answer talks about what guests thought, while none of the dishes
    it named actually has enough ratings to support that.

    Deliberately cautious: if even one named dish has real feedback, the claim is
    treated as supported rather than guessing which dish it referred to.
    """
    import re

    if not re.search("|".join(_CLAIM_PATTERNS), answer or "", re.I):
        return False
    table = stats if stats is not None else snapshot()
    return not any((table.get(name) or {}).get("ratings", 0) >= MIN_RATINGS
                   for name in mentioned)


def reset_cache() -> None:
    """Used by tests and after data is cleared."""
    _cache["at"] = 0.0
    _cache["stats"] = {}
