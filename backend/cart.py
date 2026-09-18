"""
Pure cart operations — no LLM, just reads/writes to the database.

The cart lives in sessions.cart (JSON column) while the customer is browsing.
On checkout it gets snapshotted into orders + order_items and the cart is cleared.
"""
import copy
from datetime import datetime

from . import events
from .database import DbSession, Order, OrderItem


# ── session helpers ───────────────────────────────────────────────────────────

def get_or_create_session(db, session_id: str) -> DbSession:
    sess = db.query(DbSession).filter(DbSession.id == session_id).first()
    if not sess:
        sess = DbSession(id=session_id, cart=[])
        db.add(sess)
        db.commit()
    return sess


# ── cart read ─────────────────────────────────────────────────────────────────

def get_cart(db, session_id: str) -> list[dict]:
    return list(get_or_create_session(db, session_id).cart or [])


def cart_total(cart: list[dict]) -> float:
    return round(sum(item["subtotal"] for item in cart), 2)


def format_cart(cart: list[dict]) -> str:
    if not cart:
        return "Your cart is empty."
    lines = ["**Your cart:**"]
    for item in cart:
        cust = item.get("customizations", {})
        notes = []
        if cust.get("add"):
            notes.append("extra " + ", ".join(cust["add"]))
        if cust.get("reduce"):
            notes.append("less " + ", ".join(cust["reduce"]))
        note_str = f" ({', '.join(notes)})" if notes else ""
        lines.append(
            f"• **{item['dish_name']}** ×{item['quantity']}{note_str} — ₹{item['subtotal']}"
        )
    lines.append(f"\n**Total: ₹{cart_total(cart)}**")
    return "\n".join(lines)


# ── cart write ────────────────────────────────────────────────────────────────

def _quantities(cart: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for item in cart or []:
        out[item["dish_name"]] = out.get(item["dish_name"], 0) + int(item.get("quantity") or 0)
    return out


def _save_cart(db, sess: DbSession, cart: list[dict], track: bool = True):
    before = _quantities(sess.cart)
    sess.cart = cart
    sess.updated_at = datetime.utcnow()
    db.commit()
    if track:
        _track_cart_change(sess.id, before, _quantities(cart))


def _track_cart_change(session_id: str, before: dict[str, int], after: dict[str, int]):
    """Record one cart_added / cart_removed event per dish whose quantity changed."""
    rows = []
    for dish in sorted(set(before) | set(after)):
        change = after.get(dish, 0) - before.get(dish, 0)
        if change > 0:
            rows.append({
                "session_id": session_id, "event_type": "cart_added", "dish_name": dish,
                "properties": {
                    "quantity": change,
                    "was_suggested": events.was_suggested(session_id, dish),
                },
            })
        elif change < 0:
            rows.append({
                "session_id": session_id, "event_type": "cart_removed", "dish_name": dish,
                "properties": {"quantity": -change},
            })
    events.record_many(rows)


def add_item(
    db,
    session_id: str,
    dish_name: str,
    dish_price: float,
    quantity: int,
    customizations: dict,
) -> list[dict]:
    sess = get_or_create_session(db, session_id)
    cart = copy.deepcopy(sess.cart or [])

    # Merge with existing line if same dish + same customizations
    for item in cart:
        if (
            item["dish_name"].lower() == dish_name.lower()
            and item.get("customizations", {}) == customizations
        ):
            item["quantity"] += quantity
            item["subtotal"] = round(item["dish_price"] * item["quantity"], 2)
            _save_cart(db, sess, cart)
            return cart

    cart.append({
        "dish_name": dish_name,
        "dish_price": dish_price,
        "quantity": quantity,
        "customizations": customizations,
        "subtotal": round(dish_price * quantity, 2),
    })
    _save_cart(db, sess, cart)
    return cart


def remove_item(db, session_id: str, dish_name: str) -> list[dict]:
    sess = get_or_create_session(db, session_id)
    cart = [i for i in (sess.cart or []) if i["dish_name"].lower() != dish_name.lower()]
    _save_cart(db, sess, cart)
    return cart


def update_quantity(db, session_id: str, dish_name: str, quantity: int) -> list[dict]:
    sess = get_or_create_session(db, session_id)
    cart = copy.deepcopy(sess.cart or [])
    if quantity <= 0:
        cart = [i for i in cart if i["dish_name"].lower() != dish_name.lower()]
    else:
        for item in cart:
            if item["dish_name"].lower() == dish_name.lower():
                item["quantity"] = quantity
                item["subtotal"] = round(item["dish_price"] * quantity, 2)
                break
    _save_cart(db, sess, cart)
    return cart


def clear_cart(db, session_id: str):
    sess = get_or_create_session(db, session_id)
    _save_cart(db, sess, [])


# ── checkout ──────────────────────────────────────────────────────────────────

def checkout(
    db,
    session_id: str,
    note: str | None = None,
    customer_name: str | None = None,
    table_number: str | None = None,
) -> Order:
    sess = get_or_create_session(db, session_id)
    cart = list(sess.cart or [])
    if not cart:
        raise ValueError("Cart is empty — nothing to place.")

    # Prevent duplicate orders from double-clicks or multiple tabs
    active = (
        db.query(Order)
        .filter(Order.session_id == session_id)
        .filter(Order.status.in_(["pending", "confirmed", "preparing", "ready"]))
        .first()
    )
    if active:
        raise ValueError("You already have an active order. Please wait for it to complete.")

    total = cart_total(cart)
    order = Order(
        session_id=session_id,
        status="pending",
        total_amount=total,
        customer_name=customer_name,
        table_number=table_number,
        customer_note=note,
    )
    db.add(order)
    db.flush()  # get order.id before inserting items

    for item in cart:
        db.add(OrderItem(
            order_id=order.id,
            dish_name=item["dish_name"],
            dish_price=item["dish_price"],
            quantity=item["quantity"],
            customizations=item.get("customizations", {}),
            subtotal=item["subtotal"],
        ))

    _save_cart(db, sess, [], track=False)  # clear cart after checkout — not a removal
    db.commit()
    db.refresh(order)

    events.record(
        session_id, "order_placed",
        order_id=order.id,
        total=float(order.total_amount),
        items=[
            {
                "dish_name":     item["dish_name"],
                "quantity":      item["quantity"],
                "was_suggested": events.was_suggested(session_id, item["dish_name"]),
            }
            for item in cart
        ],
    )
    return order
