"""
Tool functions the LLM can call instead of us dumping a guessed list of dishes
into the prompt. Works on any menu that follows the schema in data.py - no
Savora-specific logic here, just generic filtering over whatever fields exist.
"""
def _dish_allergens(dish: dict) -> set[str]:
    return (
        {a.lower() for a in dish.get("allergens_contains", [])}
        | {a.lower() for a in dish.get("allergens_may_contain", [])}
    )


def _condensed(d: dict) -> dict:
    return {
        "name": d.get("name"),
        "category": d.get("category"),
        "price_inr": d.get("price_inr"),
        "calories_kcal": d.get("approx_calories_kcal"),
        "spice": d.get("spice"),
        "dietary_tags": d.get("dietary_tags", []),
        "allergens_contains": d.get("allergens_contains", []),
        "description": (d.get("description") or "")[:150],
    }


def build_tools(dishes: list[dict], record: list | None = None):
    """Returns (tool_schemas, dispatch) where dispatch maps a tool name to a
    callable(**args) -> JSON-serialisable result, both scoped to this menu's dishes.
    If `record` (a list) is passed, every dish name returned by a tool call gets
    appended to it - lets the caller know which dishes the model actually looked at."""

    def _remember(names: list[str]):
        if record is not None:
            record.extend(names)

    def _spice_level(d: dict) -> int:
        import re
        m = re.search(r"level\s*(\d)/", d.get("spice") or "")
        return int(m.group(1)) if m else 0

    def search_dishes(category: str | None = None, diet_tag: str | None = None,
                       allergen_free: list | None = None, allergen_contains: list | None = None,
                       max_price: float | None = None, min_price: float | None = None,
                       max_calories: float | None = None, min_calories: float | None = None,
                       tag_contains: str | None = None,
                       spice: str | None = None) -> list:
        results = dishes
        if category:
            results = [d for d in results if category.lower() in (d.get("category") or "").lower()]
        if diet_tag:
            results = [d for d in results if any(diet_tag.lower() in t.lower() for t in d.get("dietary_tags", []))]
        if tag_contains:
            results = [d for d in results if any(tag_contains.lower() in t.lower() for t in d.get("dietary_tags", []))]
        if allergen_free:
            free_set = {a.lower() for a in allergen_free}
            results = [d for d in results if not (_dish_allergens(d) & free_set)]
        if allergen_contains:
            has_set = {a.lower() for a in allergen_contains}
            results = [d for d in results if _dish_allergens(d) & has_set]
        if max_price is not None:
            results = [d for d in results if (d.get("price_inr") or 0) <= max_price]
        if min_price is not None:
            results = [d for d in results if (d.get("price_inr") or 0) >= min_price]
        if max_calories is not None:
            results = [d for d in results if (d.get("approx_calories_kcal") or 0) <= max_calories]
        if min_calories is not None:
            results = [d for d in results if (d.get("approx_calories_kcal") or 0) >= min_calories]
        if spice:
            s = spice.lower()
            if s in ("mild", "1"):
                results = [d for d in results if _spice_level(d) == 1]
            elif s in ("medium", "2"):
                results = [d for d in results if _spice_level(d) == 2]
            elif s in ("spicy", "hot", "3"):
                results = [d for d in results if _spice_level(d) >= 3]
            elif s in ("very spicy", "very hot", "extra spicy", "4"):
                results = [d for d in results if _spice_level(d) >= 4]
        results = results[:30]
        _remember([d.get("name") for d in results])
        return [_condensed(d) for d in results]

    def get_dish_details(name: str) -> dict:
        for d in dishes:
            if d.get("name", "").lower() == name.lower():
                _remember([d.get("name")])
                return d
        # loose fallback match
        for d in dishes:
            if name.lower() in d.get("name", "").lower():
                _remember([d.get("name")])
                return d
        return {"error": f"No dish named '{name}' found in the menu."}

    # Ground the model in this menu's *actual* categories/tags instead of letting
    # it guess plausible-sounding ones ("light", "healthy") that don't exist in
    # the data and would silently return zero results.
    real_categories = sorted({d.get("category") for d in dishes if d.get("category")})
    real_tags = sorted({t for d in dishes for t in d.get("dietary_tags", [])})

    schemas = [
        {
            "type": "function",
            "function": {
                "name": "search_dishes",
                "description": (
                    "Search the restaurant menu by category, diet, allergens, price, or dietary tag. "
                    "Use this instead of guessing - it returns only real dishes that match. For vague, "
                    "mood-based requests ('something light', 'not too heavy/oily', 'healthy'), prefer "
                    "tag_contains with one of this menu's real dietary tags over guessing a price range."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "category": {"type": "string", "description": f"One of this menu's real categories: {', '.join(real_categories)}"},
                        "diet_tag": {"type": "string", "description": "e.g. 'vegan', 'vegetarian', 'jain', 'non-vegetarian'"},
                        "allergen_free": {"type": "array", "items": {"type": "string"}, "description": "allergens the dish must NOT contain, e.g. ['egg','dairy']"},
                        "allergen_contains": {"type": "array", "items": {"type": "string"}, "description": "allergens the dish MUST contain"},
                        "max_price": {"type": "number"},
                        "min_price": {"type": "number"},
                        "max_calories": {"type": "number"},
                        "min_calories": {"type": "number"},
                        "tag_contains": {"type": "string", "description": f"One of this menu's real dietary tags: {', '.join(real_tags)}"},
                        "spice": {"type": "string", "description": "Filter by spice level: 'mild', 'medium', 'spicy', 'very spicy'"},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_dish_details",
                "description": "Get full details (ingredients, customisations, exact allergens) for one specific dish by name.",
                "parameters": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
            },
        },
    ]

    dispatch = {"search_dishes": search_dishes, "get_dish_details": get_dish_details}
    return schemas, dispatch
