"""
Orchestrator — routes each customer message to the right sub-agent.

Makes a single cheap LLM call (max 10 tokens) to classify intent:
  "menu"    — menu questions, dish info, filters, recommendations
  "order"   — cart actions, placing/confirming orders
  "support" — out-of-scope (hours, location, delivery, complaints)

Falls back to "menu" on any error (safest default — the menu agent
handles unknown queries gracefully).
"""
import json
import os

from .llm_client import _post

ORCHESTRATOR_PROMPT = """\
You are a routing agent for Savora, an Indian restaurant chatbot.
Classify the customer's message and decide which sub-agent handles it.

AGENTS:
"menu"    — anything about the menu: dish questions, dietary info, allergens,
            ingredients, price, spice level, recommendations, comparisons,
            pairings, "what do you have", filter queries (vegan/gluten-free/under ₹150),
            calorie info, customisation questions without ordering intent
"order"   — anything about ordering or the cart: "add", "remove", "I'll have",
            "I'll take", "give me", "can I order", "place order", "checkout",
            "confirm", "view cart", "what's in my cart", "update quantity",
            "bring me", "I want to order"
"support" — clearly out of scope: opening hours, location, reservations,
            delivery, parking, WiFi, complaints, contact info

IMPORTANT: Use conversation history ONLY to resolve context-dependent messages
like "add 2 of those" or "I'll take the second one" — look at what was
discussed and route to "order".

Return ONLY valid JSON. No explanation. No markdown. No extra text.
Example: {"agent": "menu"}
"""


def route(question: str, history: list[dict] | None = None) -> str:
    """Classify question and return 'menu', 'order', or 'support'."""
    if not os.environ.get("OPENROUTER_API_KEY"):
        return "menu"

    # Build a compact context from the last 2 turns so the orchestrator
    # can resolve pronouns like "add 2 of those".
    context_lines = []
    for turn in (history or [])[-2:]:
        role = turn.get("role", "")
        content = (turn.get("content") or "")[:120]
        if role in ("user", "assistant") and content:
            context_lines.append(f"{role}: {content}")

    user_message = "\n".join(context_lines + [f"customer: {question}"])

    messages = [
        {"role": "system", "content": ORCHESTRATOR_PROMPT},
        {"role": "user", "content": user_message},
    ]
    data, err = _post(messages, max_tokens=12)
    if err:
        return "menu"

    try:
        raw = data["choices"][0]["message"]["content"].strip()
        agent = json.loads(raw).get("agent", "menu")
        if agent in ("menu", "order", "support"):
            return agent
    except (KeyError, IndexError, json.JSONDecodeError, AttributeError):
        pass

    return "menu"
