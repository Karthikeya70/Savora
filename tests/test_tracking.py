"""
Tests for customer tracking, ratings and the insights numbers.

These never call the AI and use a throwaway database file, so they are free,
fast, and safe to run any time:

    python tests/test_tracking.py
"""
import os
import sys
import tempfile
from pathlib import Path

# Point the app at a brand-new temporary database BEFORE any backend import,
# so tests can never touch real data. load_dotenv won't override these.
_TMP = tempfile.mkdtemp(prefix="savora_test_")
os.environ["DATABASE_URL"]     = f"sqlite:///{Path(_TMP, 'test.db').as_posix()}"
os.environ["DASHBOARD_SECRET"] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import cart as cart_ops, events, insights, popularity  # noqa: E402
from backend.data import load_menu                                 # noqa: E402
from backend.database import Base, Event, SessionLocal, engine     # noqa: E402

DISHES = load_menu()["dishes"]
PRICE  = {d["name"]: float(d["price_inr"]) for d in DISHES}
BY_NAME = {d["name"]: d for d in DISHES}


def fresh_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def all_events(event_type=None):
    db = SessionLocal()
    try:
        q = db.query(Event)
        if event_type:
            q = q.filter(Event.event_type == event_type)
        return q.order_by(Event.id).all()
    finally:
        db.close()


def add(session, dish, qty=1):
    db = SessionLocal()
    try:
        cart_ops.add_item(db, session, dish, PRICE[dish], qty, {})
    finally:
        db.close()


def suggest(session, *dishes):
    events.record_many([
        {"session_id": session, "event_type": "dish_suggested", "dish_name": d}
        for d in dishes
    ])


# ── topic sorting ─────────────────────────────────────────────────────────────

def test_topics():
    cases = {
        "Is the Veg Samosa safe for someone with a nut allergy?": "allergy_or_diet",
        "Which desserts are eggless?":                             "allergy_or_diet",
        "What vegan options do you have?":                         "allergy_or_diet",
        "Does the Pav Bhaji have onion or garlic?":                "ingredients",
        "Anything under 150 rupees?":                              "budget",
        "How spicy is it?":                                        "spice",
        "What do you recommend for a first date?":                 "recommendation",
        "Tell me about the Veg Samosa":                            "other",  # "veg" is part of the name
        "What are your opening hours?":                            "other",
    }
    for question, expected in cases.items():
        got = events.question_topic(question, DISHES)
        assert got == expected, f"{question!r}: expected {expected}, got {got}"
    assert events.question_topic("add two of those", DISHES, agent="order") == "ordering"


# ── which dishes did an answer name? ──────────────────────────────────────────

def test_dishes_mentioned():
    answer = ("Try the **Butter Naan** with **Dal Makhani**, or go lighter with "
              "**Masala Dosa**. The **Plain Sada Dosa** is great too.")
    names = events.dishes_mentioned(answer, DISHES)
    assert names == ["Butter Naan", "Dal Makhani", "Masala Dosa", "Plain Sada Dosa"], names
    # "Garlic Naan" must not be found just because the answer says "naan".
    assert "Garlic Naan" not in events.dishes_mentioned("We have naan.", DISHES)
    assert events.dishes_mentioned("Sorry, we don't serve sushi.", DISHES) == []


# ── cart tracking ─────────────────────────────────────────────────────────────

def test_cart_events_mark_suggested_dishes():
    fresh_db()
    suggest("s1", "Pani Puri")
    add("s1", "Pani Puri")            # suggested earlier
    add("s1", "Masala Chai")          # never suggested
    add("s1", "Pani Puri", qty=2)     # same dish again: merges, +2

    added = [(e.dish_name, e.properties["quantity"], e.properties["was_suggested"])
             for e in all_events("cart_added")]
    assert added == [
        ("Pani Puri", 1, True),
        ("Masala Chai", 1, False),
        ("Pani Puri", 2, True),
    ], added


def test_remove_and_checkout():
    fresh_db()
    suggest("s2", "Veg Samosa")
    add("s2", "Veg Samosa", qty=3)
    add("s2", "Masala Chai")

    db = SessionLocal()
    try:
        cart_ops.update_quantity(db, "s2", "Veg Samosa", 1)   # 3 -> 1
        cart_ops.remove_item(db, "s2", "Masala Chai")
        order = cart_ops.checkout(db, "s2", customer_name="Test")
        order_id = order.id
    finally:
        db.close()

    removed = [(e.dish_name, e.properties["quantity"]) for e in all_events("cart_removed")]
    assert removed == [("Veg Samosa", 2), ("Masala Chai", 1)], removed

    placed = all_events("order_placed")
    assert len(placed) == 1
    assert placed[0].properties["order_id"] == order_id
    assert placed[0].properties["items"] == [
        {"dish_name": "Veg Samosa", "quantity": 1, "was_suggested": True}
    ]
    # Checkout empties the cart, but that must not look like the customer removed things.
    assert len(all_events("cart_removed")) == 2


# ── insights numbers ──────────────────────────────────────────────────────────

def test_insights_numbers():
    fresh_db()
    q = lambda s, topic: events.record(s, "question_asked", topic=topic,
                                       handled_by="menu", dishes_named=1, response_ms=300)

    # Customer A: allergy question, suggested Pani Puri, orders it, likes it.
    q("A", "allergy_or_diet"); suggest("A", "Pani Puri"); add("A", "Pani Puri")
    # Customer B: budget question, suggested Pani Puri, orders something else, dislikes it.
    q("B", "budget"); suggest("B", "Pani Puri"); add("B", "Masala Chai")
    # Customer C: asks, suggested nothing, leaves.
    events.record("C", "question_asked", topic="other", handled_by="menu",
                  dishes_named=0, response_ms=200, question="Do you have sushi?")

    db = SessionLocal()
    try:
        for s in ("A", "B"):
            cart_ops.checkout(db, s)
    finally:
        db.close()
    events.record("A", "dish_rated", dish_name="Pani Puri",   liked=True,  was_suggested=True)
    events.record("B", "dish_rated", dish_name="Masala Chai", liked=False, was_suggested=False)

    db = SessionLocal()
    try:
        out = insights.build(db, DISHES, source="live")
    finally:
        db.close()

    h = out["headline"]
    assert h["customers"] == 3 and h["questions"] == 3 and h["orders"] == 2
    assert h["order_rate"] == round(2 / 3, 4)
    assert h["orders_using_suggestion"] == 1 and h["suggestion_share"] == 0.5
    assert h["like_rate"] == 0.5

    steps = {f["step"]: f["customers"] for f in out["funnel"]}
    assert steps == {"asked": 3, "suggested": 2, "carted": 2, "ordered": 2, "rated": 2}, steps

    pani = next(d for d in out["dishes"] if d["dish"] == "Pani Puri")
    assert pani["customers_shown"] == 2
    assert pani["picked_when_suggested"] == 0.5   # A picked it, B didn't
    assert pani["like_rate"] == 1.0 and pani["low_sample"] is True

    assert out["liked_by_path"]["suggested"]["like_rate"] == 1.0
    assert out["liked_by_path"]["not_suggested"]["like_rate"] == 0.0
    assert out["questions_before_order"]["median"] == 1
    assert [x["question"] for x in out["no_dish_questions"]] == ["Do you have sushi?"]

    # Demo data must never leak into real numbers.
    events.record("D", "question_asked", source="demo", topic="budget")
    db = SessionLocal()
    try:
        assert insights.build(db, DISHES, source="live")["headline"]["customers"] == 3
        assert insights.build(db, DISHES, source="demo")["headline"]["customers"] == 1
    finally:
        db.close()


# ── ratings API ───────────────────────────────────────────────────────────────

def test_rating_endpoint():
    from fastapi.testclient import TestClient
    from backend.app import app
    from backend.database import Order

    fresh_db()
    suggest("R", "Pani Puri")
    add("R", "Pani Puri")
    add("R", "Masala Chai")
    db = SessionLocal()
    try:
        order_id = cart_ops.checkout(db, "R").id
    finally:
        db.close()

    client = TestClient(app)  # no "with": skips loading the AI model at startup
    url = f"/api/order/{order_id}/rate"
    body = {"ratings": [{"dish_name": "Pani Puri", "liked": True}]}

    r = client.post(url, json=body)
    assert r.status_code == 400, "rating must wait until the food is ready"

    db = SessionLocal()
    try:
        db.query(Order).filter(Order.id == order_id).update({"status": "completed"})
        db.commit()
    finally:
        db.close()

    r = client.post(url, json={"ratings": [{"dish_name": "Butter Chicken", "liked": True}]})
    assert r.status_code == 400, "can't rate a dish that wasn't ordered"

    r = client.post(url, json=body)
    assert r.status_code == 200 and r.json()["ratings"] == {"Pani Puri": True}, r.text

    # Rating the same dish again is ignored, not double-counted.
    client.post(url, json={"ratings": [{"dish_name": "Pani Puri", "liked": False}]})
    rated = all_events("dish_rated")
    assert len(rated) == 1 and rated[0].properties["was_suggested"] is True

    order = client.get(f"/api/order/{order_id}").json()
    assert order["can_rate"] is True and order["ratings"] == {"Pani Puri": True}

    ins = client.get("/api/insights").json()
    assert ins["headline"]["like_rate"] == 1.0

    assert client.get("/api/insights?source=nope").status_code == 400


# ── guest feedback shown back to customers ────────────────────────────────────

def _rate_dish(session, dish, liked, source="live"):
    events.record(session, "dish_rated", dish_name=dish, source=source,
                  liked=liked, order_id="o-" + session)


def test_popularity_needs_enough_real_ratings():
    fresh_db()
    popularity.reset_cache()

    # Four ratings is below the threshold, so customers are told nothing.
    for i in range(4):
        _rate_dish(f"p{i}", "Pani Puri", True)
    assert popularity.describe("Pani Puri", popularity.snapshot(force=True)) == popularity.NO_FEEDBACK

    # The fifth rating reaches the threshold.
    _rate_dish("p4", "Pani Puri", False)
    line = popularity.describe("Pani Puri", popularity.snapshot(force=True))
    assert line == "4 of 5 guests who rated this liked it", line

    # A dish nobody rated says so explicitly, so the assistant cannot fill the gap.
    assert popularity.describe("Jalebi", popularity.snapshot(force=True)) == popularity.NO_FEEDBACK


def test_demo_ratings_never_reach_customers():
    fresh_db()
    popularity.reset_cache()
    for i in range(20):
        _rate_dish(f"d{i}", "Masala Dosa", True, source="demo")
    assert popularity.describe("Masala Dosa", popularity.snapshot(force=True)) == popularity.NO_FEEDBACK, \
        "invented demo ratings must never be quoted to a real customer"


def test_feedback_appears_in_what_the_assistant_reads():
    from backend.router import _build_context_block

    fresh_db()
    popularity.reset_cache()
    for i in range(6):
        _rate_dish(f"c{i}", "Veg Samosa", i < 5)
    stats = popularity.snapshot(force=True)

    block = _build_context_block([BY_NAME["Veg Samosa"], BY_NAME["Jalebi"]], stats)
    assert "Guest feedback: 5 of 6 guests who rated this liked it" in block, block
    # The unrated dish is explicitly marked as having no ratings.
    assert popularity.NO_FEEDBACK in block, block
    assert block.count("Guest feedback") == 2, block


def test_detects_invented_guest_opinions():
    fresh_db()
    popularity.reset_cache()
    for i in range(6):
        _rate_dish(f"u{i}", "Veg Samosa", True)
    stats = popularity.snapshot(force=True)

    invented = "The **Jalebi** is a bestseller and most guests who rated it really enjoyed it!"
    assert popularity.unsupported_claim(invented, ["Jalebi"], stats) is True

    supported = "5 of 6 guests who rated the **Veg Samosa** liked it."
    assert popularity.unsupported_claim(supported, ["Veg Samosa"], stats) is False

    plain = "The **Jalebi** is crisp, syrupy and best eaten hot."
    assert popularity.unsupported_claim(plain, ["Jalebi"], stats) is False


# ── A/B test ──────────────────────────────────────────────────────────────────

def test_ab_groups_are_stable_and_even():
    import uuid
    from backend import experiment

    ids = [str(uuid.uuid4()) for _ in range(4000)]
    groups = [experiment.group_for(i) for i in ids]
    share_b = groups.count("B") / len(groups)
    assert 0.46 < share_b < 0.54, f"split should be close to 50/50, got {share_b:.1%}"
    # The same visitor must always see the same version.
    assert all(experiment.group_for(i) == g for i, g in zip(ids[:300], groups[:300]))
    # Only group B gets the extra instruction.
    assert experiment.extra_prompt("A") == "" and "3 dishes" in experiment.extra_prompt("B")


def test_cache_keeps_ab_groups_apart():
    """An answer written for group B must never be served to group A."""
    import hashlib
    import numpy as np
    from backend import cache

    def fake_embed(text):  # stands in for the real AI model, so the test stays fast
        seed = int(hashlib.md5(text.lower().encode()).hexdigest()[:8], 16)
        v = np.random.default_rng(seed).normal(size=16)
        return v / np.linalg.norm(v)

    real = cache.embeddings.embed
    cache.embeddings.embed = fake_embed
    try:
        cache._store.clear()
        cache.set("Which dishes are nut-free?", {"answer": "B version"}, group="B")
        assert cache.get("Which dishes are nut-free?", group="B")["answer"] == "B version"
        assert cache.get("Which dishes are nut-free?", group="A") is None
    finally:
        cache.embeddings.embed = real
        cache._store.clear()


# ── the SQL gives the same answers as the dashboard ──────────────────────────

def test_sql_matches_dashboard():
    """
    The insights page (Python) and analysis/questions.sql (SQL) calculate the
    same numbers two different ways. If they ever disagree, one of them is wrong.
    """
    import importlib.util
    import random
    import sqlite3
    from datetime import datetime, timedelta

    root = Path(__file__).resolve().parent.parent

    def load(name, path):
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    demo = load("demo_data", root / "scripts" / "demo_data.py")
    run  = load("analysis_run", root / "analysis" / "run.py")

    fresh_db()
    rng, bad_day = random.Random(7), (datetime.utcnow() - timedelta(days=4)).date()
    db = SessionLocal()
    try:
        for _ in range(200):
            db.add_all(demo.one_customer(rng, 14, bad_day))
        db.commit()
        dash = insights.build(db, DISHES, source="demo")
    finally:
        db.close()

    con = sqlite3.connect(os.environ["DATABASE_URL"].replace("sqlite:///", ""))
    try:
        queries = {q["number"]: q["sql"] for q in run.load_queries()}

        def one_row(n):
            cur = con.execute(queries[n], {"source": "demo"})
            return dict(zip([d[0] for d in cur.description], cur.fetchone()))

        funnel = one_row(2)
        steps  = {f["step"]: f["customers"] for f in dash["funnel"]}
        assert funnel["asked"]            == steps["asked"]
        assert funnel["got_a_suggestion"] == steps["suggested"]
        assert funnel["added_to_cart"]    == steps["carted"]
        assert funnel["ordered"]          == steps["ordered"]
        assert funnel["rated"]            == steps["rated"]

        helped = one_row(4)
        assert helped["orders"]        == dash["headline"]["orders"]
        assert helped["helped_orders"] == dash["headline"]["orders_using_suggestion"]

        # Every query in the file must at least run without an error.
        for n, sql in queries.items():
            con.execute(sql, {"source": "demo"}).fetchall()
    finally:
        con.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS  {name}")
        except Exception as e:
            failed += 1
            print(f"FAIL  {name}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
