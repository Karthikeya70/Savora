"""
Customer journey tracking.

Every step a customer takes is written to the `events` table:
question -> dishes suggested -> added to cart -> order placed -> dish rated.

Because every row carries the same session_id, the steps can be joined later
to answer questions like "did people who were suggested a dish actually order it?"
and "what % of people who ordered this dish liked it?".

Tracking must never break the customer's experience, so every write is wrapped:
if recording fails, it is logged and the request carries on normally.
"""
import logging
import re

from .database import Event, SessionLocal

logger = logging.getLogger("savora.events")


# ── writing ───────────────────────────────────────────────────────────────────

def record(session_id: str, event_type: str, dish_name: str | None = None,
           source: str = "live", **properties) -> None:
    record_many([{
        "session_id": session_id,
        "event_type": event_type,
        "dish_name":  dish_name,
        "properties": properties,
        "source":     source,
    }])


def record_many(rows: list[dict]) -> None:
    if not rows:
        return
    db = SessionLocal()
    try:
        for r in rows:
            db.add(Event(
                session_id=r["session_id"],
                event_type=r["event_type"],
                dish_name=r.get("dish_name"),
                properties=r.get("properties") or {},
                source=r.get("source", "live"),
            ))
        db.commit()
    except Exception as e:  # tracking must never take the app down
        db.rollback()
        logger.warning("Could not record %d event(s): %s", len(rows), e)
    finally:
        db.close()


def was_suggested(session_id: str, dish_name: str) -> bool:
    """True if the assistant named this dish to this customer earlier in the visit."""
    db = SessionLocal()
    try:
        return db.query(Event.id).filter(
            Event.session_id == session_id,
            Event.event_type == "dish_suggested",
            Event.dish_name == dish_name,
        ).first() is not None
    except Exception as e:
        logger.warning("Suggestion lookup failed: %s", e)
        return False
    finally:
        db.close()


# ── which dishes did the answer mention? ──────────────────────────────────────

def dishes_mentioned(answer: str, dishes: list[dict]) -> list[str]:
    """
    Menu dishes named in the assistant's answer, in the order they appear.

    Longer names are matched first and blanked out, so "Butter Naan" is not
    also counted as a mention of a shorter name contained inside it.
    """
    text = (answer or "").lower()
    found: list[tuple[int, str]] = []
    names = sorted((d.get("name") or "" for d in dishes), key=len, reverse=True)
    for name in names:
        if not name:
            continue
        pattern = r"(?<![a-z])" + re.escape(name.lower()) + r"(?![a-z])"
        m = re.search(pattern, text)
        if m:
            found.append((m.start(), name))
            text = text[:m.start()] + " " * len(m.group(0)) + text[m.end():]
    return [name for _, name in sorted(found)]


# ── what is the question about? ───────────────────────────────────────────────

# Checked top to bottom; the first topic that matches wins. Safety topics come
# first on purpose: "is the vegan curry spicy" is primarily a diet question.
TOPIC_RULES: list[tuple[str, str]] = [
    ("allergy_or_diet", r"allerg|\bnuts?\b|peanut|cashew|almond|gluten|wheat|dairy|lactose|"
                        r"\beggs?\b|eggless|vegan|vegetarian|\bveg\b|non.?veg|jain|halal|"
                        r"diabet|sugar.?free|\bsafe\b|intoleran|celiac|coeliac|soy|sesame"),
    ("ingredients",     r"ingredient|contain|made (?:with|of|from)|what.?s in|\binside\b|"
                        r"onion|garlic|\boil\b|butter|ghee|cream|cheese|paneer|meat|chicken|"
                        r"calorie|protein|healthy|fried"),
    ("budget",          r"\bunder\b|cheap|budget|price|cost|₹|\brs\.?\b|rupee|afford|"
                        r"expensive|how much|value"),
    ("spice",           r"spic|\bhot\b|\bmild\b|chilli|chili|heat"),
    ("recommendation",  r"recommend|suggest|\bbest\b|popular|favou?rite|good|should i|"
                        r"what to (?:get|order|eat)|\btry\b|confus|decide|special|pair|go with"),
]

TOPIC_LABELS = {
    "allergy_or_diet": "Allergies & diet",
    "ingredients":     "Ingredients",
    "budget":          "Price & budget",
    "spice":           "Spice level",
    "recommendation":  "Help me choose",
    "ordering":        "Ordering",
    "other":           "Other",
}


def question_topic(question: str, dishes: list[dict], agent: str | None = None) -> str:
    """Sort a customer question into one plain-English topic."""
    if agent == "order":
        return "ordering"
    q = (question or "").lower()
    # Remove dish names first, so "tell me about Veg Samosa" isn't mistaken
    # for a vegetarian-diet question just because the name contains "veg".
    for d in sorted(dishes, key=lambda d: len(d.get("name") or ""), reverse=True):
        name = (d.get("name") or "").lower()
        if name:
            q = q.replace(name, " ")
    for topic, pattern in TOPIC_RULES:
        if re.search(pattern, q):
            return topic
    return "other"
