"""
Create practice data for the insights page.

    python scripts/demo_data.py                  # replace demo data with 600 pretend customers
    python scripts/demo_data.py --customers 800  # more customers
    python scripts/demo_data.py --clear          # remove all demo data, add nothing

IMPORTANT — what this is and isn't:
  Every row written here is marked source="demo" and is invented by the rules
  below. It exists so you can see the insights page working and learn to read
  it. The patterns in it are patterns this script put there, so they are NOT
  findings and must never be presented as real customer behaviour.

  Real numbers come only from people actually using the app (source="live").
  The insights page keeps the two completely separate.

Demo data only goes into the events diary. It never creates orders, so the
kitchen board stays clean.

Two extras, both for practice:
  * A/B test groups. Every pretend visitor is put in group A or B exactly as the
    real app does it. The two groups are given NO real difference in how likely
    they are to order, so any gap you see in the results is luck. That is the
    point: learning to tell a real difference from noise.
  * One planted problem. On one day, something goes wrong and orders drop.
    Finding what it was is the root-cause exercise in analysis/README.md.
    Don't read the code below if you want to solve it yourself.
"""
import argparse
import math
import os
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
# Same local database as run_local.py, unless you've set DATABASE_URL yourself.
os.environ.setdefault("DATABASE_URL", f"sqlite:///{(ROOT / 'savora_local.db').as_posix()}")

from backend import events, experiment            # noqa: E402
from backend.data import load_menu                # noqa: E402
from backend.database import Event, SessionLocal, init_db  # noqa: E402

DISHES = load_menu()["dishes"]
BY_NAME = {d["name"]: d for d in DISHES}


# ── pretend-customer rules ────────────────────────────────────────────────────

FIRST_TOPIC_WEIGHTS = {
    "allergy_or_diet": 0.30, "recommendation": 0.26, "budget": 0.14,
    "other": 0.12, "ingredients": 0.10, "spice": 0.08,
}

QUESTIONS = {
    "allergy_or_diet": ["Which dishes are nut-free?", "Is the {dish} vegan?", "Anything without dairy?",
                        "What's gluten-free here?", "I'm allergic to peanuts, what can I eat?",
                        "Which dishes are eggless?", "Is the {dish} Jain friendly?"],
    "ingredients":     ["What's in the {dish}?", "Does the {dish} have onion or garlic?",
                        "Which dishes are high in protein?"],
    "budget":          ["What can I get under ₹150?", "Cheapest filling meal?",
                        "Anything good under 200 rupees?"],
    "spice":           ["What's not spicy at all?", "How spicy is the {dish}?", "Spiciest thing on the menu?"],
    "recommendation":  ["What do you recommend?", "What's popular here?", "Can't decide, help me pick",
                        "What pairs well with the {dish}?"],
    "other":           ["Do you have sushi?", "Do you have cheesecake?", "Is there a kids menu?",
                        "Do you serve sugar free desserts?", "What are your opening hours?"],
}

ALLERGENS = ["dairy", "gluten", "tree_nut", "egg"]


def spice_level(d):
    s = d.get("spice") or ""
    for n in "4321":
        if f"level {n}/" in s:
            return int(n)
    return 0


def appeal(d):
    """How appealing a dish is to pretend customers (drives picks and likes)."""
    score = 0.72
    if "BESTSELLER" in d.get("badges", []):
        score += 0.10
    match = d.get("photo_reality_match_pct")
    if match is not None and match < 90:
        score -= (90 - match) / 100 * 1.2   # food that looks nothing like the photo disappoints
    return max(0.05, min(0.95, score))


def weighted_sample(rng, pool, k, weight=appeal):
    pool, out = list(pool), []
    while pool and len(out) < k:
        weights = [max(0.01, weight(d)) for d in pool]
        pick = rng.choices(pool, weights=weights, k=1)[0]
        out.append(pick)
        pool.remove(pick)
    return out


def dishes_for(rng, topic, anchor, k=3):
    """Which dishes the pretend assistant names for a question on this topic."""
    if topic == "allergy_or_diet":
        allergen = rng.choice(ALLERGENS)
        pool = [d for d in DISHES if allergen not in d.get("allergens_contains", [])]
        return weighted_sample(rng, pool, k)
    if topic == "ingredients":
        return [anchor]
    if topic == "budget":
        return weighted_sample(rng, [d for d in DISHES if d["price_inr"] <= 150], k)
    if topic == "spice":
        mild = rng.random() < 0.6
        pool = [d for d in DISHES if (spice_level(d) <= 1) == mild]
        return weighted_sample(rng, pool, k)
    if topic == "recommendation":
        return weighted_sample(rng, DISHES, k, weight=lambda d: appeal(d) ** 2)
    return []


def response_ms(rng, topic, broken=False):
    if rng.random() < 0.18 and not broken:
        return round(rng.uniform(8, 40)), True          # answered from cache
    base = 2100 if topic == "allergy_or_diet" else 650
    if broken:
        base *= 4.5                                      # the planted problem
    return round(base * math.exp(rng.gauss(0, 0.55))), False


def session_start(rng, days):
    day  = rng.randrange(days)
    hour = rng.choices([12, 13, 14, 19, 20, 21, 16, 11], weights=[3, 4, 2, 4, 5, 3, 1, 1])[0]
    now   = datetime.utcnow()
    start = (now - timedelta(days=day)).replace(hour=hour, minute=rng.randrange(60), second=0, microsecond=0)
    return start - timedelta(days=1) if start > now else start   # never in the future


def one_customer(rng, days, bad_day):
    sid   = "demo-" + format(rng.getrandbits(48), "012x")
    clock = session_start(rng, days)
    rows  = []
    group = experiment.group_for(sid)          # same rule as the real app
    on_bad_day = clock.date() == bad_day

    def emit(event_type, dish=None, **props):
        nonlocal clock
        clock += timedelta(seconds=rng.randint(12, 75))
        rows.append(Event(session_id=sid, event_type=event_type, dish_name=dish,
                          properties=props, source="demo", created_at=clock))

    # ── asking ──
    shown: list[str] = []
    n_questions = rng.choices([1, 2, 3, 4], weights=[35, 35, 20, 10])[0]
    topic = rng.choices(list(FIRST_TOPIC_WEIGHTS), weights=list(FIRST_TOPIC_WEIGHTS.values()))[0]
    first_topic = topic
    for i in range(n_questions):
        if i:  # follow-ups usually stay on a similar track
            topic = topic if rng.random() < 0.45 else rng.choice(list(FIRST_TOPIC_WEIGHTS))
        anchor   = rng.choice(DISHES)
        question = rng.choice(QUESTIONS[topic]).format(dish=anchor["name"])
        handled  = "support" if "opening hours" in question else "menu"
        # Group B's answers name at most 3 dishes; group A's often name more.
        k        = 3 if group == "B" else rng.choice([3, 4, 5])
        named    = dishes_for(rng, topic, anchor, k) if handled == "menu" else []
        ms, cached = response_ms(rng, topic, broken=on_bad_day and topic == "allergy_or_diet")
        emit("question_asked",
             question=question,
             topic=events.question_topic(question, DISHES, handled),
             handled_by=handled, from_cache=cached, response_ms=ms, dishes_named=len(named),
             invented_feedback=False, ab_group=group)
        for pos, d in enumerate(named, 1):
            emit("dish_suggested", d["name"], position=pos)
            shown.append(d["name"])

    # ── deciding ──
    # Deliberately identical for groups A and B: the test has no real effect.
    wants_to_order = 0.66 if shown else 0.18
    if on_bad_day and first_topic == "allergy_or_diet":
        wants_to_order = 0.08                    # people gave up waiting
    if rng.random() > wants_to_order:
        return rows

    cart: dict[str, int] = {}
    for _ in range(rng.choices([1, 2, 3], weights=[45, 40, 15])[0]):
        if shown and rng.random() < 0.78:
            pool = [BY_NAME[n] for n in dict.fromkeys(shown) if n not in cart]
        else:
            pool = [d for d in DISHES if d["name"] not in cart]
        if not pool:
            continue
        dish = weighted_sample(rng, pool, 1, weight=lambda d: appeal(d) ** 1.5)[0]["name"]
        qty  = rng.choices([1, 2], weights=[80, 20])[0]
        cart[dish] = qty
        emit("cart_added", dish, quantity=qty, was_suggested=dish in shown)

    if cart and rng.random() < 0.10:  # changes their mind about one dish
        dish = rng.choice(list(cart))
        emit("cart_removed", dish, quantity=cart.pop(dish))

    if not cart or rng.random() < 0.17:  # leaves without ordering
        return rows

    order_id = "demo-order-" + format(rng.getrandbits(40), "010x")
    emit("order_placed", order_id=order_id,
         total=float(sum(BY_NAME[d]["price_inr"] * q for d, q in cart.items())),
         items=[{"dish_name": d, "quantity": q, "was_suggested": d in shown} for d, q in cart.items()])

    if rng.random() < 0.05:
        emit("order_cancelled", order_id=order_id, by=rng.choice(["customer", "kitchen"]))
        return rows

    # ── eating & rating ──
    if rng.random() < 0.62:
        for dish in cart:
            like_p = appeal(BY_NAME[dish]) + (0.06 if dish in shown else 0)
            emit("dish_rated", dish, order_id=order_id,
                 liked=rng.random() < min(0.97, like_p), was_suggested=dish in shown)
    return rows


# ── main ──────────────────────────────────────────────────────────────────────

def clear_demo(db) -> int:
    n = db.query(Event).filter(Event.source == "demo").delete()
    db.commit()
    return n


def generate(customers: int = 600, days: int = 14, seed: int = 42) -> int:
    """Replace all demo data with `customers` pretend visitors. Returns events added."""
    init_db()
    db = SessionLocal()
    try:
        clear_demo(db)
        rng     = random.Random(seed)
        bad_day = (datetime.utcnow() - timedelta(days=min(4, days - 1))).date()
        rows    = []
        for _ in range(customers):
            rows.extend(one_customer(rng, days, bad_day))
        db.add_all(rows)
        db.commit()
        return len(rows)
    finally:
        db.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--customers", type=int, default=600, help="how many pretend customers (default 600)")
    ap.add_argument("--days", type=int, default=14, help="spread over this many past days (default 14)")
    ap.add_argument("--seed", type=int, default=42, help="same seed = same data every run")
    ap.add_argument("--clear", action="store_true", help="only remove demo data")
    args = ap.parse_args()

    if args.clear:
        init_db()
        db = SessionLocal()
        try:
            print(f"Removed {clear_demo(db)} demo events.")
        finally:
            db.close()
        return

    added = generate(args.customers, args.days, args.seed)
    db = SessionLocal()
    try:
        live = db.query(Event).filter(Event.source == "live").count()
    finally:
        db.close()
    print(f"Added {added} demo events from {args.customers} pretend customers.")
    print(f"Real (live) events untouched: {live}.")
    print("Open http://127.0.0.1:8000/insights.html and switch to DEMO to see them.")


if __name__ == "__main__":
    main()
