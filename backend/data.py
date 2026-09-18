"""
Loads a restaurant menu dataset.

The only contract a menu JSON must satisfy to work with this whole backend is:
{
  "restaurant": "<name>",
  "dishes": [
     { "name": ..., "category": ..., "price_inr": ..., "dietary_tags": [...],
       "allergens_contains": [...], "allergens_may_contain": [...],
       "spice": "...", "approx_calories_kcal": ..., "ingredients": [...],
       "customisations": [...], "description": ... }, ...
  ]
}
Every field is read defensively (missing fields just degrade that field's
usefulness) so a thinner menu dataset from a different restaurant still works.
"""
import json
import re
from pathlib import Path

DATASET_PATH = Path(__file__).parent.parent / "savora_menu_dataset.json"


def load_menu(path: Path = DATASET_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("dishes", [])
    return data


def all_dietary_tags(dishes: list[dict]) -> set[str]:
    return {t for d in dishes for t in d.get("dietary_tags", [])}


def all_allergens(dishes: list[dict]) -> set[str]:
    out = set()
    for d in dishes:
        out.update(d.get("allergens_contains", []))
        out.update(d.get("allergens_may_contain", []))
    return {a for a in out if a and a != "none declared"}


def all_categories(dishes: list[dict]) -> set[str]:
    return {d.get("category", "") for d in dishes if d.get("category")}


# Generic English connector/descriptor words that occasionally show up inside an
# ingredient's own name (e.g. "Cabbage-carrot balls (with flour)", "Spicy mayo")
# but aren't themselves an ingredient someone would search for. Plain English
# stopwords, not tied to any specific restaurant's dishes.
_INGREDIENT_STOPWORDS = {
    "with", "and", "from", "made", "fresh", "served", "topped", "mixed", "whole",
    "fried", "cooked", "boiled", "steamed", "roasted", "sauce", "spicy", "mild",
    "medium", "spice", "that", "this", "your", "into", "over", "some", "extra",
}


def ingredient_keywords(dishes: list[dict]) -> set[str]:
    """Words worth matching as an ingredient/dish-content search term (e.g. "paneer",
    "chicken", "mushroom"). Built entirely from this menu's own ingredient names and
    dish names, so it works for any restaurant without a hardcoded ingredient list.

    Words that show up in almost every dish (oil, salt, water, sauce...) are dropped
    automatically because they don't help distinguish one dish from another - no
    hand-written stopword list needed."""
    doc_count: dict[str, int] = {}
    for d in dishes:
        words_in_dish = set()
        for ing in d.get("ingredients", []):
            words_in_dish.update(re.findall(r"[a-z]{4,}", ing.get("ingredient", "").lower()))
        words_in_dish.update(re.findall(r"[a-z]{4,}", d.get("name", "").lower()))
        for w in words_in_dish:
            doc_count[w] = doc_count.get(w, 0) + 1

    n = len(dishes) or 1
    return {w for w, c in doc_count.items() if c / n <= 0.5} - _INGREDIENT_STOPWORDS


def preparation_keywords(dishes: list[dict]) -> set[str]:
    """Words worth matching as a cooking-method search term (e.g. "fried", "steamed",
    "grilled"), built from this menu's own preparation_method text - so "not fried"
    or "steamed only" work without hardcoding a fixed list of cooking techniques."""
    doc_count: dict[str, int] = {}
    for d in dishes:
        words = set(re.findall(r"[a-z]{4,}", (d.get("preparation_method") or "").lower()))
        for w in words:
            doc_count[w] = doc_count.get(w, 0) + 1

    n = len(dishes) or 1
    return {w for w, c in doc_count.items() if c / n <= 0.6}
