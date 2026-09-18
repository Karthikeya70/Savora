"""
Support Agent — handles out-of-scope questions.

For anything the bot cannot answer (hours, location, delivery, complaints),
it gives a warm apology and directs the customer to contact the restaurant.

Future: wire up to a reservations API, live delivery tracker, FAQ database.
"""
from .llm_client import ask_llm

SUPPORT_PROMPT = """\
You are Savora's support assistant. A customer has asked something outside
the menu — such as opening hours, location, delivery options, reservations,
parking, WiFi, or a complaint.

You do NOT have this information. Apologise briefly, acknowledge what they asked,
and tell them to contact the restaurant directly. Be warm, not robotic.

RULES:
• 1–2 sentences only.
• Never make up hours, phone numbers, or addresses.
• End with a suggestion to contact Savora directly (phone, in-person, or email).
"""


def handle_support(question: str, history: list[dict] | None = None) -> dict:
    answer = ask_llm(SUPPORT_PROMPT, question, history=history, max_tokens=120)
    return {
        "answer": answer,
        "used_llm": True,
        "filters_applied": [],
        "dish_names": [],
        "agent": "support",
    }
