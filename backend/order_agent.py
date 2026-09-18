"""
Order Agent — manages the customer's cart via natural conversation.

Responsibilities:
  - Add / remove / update items in the cart
  - Handle ingredient customizations ("extra chutney", "less oil")
  - Show cart summary on request
  - Place the order (writes to DB) when the customer confirms

The agent receives a session_id so all cart operations are scoped to
one customer. Cart state persists in the database between turns.
"""
import json

from . import cart as cart_ops
from .database import SessionLocal
from .llm_client import ask_llm_with_tools

ORDER_SYSTEM_PROMPT = """\
You are Savora's order assistant — friendly, efficient, and precise.
Your only job is to manage the customer's cart and place their order.

WHAT YOU CAN DO:
• Add dishes to the cart — with customizations like "extra chutney" or "less oil"
• Remove dishes or update quantities
• Show the current cart summary
• Place the order once the customer confirms

RULES:
1. The current cart state is always shown above — use it. Never assume the cart is empty.
2. Only add dishes that exist on the menu. If unsure, call look_up_dish first.
3. When adding to the cart, ALWAYS call add_to_cart — do not just say "added".
4. After every add/remove/update, show the updated cart to the customer.
5. When asked to place an order: confirm the cart contents with the customer, \
   then call place_order once they confirm.
6. Once the customer says "yes", "confirm", "place it", or similar — call place_order immediately.
7. Stay focused on orders — if the customer asks a menu question, answer briefly \
   and redirect back to ordering.

VOICE: Warm, efficient, like a friendly cashier. Confirm customizations back to the customer. \
Use **bold** for dish names.\
"""


def build_order_tools(dishes: list[dict], session_id: str, db):
    """Build the tool schemas and dispatch map scoped to this session."""

    def look_up_dish(name: str) -> dict:
        """Find a dish by name (exact or fuzzy) and return its name + price."""
        name_lower = name.lower()
        for d in dishes:
            if d.get("name", "").lower() == name_lower:
                return {"found": True, "name": d["name"], "price": d.get("price_inr")}
        for d in dishes:
            if name_lower in d.get("name", "").lower():
                return {"found": True, "name": d["name"], "price": d.get("price_inr")}
        return {"found": False, "error": f"No dish named '{name}' on the menu."}

    def view_cart() -> str:
        current = cart_ops.get_cart(db, session_id)
        return cart_ops.format_cart(current)

    def add_to_cart(dish_name: str, quantity: int = 1,
                    add_ingredients: list | None = None,
                    reduce_ingredients: list | None = None) -> str:
        info = look_up_dish(dish_name)
        if not info.get("found"):
            return info["error"]
        customizations = {}
        if add_ingredients:
            customizations["add"] = add_ingredients
        if reduce_ingredients:
            customizations["reduce"] = reduce_ingredients
        updated = cart_ops.add_item(
            db, session_id,
            dish_name=info["name"],
            dish_price=float(info["price"] or 0),
            quantity=quantity,
            customizations=customizations,
        )
        return cart_ops.format_cart(updated)

    def remove_from_cart(dish_name: str) -> str:
        updated = cart_ops.remove_item(db, session_id, dish_name)
        return cart_ops.format_cart(updated)

    def update_quantity(dish_name: str, quantity: int) -> str:
        updated = cart_ops.update_quantity(db, session_id, dish_name, quantity)
        return cart_ops.format_cart(updated)

    def place_order(customer_note: str | None = None) -> str:
        try:
            order = cart_ops.checkout(db, session_id, note=customer_note)
            return json.dumps({
                "success": True,
                "order_id": order.id,
                "total": float(order.total_amount),
                "status": order.status,
            })
        except ValueError as e:
            return json.dumps({"success": False, "error": str(e)})

    schemas = [
        {
            "type": "function",
            "function": {
                "name": "look_up_dish",
                "description": "Check if a dish exists on the menu and get its price before adding to cart.",
                "parameters": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "view_cart",
                "description": "Show the customer's current cart.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "add_to_cart",
                "description": "Add a dish to the cart with optional customizations.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "dish_name": {"type": "string", "description": "Exact dish name from the menu"},
                        "quantity": {"type": "integer", "default": 1},
                        "add_ingredients": {
                            "type": "array", "items": {"type": "string"},
                            "description": "Ingredients to add extra, e.g. ['chutney', 'onion']",
                        },
                        "reduce_ingredients": {
                            "type": "array", "items": {"type": "string"},
                            "description": "Ingredients to use less of, e.g. ['butter', 'oil']",
                        },
                    },
                    "required": ["dish_name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "remove_from_cart",
                "description": "Remove a dish from the cart entirely.",
                "parameters": {
                    "type": "object",
                    "properties": {"dish_name": {"type": "string"}},
                    "required": ["dish_name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "update_quantity",
                "description": "Change the quantity of a dish already in the cart.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "dish_name": {"type": "string"},
                        "quantity": {"type": "integer"},
                    },
                    "required": ["dish_name", "quantity"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "place_order",
                "description": "Place the order — saves cart to database. Call only after customer confirms.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "customer_note": {
                            "type": "string",
                            "description": "Any special note from the customer for the kitchen.",
                        }
                    },
                },
            },
        },
    ]

    dispatch = {
        "look_up_dish": look_up_dish,
        "view_cart": view_cart,
        "add_to_cart": add_to_cart,
        "remove_from_cart": remove_from_cart,
        "update_quantity": update_quantity,
        "place_order": place_order,
    }
    return schemas, dispatch


def handle_order(
    question: str,
    dishes: list[dict],
    session_id: str,
    history: list[dict] | None = None,
) -> dict:
    db = SessionLocal()
    try:
        # Pre-load current cart into the system prompt — the LLM always knows
        # the cart state without needing to call view_cart first.
        current_cart  = cart_ops.get_cart(db, session_id)
        cart_snapshot = cart_ops.format_cart(current_cart)
        augmented_prompt = (
            ORDER_SYSTEM_PROMPT
            + f"\n\nCURRENT CART STATE:\n{cart_snapshot}"
        )

        tools, dispatch = build_order_tools(dishes, session_id, db)
        recent_history = (history or [])[-6:]
        answer, calls_made = ask_llm_with_tools(
            augmented_prompt, question, tools, dispatch, history=recent_history
        )

        # Re-fetch cart after tool calls so the frontend gets the latest state.
        # expire_all forces SQLAlchemy to discard its identity-map cache and
        # issue a fresh SELECT — without this, the same db session returns the
        # object it already has in memory, which may be stale after tool commits.
        db.expire_all()
        cart_after   = cart_ops.get_cart(db, session_id)
        order_placed = any(c["name"] == "place_order" for c in calls_made)

        return {
            "answer":        answer,
            "used_llm":      True,
            "filters_applied": [],
            "dish_names":    [],
            "agent":         "order",
            "cart":          cart_after,
            "cart_total":    cart_ops.cart_total(cart_after),
            "order_placed":  order_placed,
        }
    finally:
        db.close()
