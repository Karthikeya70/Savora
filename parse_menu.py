"""
Parse Savora_Menu_Catalog.pdf (extracted as menu_text.txt) into a structured
savora_menu_dataset.json.

The PDF layout interleaves a left-hand photo-badge column with the right-hand
info column in the extracted text (e.g. "NO VERIFIED Approx calories: 420 kcal
PHOTO Spice: ..."), so parsing is done with regexes over per-dish text blocks
rather than assuming a fixed line order.
"""
import json
import re

RAW = open("menu_text.txt", encoding="utf-8").read()

# Strip page markers and running footer lines.
RAW = re.sub(r"--- PAGE \d+ ---\n", "", RAW)
RAW = re.sub(r"Savora - dummy menu dataset - know your food before you order Page \d+\n?", "", RAW)

# Split into dish blocks. Each dish starts with "<Name> Rs <price>" on its own
# line followed by "[CODE]" on the next line.
DISH_START = re.compile(r"^(.+?)\s+Rs\s+(\d+)\s*\n\[([A-Z0-9]+)\]\s*\n", re.MULTILINE)

matches = list(DISH_START.finditer(RAW))
print(f"Found {len(matches)} dish headers")

dishes = []
for i, m in enumerate(matches):
    name, price, code = m.group(1).strip(), int(m.group(2)), m.group(3)
    start = m.end()
    end = matches[i + 1].start() if i + 1 < len(matches) else len(RAW)
    block = RAW[start:end]

    lines = [l for l in block.split("\n") if l.strip()]

    # Category line: first non-empty line, optionally "Category · also: aliases"
    category_line = lines[0] if lines else ""
    also = None
    if "also:" in category_line:
        cat_part, also_part = category_line.split("also:", 1)
        category = cat_part.split("·")[0].strip().rstrip("·").strip()
        also = [a.strip() for a in also_part.split("/")]
    else:
        category = category_line.split("·")[0].strip()

    # Badges line (BESTSELLER, SPICY ***, VEGAN, JAIN OK, HIGH PROTEIN, etc.)
    # It's the line right after category, before the description, made of
    # ALL-CAPS words/stars only.
    KNOWN_BADGES = [
        r"BESTSELLER", r"NEW", r"CHEF'S SPECIAL", r"HIGH PROTEIN", r"VEGAN",
        r"JAIN OK", r"SPICY \*+", r"GLUTEN FREE",
    ]
    badge_idx = 1
    badges = []
    had_badge_line = False
    if badge_idx < len(lines) and re.fullmatch(r"[A-Z0-9 *\-']+", lines[badge_idx].strip()):
        badge_text = lines[badge_idx].strip()
        remaining = badge_text
        for kb in KNOWN_BADGES:
            bm = re.search(kb, remaining)
            if bm:
                badges.append(bm.group(0))
                remaining = remaining[:bm.start()] + remaining[bm.end():]
        remaining = remaining.strip()
        if remaining:
            badges.append(remaining)
        had_badge_line = True
        badge_idx += 1

    def find(pattern, text=block, flags=re.IGNORECASE):
        mm = re.search(pattern, text, flags)
        return mm.group(1).strip() if mm else None

    serves = find(r"Serves:\s*([^\n]+)")
    calories = find(r"Approx calories:\s*([0-9]+)\s*kcal")
    spice = find(r"Spice:\s*([^\n]+)")
    prep_time = find(r"Prep time:\s*([^\n]+)")
    dietary_raw = find(r"Dietary:\s*([^\n]+)")
    dietary = [d.strip() for d in dietary_raw.split(",")] if dietary_raw else []
    available = find(r"Available:\s*([^\n]+)")

    # Photo type + match score (order in text varies due to column bleed)
    photo_match = find(r"photo-reality match:\s*\n?\s*(\d+)%")
    if re.search(r"ACTUAL PHOTO", block):
        photo_type = "actual_dish_photo"
    elif re.search(r"REPRESENTATIVE", block):
        photo_type = "representative"
    elif re.search(r"NO VERIFIED", block):
        photo_type = "none"
    else:
        photo_type = None

    # Description: text between badges line and "Serves:"
    desc_match = re.search(r"\n(.*?)\nServes:", block, re.DOTALL)
    description = None
    if desc_match:
        desc_lines = [l.strip() for l in desc_match.group(1).split("\n") if l.strip()]
        excluded = {category_line}
        if had_badge_line and len(lines) > 1:
            excluded.add(lines[1])
        desc_lines = [l for l in desc_lines if l not in excluded]
        description = " ".join(desc_lines).strip()

    # Ingredients table: between "INGREDIENTS & PROMINENCE" header+col-titles and "ALLERGENS"
    ingredients = []
    ing_match = re.search(
        r"INGREDIENTS & PROMINENCE\s*\nIngredient Prominence Removable Allergens\n(.*?)\nALLERGENS",
        block, re.DOTALL,
    )
    if ing_match:
        for row in ing_match.group(1).split("\n"):
            row = row.strip()
            if not row:
                continue
            rm = re.match(
                r"(.+?)\s+(primary|secondary|minor|trace|garnish)\s+(yes|no)\s+(.+)$",
                row, re.IGNORECASE,
            )
            if rm:
                ing_name, prominence, removable, allergens = rm.groups()
                allergens_list = [] if allergens.strip() == "-" else [a.strip() for a in allergens.split(",")]
                ingredients.append({
                    "ingredient": ing_name.strip(),
                    "prominence": prominence.lower(),
                    "removable": removable.lower() == "yes",
                    "allergens": allergens_list,
                })

    # Allergens block
    contains_raw = find(r"Contains:\s*([^\n]+)")
    contains = [a.strip() for a in contains_raw.split(",")] if contains_raw else []
    may_contain_raw = find(r"May contain \(cross-contact\):\s*([^\n]+)")
    may_contain = [a.strip() for a in may_contain_raw.split(",")] if may_contain_raw else []
    status_raw = find(r"Status:\s*([^\n]+)")
    allergen_status_verified = bool(status_raw and "verified" in status_raw.lower())

    # Preparation
    prep_match = re.search(r"PREPARATION\s*\n(.+?)\s*·\s*made to order:\s*(yes|no)([^\n]*)", block, re.IGNORECASE)
    prep_method = made_to_order = made_to_order_note = None
    if prep_match:
        prep_method = prep_match.group(1).strip()
        made_to_order = prep_match.group(2).lower() == "yes"
        made_to_order_note = prep_match.group(3).strip(" ()")

    # Customisations table
    customisations = []
    cust_match = re.search(
        r"CUSTOMISATIONS\s*\nCustomisation Allowed\? Price\n(.*?)$",
        block, re.DOTALL,
    )
    if cust_match:
        cust_block = cust_match.group(1)
        cust_block = re.split(r"\nBEVERAGES\n|\nDESSERTS\n", cust_block)[0]
        for row in cust_block.split("\n"):
            row = row.strip()
            if not row:
                continue
            rm = re.match(r"(.+?)\s+(Yes|No)\s+(.+)$", row)
            if rm:
                cust_name, allowed, price_txt = rm.groups()
                customisations.append({
                    "customisation": cust_name.strip(),
                    "allowed": allowed == "Yes",
                    "price_note": price_txt.strip(),
                })

    dishes.append({
        "code": code,
        "name": name,
        "price_inr": price,
        "category": category,
        "also_known_as": also,
        "badges": badges,
        "description": description,
        "serves": serves,
        "approx_calories_kcal": int(calories) if calories else None,
        "spice": spice,
        "prep_time": prep_time,
        "dietary_tags": dietary,
        "available": available,
        "photo_type": photo_type,
        "photo_reality_match_pct": int(photo_match) if photo_match else None,
        "ingredients": ingredients,
        "allergens_contains": contains,
        "allergens_may_contain": may_contain,
        "allergens_verified_by_kitchen": allergen_status_verified,
        "preparation_method": prep_method,
        "made_to_order": made_to_order,
        "made_to_order_note": made_to_order_note,
        "customisations": customisations,
    })

with open("savora_menu_dataset.json", "w", encoding="utf-8") as f:
    json.dump({"restaurant": "Savora", "dish_count": len(dishes), "dishes": dishes}, f, indent=2, ensure_ascii=False)

print(f"Wrote {len(dishes)} dishes to savora_menu_dataset.json")
