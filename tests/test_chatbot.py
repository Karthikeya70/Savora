"""
Savora chatbot test suite.

Run with:  python -m pytest tests/test_chatbot.py -v
Or simply: python tests/test_chatbot.py

Every question now goes through the LLM (no rule-based filter engine).
Tests verify two things:
  1. The answer actually goes through the LLM (used_llm == True)
  2. Key words appear (or don't appear) in the answer

When a new bug is found, add it here so it never comes back.
"""

import sys, os, io
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from backend.router import answer_question
from backend.data import load_menu
from backend.dish_index import DishIndex

# ── setup (runs once) ─────────────────────────────────────────────────────────

menu   = load_menu()
idx    = DishIndex(menu["dishes"])
DISHES = menu["dishes"]

def ask(question, history=None):
    return answer_question(question, menu, dish_index=idx, history=history)

PASS = "PASS"
FAIL = "FAIL"

results = []

def check(description, question, must_contain=(), must_not_contain=(), history=None):
    r      = ask(question, history=history)
    answer = r["answer"].lower()

    failures = []
    if not r["used_llm"]:
        failures.append("expected LLM but got cache/instant")
    for word in must_contain:
        if word.lower() not in answer:
            failures.append(f"answer missing '{word}'")
    for word in must_not_contain:
        if word.lower() in answer:
            failures.append(f"answer should NOT contain '{word}'")

    ok = PASS if not failures else FAIL
    results.append((ok, description, failures, r["answer"][:120].replace("\n", " ")))
    return ok


# ═════════════════════════════════════════════════════════════════════════════
# GROUP 1: Filter queries — LLM applies filters via tools, answers naturally
# ═════════════════════════════════════════════════════════════════════════════

check("vegan filter",
      "What vegan options do you have?",
      must_contain=["vegan"])

check("price filter under",
      "Show me dishes under 150 rupees",
      must_contain=["₹"])

check("price filter over",
      "Dishes above 200 rupees",
      must_contain=["₹"])

check("nut-free filter",
      "I need nut-free dishes",
      must_contain=["nut"])

check("spicy filter",
      "What are the spiciest dishes?")

check("mild filter",
      "Show me mild options")

check("dairy-free filter",
      "Any dairy-free options?",
      must_contain=["dairy"])

check("gluten-free filter",
      "Which dishes are gluten-free?")

check("vegetarian filter",
      "What vegetarian options do you have?")

check("non-veg filter",
      "Show me non-vegetarian dishes")

check("multiple filters: vegan + price",
      "What vegan dishes are under 150 rupees?",
      must_contain=["vegan"])

check("multiple filters: mild + vegan",
      "Mild vegan dishes")


# ═════════════════════════════════════════════════════════════════════════════
# GROUP 2: Single dish questions
# ═════════════════════════════════════════════════════════════════════════════

check("dish overview: tell me about",
      "Tell me about the Masala Dosa",
      must_contain=["masala dosa"])

check("dish overview: describe",
      "Describe the Pani Puri",
      must_contain=["pani puri"])

check("dish spice level",
      "How spicy is the Pani Puri?",
      must_contain=["pani puri"])

check("dish price",
      "How much is the Masala Dosa?",
      must_contain=["₹"])

check("dish ingredients: what's in",
      "What's in the Veg Samosa?",
      must_contain=["samosa"])

check("dish ingredients: made of",
      "What is the Masala Dosa made of?",
      must_contain=["masala dosa"])

check("dish customisation",
      "Can I customise the Masala Dosa?",
      must_contain=["masala dosa"])

check("dish by alias name",
      "Is golgappa spicy?",
      must_contain=["pani puri"])


# ═════════════════════════════════════════════════════════════════════════════
# GROUP 3: Allergen / diet yes-no for specific dishes
# ═════════════════════════════════════════════════════════════════════════════

check("allergen: is it gluten-free",
      "Is the Veg Samosa gluten-free?",
      must_contain=["gluten"])

check("allergen: does it contain dairy",
      "Does the Masala Dosa contain dairy?",
      must_contain=["dairy"])

check("allergen: does it have peanuts",
      "Does the Pani Puri have peanuts?")

check("allergen: safe for nut allergy",
      "Is the Veg Samosa safe for someone with a nut allergy?",
      must_contain=["nut"])

check("allergen: safe for dairy allergy",
      "Is the Masala Dosa safe for someone with a dairy allergy?",
      must_contain=["masala dosa"])

check("allergen: does it contain eggs",
      "Does the Veg Dum Biryani contain eggs?",
      must_contain=["egg"])

check("diet tag yes/no: is it vegan",
      "Is the Pani Puri vegan?",
      must_contain=["pani puri"])

check("diet tag yes/no: is it vegetarian",
      "Is the Masala Dosa vegetarian?",
      must_contain=["masala dosa"])


# ═════════════════════════════════════════════════════════════════════════════
# GROUP 4: Complex queries — recommendation, comparison, mood, out-of-scope
# ═════════════════════════════════════════════════════════════════════════════

check("pairing question",
      "What goes well with the Masala Dosa?",
      must_contain=["masala dosa"])

check("comparison: which is better",
      "Which is better, the Pani Puri or the Samosa?")

check("negated diet: not vegetarian",
      "I am not vegetarian, what do you recommend?",
      must_not_contain=["i'm sorry", "cannot"])

check("negated diet: not a vegan",
      "I'm not a vegan, suggest something")

check("taste preference / similarity",
      "My friend loves butter chicken but is vegetarian")

check("history reference: first dish you mentioned",
      "Does the first dish you mentioned have nuts?",
      must_contain=["masala dosa"],
      history=[{"role": "user", "content": "What do you recommend?"},
               {"role": "assistant", "content": "I'd recommend the Masala Dosa! It's a South Indian classic.", "dish_names": ["Masala Dosa"]}])

check("pronoun resolution after single dish",
      "Does it have gluten?",
      must_contain=["masala dosa"],
      history=[{"role": "assistant", "content": "Try the Masala Dosa!", "dish_names": ["Masala Dosa"]}])

check("mood / occasion question",
      "What's good for a first date?")

check("superlative: most expensive",
      "What is the most expensive dish?",
      must_contain=["₹"])

check("superlative: cheapest",
      "What is the cheapest dish on the menu?",
      must_contain=["₹"])

check("superlative: highest calorie",
      "Which dish has the most calories?")

check("out of scope: opening hours",
      "What are your opening hours?",
      must_not_contain=["9am", "10am", "11am", "6pm", "7pm", "8pm", "9pm"])

check("out of scope: location",
      "Where are you located?",
      must_not_contain=["123", "street", "road", "avenue"])

check("out of scope: delivery",
      "Do you do home delivery?")

check("health question: good for diabetics",
      "Do you have anything good for diabetics?")

check("vague / open-ended",
      "What do you recommend?")

check("not on the menu",
      "Do you have sushi?",
      must_not_contain=["yes"])


# ═════════════════════════════════════════════════════════════════════════════
# RESULTS
# ═════════════════════════════════════════════════════════════════════════════

passed = sum(1 for ok, *_ in results if ok == PASS)
failed = sum(1 for ok, *_ in results if ok == FAIL)
total  = len(results)

print(f"\n{'='*72}")
print(f"SAVORA CHATBOT TEST SUITE   {passed}/{total} passed\n")

if failed:
    print("── FAILURES ─────────────────────────────────────────────────────────")
    for ok, desc, failures, answer in results:
        if ok == FAIL:
            print(f"\n  FAIL  {desc}")
            for f in failures:
                print(f"        ✗ {f}")
            print(f"        answer: {answer}")

print("\n── ALL RESULTS ──────────────────────────────────────────────────────")
for ok, desc, failures, answer in results:
    mark = "✓" if ok == PASS else "✗"
    print(f"  {mark}  {desc}")

print(f"\n{'='*72}")
print(f"{'ALL PASS' if failed == 0 else str(failed) + ' FAILED'}  ({passed}/{total})")

if failed > 0:
    sys.exit(1)
