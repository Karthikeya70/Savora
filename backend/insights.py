"""
Turns the raw event diary into the numbers shown on the insights page.

Every figure here answers a plain question a restaurant owner or product
person would ask:

  funnel            Of the people who asked a question, how many went on to order?
  topics            What do people ask about, and do those people end up ordering?
  dishes            For each dish: how often was it suggested, how often was it
                    picked after being suggested, and what % of eaters liked it?
  liked_by_path     Do people like their food more when the assistant suggested it?
  questions_before  How many questions does it take someone to decide?
  no_dish_questions Questions where the assistant couldn't point to any dish —
                    often a sign the menu is missing something people want.

All maths is done in plain Python over one source ("live" or "demo") so it is
easy to read and check. Fine for thousands of events; move to SQL if it grows.
"""
from collections import defaultdict
from datetime import datetime
from statistics import median

from .database import Event
from .events import TOPIC_LABELS

# Below this many ratings, a "% liked" number is shown but flagged as unreliable.
MIN_RATINGS_FOR_CONFIDENCE = 5


def _rate(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def build(db, dishes: list[dict], source: str = "live") -> dict:
    rows = (
        db.query(Event)
        .filter(Event.source == source)
        .order_by(Event.created_at, Event.id)
        .all()
    )

    by_type: dict[str, list[Event]] = defaultdict(list)
    for r in rows:
        by_type[r.event_type].append(r)

    def sessions_with(event_type: str) -> set[str]:
        return {r.session_id for r in by_type[event_type]}

    asked     = sessions_with("question_asked")
    suggested = sessions_with("dish_suggested")
    carted    = sessions_with("cart_added")
    ordered   = sessions_with("order_placed")
    rated     = sessions_with("dish_rated")
    everyone  = {r.session_id for r in rows}

    orders    = by_type["order_placed"]
    ratings   = by_type["dish_rated"]
    likes     = sum(1 for r in ratings if (r.properties or {}).get("liked"))

    orders_using_suggestion = sum(
        1 for o in orders
        if any(i.get("was_suggested") for i in (o.properties or {}).get("items", []))
    )

    # ── funnel ────────────────────────────────────────────────────────────────
    start = len(asked)
    funnel = [
        {"step": "asked",     "label": "Asked a question",        "customers": len(asked)},
        {"step": "suggested", "label": "Were suggested a dish",   "customers": len(suggested & asked)},
        {"step": "carted",    "label": "Added a dish to cart",    "customers": len(carted & asked)},
        {"step": "ordered",   "label": "Placed an order",         "customers": len(ordered & asked)},
        {"step": "rated",     "label": "Rated their food",        "customers": len(rated & asked)},
    ]
    for f in funnel:
        f["share_of_askers"] = _rate(f["customers"], start)

    # ── topics ────────────────────────────────────────────────────────────────
    topic_questions: dict[str, int]       = defaultdict(int)
    topic_sessions:  dict[str, set[str]]  = defaultdict(set)
    topic_speed:     dict[str, list[int]] = defaultdict(list)
    no_dish_questions = []

    for q in by_type["question_asked"]:
        p     = q.properties or {}
        topic = p.get("topic", "other")
        topic_questions[topic] += 1
        topic_sessions[topic].add(q.session_id)
        if not p.get("from_cache") and p.get("response_ms") is not None:
            topic_speed[topic].append(p["response_ms"])
        if p.get("handled_by") == "menu" and not p.get("dishes_named"):
            no_dish_questions.append({
                "question": p.get("question", ""),
                "topic":    topic,
                "label":    TOPIC_LABELS.get(topic, topic),
                "asked_at": q.created_at.isoformat() if q.created_at else None,
            })

    menu_answers = [q for q in by_type["question_asked"]
                    if (q.properties or {}).get("handled_by") == "menu"]
    invented = sum(1 for q in menu_answers if (q.properties or {}).get("invented_feedback"))

    total_questions = sum(topic_questions.values())
    topics = sorted(
        (
            {
                "topic":              t,
                "label":              TOPIC_LABELS.get(t, t),
                "questions":          n,
                "share":              _rate(n, total_questions),
                "customers":          len(topic_sessions[t]),
                "went_on_to_order":   _rate(len(topic_sessions[t] & ordered), len(topic_sessions[t])),
                "median_response_ms": round(median(topic_speed[t])) if topic_speed[t] else None,
            }
            for t, n in topic_questions.items()
        ),
        key=lambda t: t["questions"],
        reverse=True,
    )

    # ── dishes ────────────────────────────────────────────────────────────────
    shown_count:    dict[str, int]      = defaultdict(int)
    shown_sessions: dict[str, set[str]] = defaultdict(set)
    added_count:    dict[str, int]      = defaultdict(int)
    order_count:    dict[str, int]      = defaultdict(int)
    order_sessions: dict[str, set[str]] = defaultdict(set)
    dish_likes:     dict[str, int]      = defaultdict(int)
    dish_dislikes:  dict[str, int]      = defaultdict(int)

    for r in by_type["dish_suggested"]:
        shown_count[r.dish_name] += 1
        shown_sessions[r.dish_name].add(r.session_id)
    for r in by_type["cart_added"]:
        added_count[r.dish_name] += int((r.properties or {}).get("quantity") or 1)
    for o in orders:
        for item in (o.properties or {}).get("items", []):
            name = item.get("dish_name")
            order_count[name] += 1
            order_sessions[name].add(o.session_id)
    for r in ratings:
        if (r.properties or {}).get("liked"):
            dish_likes[r.dish_name] += 1
        else:
            dish_dislikes[r.dish_name] += 1

    dish_rows = []
    for d in dishes:
        name   = d.get("name")
        rated_n = dish_likes[name] + dish_dislikes[name]
        shown_n = len(shown_sessions[name])
        dish_rows.append({
            "dish":             name,
            "category":         d.get("category"),
            "price_inr":        d.get("price_inr"),
            "times_suggested":  shown_count[name],
            "customers_shown":  shown_n,
            "times_added":      added_count[name],
            "times_ordered":    order_count[name],
            # of the customers who were suggested this dish, how many ordered it
            "picked_when_suggested": _rate(len(shown_sessions[name] & order_sessions[name]), shown_n),
            "likes":            dish_likes[name],
            "dislikes":         dish_dislikes[name],
            "ratings":          rated_n,
            "like_rate":        _rate(dish_likes[name], rated_n),
            "low_sample":       rated_n < MIN_RATINGS_FOR_CONFIDENCE,
        })

    # ── liked more when suggested? ────────────────────────────────────────────
    path = {"suggested": [0, 0], "not_suggested": [0, 0]}  # [likes, total]
    for r in ratings:
        p   = r.properties or {}
        key = "suggested" if p.get("was_suggested") else "not_suggested"
        path[key][1] += 1
        if p.get("liked"):
            path[key][0] += 1
    liked_by_path = {
        k: {"likes": v[0], "ratings": v[1], "like_rate": _rate(v[0], v[1])}
        for k, v in path.items()
    }

    # ── how many questions before deciding? ───────────────────────────────────
    first_order_at: dict[str, datetime] = {}
    for o in orders:
        first_order_at.setdefault(o.session_id, o.created_at)
    counts = []
    for sid, when in first_order_at.items():
        counts.append(sum(
            1 for q in by_type["question_asked"]
            if q.session_id == sid and q.created_at <= when
        ))

    cancelled = len(by_type["order_cancelled"])

    return {
        "source":       source,
        "generated_at": datetime.utcnow().isoformat(),
        "has_data":     bool(rows),
        "headline": {
            "customers":               len(everyone),
            "questions":               total_questions,
            "orders":                  len(orders),
            "order_rate":              _rate(len(ordered & asked), len(asked)),
            "orders_using_suggestion": orders_using_suggestion,
            "suggestion_share":        _rate(orders_using_suggestion, len(orders)),
            "ratings":                 len(ratings),
            "like_rate":               _rate(likes, len(ratings)),
            "cancelled":               cancelled,
            "cancel_rate":             _rate(cancelled, len(orders)),
            "menu_answers":            len(menu_answers),
            "invented_feedback":       invented,
            "invented_feedback_rate":  _rate(invented, len(menu_answers)),
        },
        "funnel":            funnel,
        "topics":            topics,
        "dishes":            dish_rows,
        "liked_by_path":     liked_by_path,
        "questions_before_order": {
            "median":           median(counts) if counts else None,
            "customers":        len(counts),
        },
        "no_dish_questions": list(reversed(no_dish_questions))[:12],
        "min_ratings_for_confidence": MIN_RATINGS_FOR_CONFIDENCE,
    }
