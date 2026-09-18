"""
Routes every question through semantic retrieval + LLM.

Flow:
  1. Cache check         — free, ~5 ms, stateless queries only
  2. Semantic retrieval  — embed question, pull top-k dishes from local index (~1 ms, no API cost)
  3. LLM call            — dishes injected as context; tools available for anything missing
"""
import re
import time

from . import cache, embeddings, experiment, popularity
from .llm_client import ask_llm_with_tools
from .query_log import log_query
from .tools import build_tools

# ── system prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are Savora, a warm and knowledgeable food guide at an Indian restaurant. \
You help customers understand the menu and choose dishes they'll genuinely enjoy — \
based on taste, dietary needs, allergies, budget, or mood.

VOICE: Conversational and enthusiastic, like a food-lover friend who knows every \
dish on this menu. When you recommend something, say WHY it's worth trying — \
flavour, texture, popularity, value — not just its name. Never be robotic or list-heavy.

RESPONSE LENGTH:
• Factual lookups (price, allergens, ingredients): 1–2 sentences, direct and precise.
• Recommendations / comparisons: 2–4 sentences; name 2–3 dishes with a brief reason each.
• Filter queries (vegan dishes, under ₹150, nut-free): list all matches concisely \
  with name, price, and one-line description. If more than 5, show the best 4–5 and \
  mention how many more exist.
• Zero results: Acknowledge warmly, suggest an alternative or ask a clarifying question.
• Something not on the menu ("do you have sushi?"): Acknowledge honestly and pivot \
  to the closest thing we do have.
• Restaurant operations (hours, location, reservations, delivery, parking, WiFi): \
  Say you only know the menu and can't answer those — keep it to one sentence and \
  suggest the customer contact the restaurant directly.

ALLERGEN SAFETY: For any allergy question, be precise and always add: \
"Please confirm with our kitchen if you have a severe allergy." Never guess.

TOOL USE RULES — follow these strictly:
• For filter queries ("vegan dishes", "nut-free options", "under ₹150", "spicy dishes", \
  "vegetarian options"): ALWAYS call search_dishes first. Do NOT answer from the context \
  alone — the injected context is only a relevance sample and may miss items.
• For a specific named dish ("tell me about Masala Dosa", "is Pani Puri vegan?"): \
  use the injected context first; call get_dish_details only if the context is missing data.
• For history references ("the first dish you mentioned", "does it have nuts?"): \
  resolve from conversation history, THEN look up that dish's details if needed.
• For recommendations, comparisons, mood queries: answer from the injected context; \
  call search_dishes only if you need a broader set.

GUEST FEEDBACK — read this carefully. Every dish carries a "Guest feedback" line.
• If it gives numbers, you may quote those exact numbers when they help someone decide. Never round, estimate, or embellish them.
• If it says "no guest ratings yet", you must say NOTHING about what guests, customers, diners or people thought of that dish. Not "popular with guests", not "well rated", not "most people love it", not even vaguely. Describe the dish itself instead — taste, texture, ingredients, spice, value.
• A BESTSELLER badge is the restaurant's own label, not guest feedback. Never turn it into a claim about what guests said or rated.

NEVER invent dishes, prices, ingredients, or allergens. Everything must come from \
the menu data or tool results. If you don't know, say so.

FORMATTING: When you mention a dish name, always wrap it in **double asterisks** so it \
renders bold (e.g. **Pani Puri**, **Kadai Paneer**). Use plain prose otherwise — no \
numbered lists unless comparing more than three options.\
"""


# ── helpers ───────────────────────────────────────────────────────────────────

def _build_context_block(dishes: list[dict], stats: dict | None = None) -> str:
    lines = []
    for d in dishes:
        name  = d.get("name", "")
        cat   = d.get("category", "")
        price = f"₹{d['price_inr']}" if d.get("price_inr") is not None else "N/A"
        badges = ", ".join(d.get("badges", []))
        tags   = ", ".join(d.get("dietary_tags", []))
        spice  = d.get("spice", "")
        desc   = (d.get("description") or "")[:120].rstrip()
        allergens = ", ".join(d.get("allergens_contains", [])) or "none declared"
        customisations = "; ".join(
            c.get("customisation", "") for c in (d.get("customisations") or []) if c.get("allowed")
        )

        line = f"• {name} ({cat}, {price})"
        if badges:
            line += f" [{badges}]"
        if tags:
            line += f"\n  Dietary: {tags}"
        if spice:
            line += f" | Spice: {spice}"
        if desc:
            line += f"\n  {desc}"
        if allergens != "none declared":
            line += f"\n  Allergens: {allergens}"
        if customisations:
            line += f"\n  Can customise: {customisations}"
        line += f"\n  Guest feedback: {popularity.describe(name, stats)}"
        lines.append(line)
    return "\n".join(lines)


def _check_for_hallucinated_dishes(answer: str, dishes: list[dict]) -> list[str]:
    real_names = {d.get("name", "").lower() for d in dishes}
    candidates = re.findall(r"\b(?:[A-Z][a-z]+(?:\s+(?:[A-Z][a-z]+|&))*)\b", answer)
    suspicious = []
    for phrase in candidates:
        if len(phrase.split()) < 2:
            continue
        low = phrase.lower()
        if low in real_names:
            continue
        if any(low in n or n in low for n in real_names):
            continue
        suspicious.append(phrase)
    return suspicious


# ── main entry point ──────────────────────────────────────────────────────────

def answer_question(
    question: str,
    menu: dict,
    dish_index=None,
    history: list[dict] | None = None,
    group: str = "A",
) -> dict:
    start  = time.perf_counter()
    dishes = menu.get("dishes", [])

    # ── Tier 1: Cache ─────────────────────────────────────────────────────────
    # Only cache stateless queries (no conversation history) so cached answers
    # never bleed into a different conversation context.
    if not history:
        cached = cache.get(question, group)
        if cached is not None:
            log_query(question, "cache", (time.perf_counter() - start) * 1000)
            return cached

    # ── Tier 2: Semantic retrieval + LLM ─────────────────────────────────────
    # Embed the question, pull the most relevant dishes locally (~1 ms), inject
    # them as context so the LLM can answer in one focused call. Tools are
    # available for anything not covered by the retrieved context.
    retrieved: list[dict] = []
    if dish_index is not None:
        query_vec = embeddings.embed(question)
        retrieved = dish_index.top_k(query_vec, k=7)

    context_block    = _build_context_block(retrieved, popularity.snapshot())
    augmented_system = (
        SYSTEM_PROMPT
        + "\n\n---\nRELEVANT MENU ITEMS (answer from these first):\n"
        + context_block
        + "\n---"
        + experiment.extra_prompt(group)
    )

    seen_dishes: list[str] = []
    tools, dispatch = build_tools(dishes, record=seen_dishes)
    recent_history  = (history or [])[-6:]

    answer, calls_made = ask_llm_with_tools(
        augmented_system, question, tools, dispatch, history=recent_history
    )

    suspicious     = _check_for_hallucinated_dishes(answer, dishes)
    retrieved_names = [d.get("name") for d in retrieved]
    dish_names     = list(dict.fromkeys(n for n in retrieved_names + seen_dishes if n))

    result = {
        "answer":          answer,
        "used_llm":        True,
        "filters_applied": [],
        "dish_names":      dish_names,
        "agent":           "menu",
    }

    log_query(question, "llm", (time.perf_counter() - start) * 1000, {
        "tool_calls":         calls_made,
        "suspicious_mentions": suspicious,
        "retrieved_context":  retrieved_names,
    })

    if not history:
        cache.set(question, result, group)

    return result
