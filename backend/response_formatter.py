"""
Converts structured filter results into natural, conversational responses.
Zero LLM calls — template-based, fast, no cost.

Design goal: "what would a knowledgeable, warm food guide say?"

Bad  → "11 dish(es) match (diet: vegan; price <= 150): Pani Puri, Samosa, ..."
Good → "We have 11 vegan options under ₹150. Some highlights:
        • **Pani Puri** (BESTSELLER · ₹60) — crispy shells with tangy tamarind water.
        • **Masala Dosa** (₹120) — South Indian classic, light and very satisfying.
        …and 9 more. Want me to narrow it down by spice or category?"
"""


# ── helpers ──────────────────────────────────────────────────────────────────

def _badge_highlights(dish: dict) -> list[str]:
    """Return notable badges, stripping pure diet labels already stated elsewhere."""
    skip = {"VEGETARIAN", "VEGAN", "NON-VEG", "NON-VEGETARIAN", "JAIN OK"}
    return [b for b in (dish.get("badges") or []) if b.upper() not in skip]


def _price_tag(dish: dict) -> str:
    p = dish.get("price_inr")
    return f"₹{p}" if p is not None else ""


def _brief_desc(dish: dict, max_chars: int = 80) -> str:
    desc = (dish.get("description") or "").strip()
    if not desc:
        return ""
    return desc[:max_chars].rstrip() + ("…" if len(desc) > max_chars else "")


def _sort_key(dish: dict):
    """Bestsellers first, then cheapest first."""
    is_bs = any("BESTSELLER" in (b or "").upper() for b in (dish.get("badges") or []))
    return (0 if is_bs else 1, dish.get("price_inr") or 9999)


def _dish_line(dish: dict, show_desc: bool = True) -> str:
    """One bullet-line for a dish: **Name** (BADGE · ₹price) — brief description."""
    name = dish.get("name", "")
    badges = _badge_highlights(dish)
    price = _price_tag(dish)

    meta_parts = []
    if badges:
        meta_parts.append(badges[0])
    if price:
        meta_parts.append(price)

    line = f"**{name}**"
    if meta_parts:
        line += f" ({' · '.join(meta_parts)})"
    if show_desc:
        desc = _brief_desc(dish)
        if desc:
            line += f" — {desc}"
    return line


# ── filter label → readable English ──────────────────────────────────────────

def _describe_filters(filters_applied: list[str]) -> str:
    """Turn structured filter labels into plain English for use inside a sentence."""
    parts = []
    for f in filters_applied:
        if f.startswith("diet: "):
            parts.append(f[6:])
        elif f.startswith("free of: "):
            parts.append(f[9:] + "-free")
        elif f.startswith("contains: "):
            parts.append("with " + f[10:])
        elif f.startswith("spice: "):
            parts.append(f[7:])
        elif f.startswith("tag: "):
            parts.append(f[5:].replace("-", " ").replace("_", " "))
        elif "price <=" in f:
            limit = f.split("<=")[1].strip()
            parts.append(f"under ₹{limit}")
        elif "price >=" in f:
            limit = f.split(">=")[1].strip()
            parts.append(f"over ₹{limit}")
        elif "calories <=" in f:
            limit = f.split("<=")[1].strip()
            parts.append(f"under {limit} kcal")
        elif "ingredient free of" in f:
            ingr = f.split(": ", 1)[1] if ": " in f else ""
            parts.append(f"no {ingr}")
        elif f.startswith("ingredient: "):
            parts.append("with " + f[12:])
        elif "cooking method free of" in f:
            method = f.split(": ", 1)[1] if ": " in f else ""
            parts.append(f"not {method}")
        elif f.startswith("cooking method: "):
            parts.append(f[16:])
        # skip category and single-dish labels — context already makes them clear
    return " & ".join(parts) if parts else ""


# ── main formatter ────────────────────────────────────────────────────────────

def format_filter_result(
    dishes: list[dict],
    filters_applied: list[str],
    prefix: str = "",
) -> str:
    """
    Format a filtered dish list as a natural-language chat response.

    Args:
        dishes:           dishes that passed the filters
        filters_applied:  list of filter label strings (for context)
        prefix:           optional sentence prefix, e.g. "Of those, " for
                          group-refinement follow-ups
    """
    n = len(dishes)
    filter_desc = _describe_filters(filters_applied)

    if n == 0:
        qualifier = f" {filter_desc}" if filter_desc else " those criteria"
        return (
            f"{prefix}Nothing on our menu matches{qualifier} right now. "
            "Want to try a broader search? I can suggest alternatives."
        )

    sorted_dishes = sorted(dishes, key=_sort_key)

    if n == 1:
        d = sorted_dishes[0]
        just = "just" if prefix else "Just"
        return f"{prefix}{just} one match: {_dish_line(d)}."

    if n <= 3:
        lines = [f"• {_dish_line(d)}" for d in sorted_dishes]
        desc_part = f" ({filter_desc})" if filter_desc else ""
        return f"{prefix}Here are {n} options{desc_part}:\n" + "\n".join(lines)

    # 4+ results: show top picks, offer to narrow down
    picks = sorted_dishes[:4]
    lines = [f"• {_dish_line(d)}" for d in picks]
    remainder = n - len(picks)

    if filter_desc:
        intro = f"{prefix}We have {n} {filter_desc} options. Some highlights:"
    else:
        intro = f"{prefix}We have {n} options. Some highlights:"

    result = intro + "\n" + "\n".join(lines)
    if remainder > 0:
        result += (
            f"\n…and {remainder} more. "
            "Want me to narrow it down — by spice level, price, or category?"
        )
    return result


# ── single-dish formatters ────────────────────────────────────────────────────

def format_allergen_answer(dish: dict, question: str = "") -> str:
    name = dish.get("name", "")
    contains = dish.get("allergens_contains", [])
    may     = dish.get("allergens_may_contain", [])
    tags    = dish.get("dietary_tags", [])
    q = question.lower()

    _ALLERGEN_MAP = {
        "gluten":  {"gluten", "wheat"},
        "dairy":   {"dairy", "milk"},
        "egg":     {"egg"},
        "nut":     {"tree_nut", "nut", "peanut"},
        "soy":     {"soy", "soya"},
        "sesame":  {"sesame", "til"},
        "mustard": {"mustard"},
    }
    _ALLERGEN_KEYWORDS = {
        "gluten": ["gluten", "wheat", "flour"],
        "dairy":  ["dairy", "milk", "lactose", "cheese", "butter", "cream"],
        "egg":    ["egg", "eggs"],
        "nut":    ["nut", "nuts", "peanut", "peanuts"],
        "soy":    ["soy", "soya"],
        "sesame": ["sesame", "til"],
        "mustard": ["mustard"],
    }

    asked_label = None
    for label, kws in _ALLERGEN_KEYWORDS.items():
        if any(kw in q for kw in kws):
            asked_label = label
            break

    is_free_q    = any(w in q for w in ["free", "without", "safe", "avoid", "okay", "ok"])
    is_contain_q = any(w in q for w in ["contain", " has ", " have ", "include"])
    is_yes_no_q  = any(p in q for p in ["is it", "is the", "is this", "is a ", "are they"])

    # Handle dietary lifestyle yes/no questions (vegan, vegetarian, jain)
    for diet_kw in ("vegan", "vegetarian", "jain"):
        if diet_kw in q and (is_yes_no_q or is_free_q):
            has_tag = any(diet_kw in t.lower() for t in tags)
            verdict = f"Yes — **{name}** is {diet_kw}." if has_tag else f"No — **{name}** is not {diet_kw}."
            allergen_note = ""
            if contains:
                allergen_note = f" Allergens: {', '.join(contains)}."
            if may:
                allergen_note += f" May contain trace {', '.join(may)}."
            return verdict + allergen_note + " Please confirm with our kitchen if you have a severe allergy."

    if asked_label and (is_free_q or is_contain_q):
        # Build a response that speaks directly to the asked allergen first,
        # then adds any other allergens as secondary info.
        allergen_set   = _ALLERGEN_MAP[asked_label]
        contains_lower = {a.lower() for a in contains}
        may_lower      = {a.lower() for a in may}
        in_declared = bool(contains_lower & allergen_set)
        in_may      = bool(may_lower      & allergen_set)
        label_name  = asked_label.replace("_", " ")

        if is_free_q and not is_contain_q:
            if in_declared:
                opening = f"No — **{name}** contains {label_name}."
            elif in_may:
                opening = f"No — **{name}** may have trace {label_name} from cross-contact."
            else:
                opening = f"Yes — **{name}** is {label_name}-free (none declared)."
        else:  # is_contain_q
            if in_declared:
                opening = f"Yes — **{name}** contains {label_name}."
            elif in_may:
                opening = f"Yes — **{name}** may have trace {label_name} from kitchen cross-contact."
            else:
                opening = f"No — **{name}** contains no {label_name}."

        # Other allergens (excluding what we just spoke about)
        other_declared = [a for a in contains if a.lower() not in allergen_set]
        other_may      = [a for a in may      if a.lower() not in allergen_set]
        rest = ""
        if other_declared:
            rest += f" It does contain {', '.join(other_declared)}."
        if other_may:
            rest += f" May also have trace {', '.join(other_may)} from cross-contact."
        if tags:
            rest += f" Dietary: {', '.join(tags)}."
        rest += " Please confirm with our kitchen if you have a severe allergy."
        return opening + rest

    # Generic allergen summary (no specific allergen asked, or ambiguous phrasing)
    if not contains:
        allergen_line = f"**{name}** has no declared allergens."
    elif len(contains) == 1:
        allergen_line = f"**{name}** contains {contains[0]}."
    else:
        allergen_line = f"**{name}** contains: {', '.join(contains)}."
    if may:
        allergen_line += f" May also have trace {', '.join(may)} from kitchen cross-contact."
    if tags:
        allergen_line += f" Dietary: {', '.join(tags)}."
    allergen_line += " Please confirm with our kitchen if you have a severe allergy."
    return allergen_line


def format_ingredient_answer(dish: dict) -> str:
    name = dish.get("name", "")
    ing = dish.get("ingredients", [])
    if not ing:
        return f"No detailed ingredient breakdown available for **{name}**."

    primary = [i["ingredient"] for i in ing if i.get("prominence") == "primary"]
    secondary = [i["ingredient"] for i in ing if i.get("prominence") == "secondary"]
    minor = [i["ingredient"] for i in ing if i.get("prominence") in ("minor", "trace", "garnish")]

    parts = []
    if primary:
        parts.append(f"**{name}** is built around {', '.join(primary)}")
    if secondary:
        parts.append(f"with {', '.join(secondary)}")
    if minor:
        parts.append(f"and finished with {', '.join(minor[:3])}")

    return ". ".join(parts) + "." if parts else (
        f"**{name}** ingredients: " + ", ".join(i["ingredient"] for i in ing) + "."
    )


def format_spice_answer(dish: dict) -> str:
    import re
    name = dish.get("name", "")
    spice = dish.get("spice") or "spice level not specified"
    m = re.search(r"level\s*(\d)/(\d)", spice, re.I)
    adjustable = "adjustable" in spice.lower()

    if m:
        level = int(m.group(1))
        descs = {
            1: "quite mild — barely any heat",
            2: "lightly spiced, mild warmth",
            3: "nicely spicy with a good kick",
            4: "very spicy / fiery — not for the faint-hearted",
        }
        desc = descs.get(level, "moderately spiced")
        adj = " The spice can be adjusted — just ask." if adjustable else ""
        return f"**{name}** is {desc} (level {level}/4).{adj}"

    return f"**{name}**: {spice}."


def format_price_answer(dish: dict) -> str:
    name = dish.get("name", "")
    price = dish.get("price_inr")
    if price is None:
        return f"No price listed for **{name}**."
    paid_cust = [
        c for c in (dish.get("customisations") or [])
        if c.get("allowed") and c.get("price_note") and c["price_note"] != "no charge"
    ]
    note = " Some add-ons carry an extra charge." if paid_cust else ""
    return f"**{name}** is ₹{price}.{note}"


def format_customisation_answer(dish: dict) -> str:
    name = dish.get("name", "")
    cust = [c for c in (dish.get("customisations") or []) if c.get("allowed")]
    if not cust:
        return (
            f"No specific customisation options are listed for **{name}**, "
            "but the kitchen is usually happy to accommodate — just ask."
        )
    options = "; ".join(
        c["customisation"]
        + (f" ({c['price_note']})" if c.get("price_note") and c["price_note"] != "no charge" else "")
        for c in cust[:5]
    )
    return f"**{name}** customisations: {options}."


def format_dish_overview(dish: dict) -> str:
    """General 'tell me about this dish' response."""
    import re as _re
    name = dish.get("name", "")
    desc = (dish.get("description") or "").strip()
    ing = dish.get("ingredients", [])
    tags = dish.get("dietary_tags", [])
    price = _price_tag(dish)
    spice = dish.get("spice", "")

    # Truncate description at a sentence boundary where possible
    if len(desc) > 160:
        # find last sentence end within 200 chars
        snip = desc[:200]
        last_dot = max(snip.rfind(". "), snip.rfind("! "), snip.rfind("? "))
        desc = snip[: last_dot + 1] if last_dot > 80 else desc[:160] + "…"

    parts = [desc] if desc else []

    primary = [i["ingredient"] for i in ing if i.get("prominence") == "primary"]
    if primary:
        parts.append(f"Main ingredients: {', '.join(primary[:4])}.")

    # Build a compact meta line (price · spice · key diet tags)
    meta = []
    if price:
        meta.append(price)
    if spice:
        m = _re.search(r"level\s*(\d)", spice, _re.I)
        if m:
            meta.append(f"spice {m.group(1)}/4")
    # Only show the most meaningful diet tags
    key_tags = [t for t in tags if t in ("vegan", "vegetarian", "non-vegetarian", "jain-on-request", "gluten-free-recipe")]
    if key_tags:
        meta.append(", ".join(key_tags))
    if meta:
        parts.append("(" + " · ".join(meta) + ")")

    return f"**{name}**: " + " ".join(parts) if parts else f"**{name}** — no additional details available."
