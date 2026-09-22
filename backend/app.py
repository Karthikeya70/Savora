import asyncio
import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.orm import joinedload

from . import embeddings, events, experiment, insights, popularity, cart as cart_ops
from . import cache as response_cache
from . import ratelimit
from .data import load_menu
from .database import SessionLocal, init_db
from .dish_index import DishIndex
from .llm_client import llm_configured
from .orchestrator import route
from .order_agent import handle_order
from .router import answer_question
from .support_agent import handle_support

# ── logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("savora")

# ── config ────────────────────────────────────────────────────────────────────

FRONTEND_DIR     = Path(__file__).parent.parent / "frontend"
DASHBOARD_SECRET = os.environ.get("DASHBOARD_SECRET", "")

_raw_origins    = os.environ.get("ALLOWED_ORIGINS", "")
ALLOWED_ORIGINS = [o.strip() for o in _raw_origins.split(",") if o.strip()] or ["*"]

menu = load_menu()
dish_index: DishIndex | None = None


# ── startup ───────────────────────────────────────────────────────────────────

def _load_models():
    """Runs in a thread — keeps the event loop free during startup."""
    global dish_index
    init_db()
    if os.environ.get("SEED_DEMO_DATA") == "1":
        _seed_demo_data()
    embeddings.embed("warmup")
    dish_index = DishIndex(menu.get("dishes", []))
    logger.info(
        "Ready — %d dishes indexed, DB tables verified, embedding model loaded",
        len(menu.get("dishes", [])),
    )


def _seed_demo_data():
    """
    On a hosted demo the database starts empty, so the Insights page would have
    nothing to show a visitor. With SEED_DEMO_DATA=1, fill in practice data once
    (clearly labelled DEMO, never mixed with real visits). Skipped if it's
    already there.
    """
    import importlib.util
    from .database import Event, SessionLocal

    db = SessionLocal()
    try:
        if db.query(Event.id).filter(Event.source == "demo").first():
            return
    finally:
        db.close()

    path = Path(__file__).resolve().parent.parent / "scripts" / "demo_data.py"
    spec = importlib.util.spec_from_file_location("demo_data", path)
    demo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(demo)
    added = demo.generate()
    logger.info("Seeded %d demo events for the Insights page", added)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await asyncio.to_thread(_load_models)
    asyncio.create_task(_session_cleanup_loop())
    yield


app = FastAPI(title="Savora Menu Chatbot", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── API models ────────────────────────────────────────────────────────────────

class HistoryTurn(BaseModel):
    role: str
    content: str
    dish_names: list[str] | None = None


class ChatRequest(BaseModel):
    question:   str
    session_id: str | None = None
    history:    list[HistoryTurn] | None = None


class CartUpdateRequest(BaseModel):
    session_id: str
    dish_name:  str
    quantity:   int


class CartCheckoutRequest(BaseModel):
    session_id:    str
    customer_name: str | None = Field(None, max_length=80)
    table_number:  str | None = Field(None, max_length=20)
    note:          str | None = Field(None, max_length=500)


class OrderCancelRequest(BaseModel):
    order_id:   str
    session_id: str  # verified against order — prevents unauthorized cancellations


class StatusUpdateRequest(BaseModel):
    status: str


class DishRating(BaseModel):
    dish_name: str = Field(..., max_length=120)
    liked:     bool


class OrderRatingRequest(BaseModel):
    ratings: list[DishRating] = Field(..., min_length=1, max_length=50)


ALLOWED_TRANSITIONS: dict[str, list[str]] = {
    "pending":   ["confirmed", "cancelled"],
    "confirmed": ["preparing", "cancelled"],
    "preparing": ["ready"],
    "ready":     ["completed"],
    "completed": [],
    "cancelled": [],
}


# ── helpers ───────────────────────────────────────────────────────────────────

def _dashboard_auth_ok(secret: str | None) -> bool:
    return not DASHBOARD_SECRET or secret == DASHBOARD_SECRET


def _orders_payload() -> str:
    """Fetch all recent orders with items in a single query (no N+1)."""
    from .database import Order as DbOrder
    db = SessionLocal()
    try:
        orders = (
            db.query(DbOrder)
            .options(joinedload(DbOrder.items))
            .order_by(DbOrder.created_at.desc())
            .limit(200)
            .all()
        )
        data = [
            {
                "id":            o.id,
                "status":        o.status,
                "total_amount":  float(o.total_amount),
                "customer_name": o.customer_name,
                "table_number":  o.table_number,
                "customer_note": o.customer_note,
                "created_at":    o.created_at.isoformat() if o.created_at else None,
                "updated_at":    o.updated_at.isoformat() if o.updated_at else None,
                "items": [
                    {
                        "dish_name":      i.dish_name,
                        "quantity":       i.quantity,
                        "dish_price":     float(i.dish_price),
                        "subtotal":       float(i.subtotal),
                        "customizations": i.customizations or {},
                    }
                    for i in o.items
                ],
            }
            for o in orders
        ]
        return json.dumps({"orders": data})
    finally:
        db.close()


# ── chat ──────────────────────────────────────────────────────────────────────

@app.post("/api/chat")
def chat(request: Request, req: ChatRequest):
    if (err := ratelimit.check(request)):
        return err

    started    = time.perf_counter()
    session_id = req.session_id or str(uuid.uuid4())
    history    = [t.model_dump() for t in req.history] if req.history else None
    dishes     = menu.get("dishes", [])
    group      = experiment.group_for(session_id)   # A/B test group, fixed per visitor

    agent = route(req.question, history=history)

    if agent == "order":
        result = handle_order(req.question, dishes, session_id, history=history)

    elif agent == "support":
        result = handle_support(req.question, history=history)

    else:
        cached = None
        if not history:
            cached = response_cache.get(req.question, group)
        if cached:
            result = dict(cached)
            result["cache_hit"] = True
        else:
            result = answer_question(
                req.question, menu, dish_index=dish_index, history=history, group=group
            )
            if result.get("used_llm") and not history:
                response_cache.set(req.question, result, group)

    result["session_id"] = session_id
    result["routed_to"]  = agent
    _track_question(session_id, req.question, agent, result, started, group)
    return result


def _track_question(session_id: str, question: str, agent: str, result: dict,
                    started: float, group: str = "A"):
    """Record the question and, for menu answers, every dish the answer named."""
    dishes = menu.get("dishes", [])
    # Only menu answers count as suggestions. The order agent also names dishes
    # ("added Pani Puri"), but that is confirming a choice, not suggesting one.
    answer = result.get("answer", "")
    named  = events.dishes_mentioned(answer, dishes) if agent == "menu" else []
    # Safety check on our own answers: did this one talk about what guests
    # thought, for dishes that have no real ratings? Caught automatically so the
    # problem shows up on the insights page instead of going unnoticed.
    invented = bool(named) and popularity.unsupported_claim(answer, named)
    rows = [{
        "session_id": session_id,
        "event_type": "question_asked",
        "properties": {
            "question":     question[:500],
            "topic":        events.question_topic(question, dishes, agent),
            "handled_by":   agent,
            "from_cache":   bool(result.get("cache_hit")),
            "response_ms":  round((time.perf_counter() - started) * 1000),
            "dishes_named": len(named),
            "invented_feedback": invented,
            "ab_group":     group if experiment.RUNNING else None,
        },
    }]
    rows += [
        {
            "session_id": session_id,
            "event_type": "dish_suggested",
            "dish_name":  name,
            "properties": {"position": i + 1},
        }
        for i, name in enumerate(named)
    ]
    events.record_many(rows)


# ── cart ──────────────────────────────────────────────────────────────────────

@app.post("/api/cart/update")
def cart_update(req: CartUpdateRequest):
    db = SessionLocal()
    try:
        if req.quantity <= 0:
            cart = cart_ops.remove_item(db, req.session_id, req.dish_name)
        else:
            cart = cart_ops.update_quantity(db, req.session_id, req.dish_name, req.quantity)
        return {"cart": cart, "cart_total": cart_ops.cart_total(cart)}
    finally:
        db.close()


@app.post("/api/cart/checkout")
def cart_checkout(req: CartCheckoutRequest):
    db = SessionLocal()
    try:
        order = cart_ops.checkout(
            db, req.session_id,
            note=req.note or None,
            customer_name=req.customer_name or None,
            table_number=req.table_number or None,
        )
        logger.info(
            "Order placed: %s | %s | Table %s | ₹%s",
            order.id[:8], order.customer_name or "Guest",
            order.table_number or "—", order.total_amount,
        )
        return {
            "order_id":      order.id,
            "total":         float(order.total_amount),
            "status":        order.status,
            "customer_name": order.customer_name,
            "table_number":  order.table_number,
        }
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    finally:
        db.close()


# ── order (customer-facing) ───────────────────────────────────────────────────

@app.post("/api/order/cancel")
def order_cancel(req: OrderCancelRequest):
    from .database import Order as DbOrder
    db = SessionLocal()
    try:
        order = db.query(DbOrder).filter(DbOrder.id == req.order_id).first()
        if not order:
            return JSONResponse(status_code=404, content={"error": "Order not found"})
        if order.session_id != req.session_id:
            return JSONResponse(status_code=403, content={"error": "Not authorized to cancel this order"})
        if order.status != "pending":
            return JSONResponse(
                status_code=400,
                content={"error": f"Cannot cancel — order is already '{order.status}'"},
            )
        order.status     = "cancelled"
        order.updated_at = datetime.utcnow()
        db.commit()
        events.record(order.session_id, "order_cancelled", order_id=order.id, by="customer")
        logger.info("Order %s cancelled by customer", order.id[:8])
        return {"order_id": order.id, "status": order.status}
    finally:
        db.close()


@app.get("/api/order/{order_id}")
def get_order(order_id: str):
    from .database import Order as DbOrder
    db = SessionLocal()
    try:
        order = (
            db.query(DbOrder)
            .options(joinedload(DbOrder.items))
            .filter(DbOrder.id == order_id)
            .first()
        )
        if not order:
            return JSONResponse(status_code=404, content={"error": "Order not found"})
        return {
            "id":            order.id,
            "status":        order.status,
            "total_amount":  float(order.total_amount),
            "customer_name": order.customer_name,
            "table_number":  order.table_number,
            "customer_note": order.customer_note,
            "created_at":    order.created_at.isoformat() if order.created_at else None,
            "items": [
                {
                    "dish_name": i.dish_name,
                    "quantity":  i.quantity,
                    "subtotal":  float(i.subtotal),
                }
                for i in order.items
            ],
            "can_rate": order.status in RATEABLE_STATUSES,
            "ratings":  _ratings_for_order(db, order),
        }
    finally:
        db.close()


# ── ratings ───────────────────────────────────────────────────────────────────

RATEABLE_STATUSES = {"ready", "completed"}


def _ratings_for_order(db, order) -> dict[str, bool]:
    """{dish_name: liked} for every dish already rated on this order."""
    from .database import Event
    rows = (
        db.query(Event)
        .filter(Event.session_id == order.session_id)
        .filter(Event.event_type == "dish_rated")
        .all()
    )
    return {
        r.dish_name: bool((r.properties or {}).get("liked"))
        for r in rows
        if (r.properties or {}).get("order_id") == order.id
    }


@app.post("/api/order/{order_id}/rate")
def rate_order(order_id: str, req: OrderRatingRequest):
    """
    Customer says whether they liked each dish. Allowed once food is ready.
    Knowing the order id is enough: it is a long random value that only the
    customer's tracking link contains. Each dish can be rated once per order.
    """
    from .database import Order as DbOrder
    db = SessionLocal()
    try:
        order = (
            db.query(DbOrder)
            .options(joinedload(DbOrder.items))
            .filter(DbOrder.id == order_id)
            .first()
        )
        if not order:
            return JSONResponse(status_code=404, content={"error": "Order not found"})
        if order.status not in RATEABLE_STATUSES:
            return JSONResponse(
                status_code=400,
                content={"error": "You can rate your food once the order is ready."},
            )

        ordered = {i.dish_name for i in order.items}
        unknown = [r.dish_name for r in req.ratings if r.dish_name not in ordered]
        if unknown:
            return JSONResponse(
                status_code=400,
                content={"error": "Not part of this order: " + ", ".join(unknown)},
            )

        already    = _ratings_for_order(db, order)
        rows, seen = [], set()
        for r in req.ratings:
            if r.dish_name in already or r.dish_name in seen:
                continue
            seen.add(r.dish_name)
            rows.append({
                "session_id": order.session_id,
                "event_type": "dish_rated",
                "dish_name":  r.dish_name,
                "properties": {
                    "order_id":      order.id,
                    "liked":         r.liked,
                    "was_suggested": events.was_suggested(order.session_id, r.dish_name),
                },
            })
        events.record_many(rows)
        return {"order_id": order.id, "ratings": _ratings_for_order(db, order)}
    finally:
        db.close()


# ── insights (owner-facing) ───────────────────────────────────────────────────

@app.get("/api/insights")
def get_insights(source: str = "live", secret: str | None = None):
    if not _dashboard_auth_ok(secret):
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    if source not in ("live", "demo"):
        return JSONResponse(status_code=400, content={"error": "source must be live or demo"})
    db = SessionLocal()
    try:
        return insights.build(db, menu.get("dishes", []), source=source)
    finally:
        db.close()


@app.get("/api/order/{order_id}/stream")
async def order_status_stream(order_id: str, request: Request):
    """SSE — pushes status updates to the customer tracking page."""
    def _get_status() -> str | None:
        from .database import Order as DbOrder
        db = SessionLocal()
        try:
            o = db.query(DbOrder).filter(DbOrder.id == order_id).first()
            return o.status if o else None
        finally:
            db.close()

    async def generator():
        last           = None
        last_heartbeat = asyncio.get_event_loop().time()
        while True:
            if await request.is_disconnected():
                break
            now = asyncio.get_event_loop().time()
            if now - last_heartbeat >= 25:
                yield ": ping\n\n"   # keeps connection alive through proxies/firewalls
                last_heartbeat = now
            status = await asyncio.to_thread(_get_status)
            if status is None:
                yield f"data: {json.dumps({'error': 'not found'})}\n\n"
                break
            if status != last:
                last = status
                yield f"data: {json.dumps({'status': status})}\n\n"
            if status in ("completed", "cancelled"):
                break
            await asyncio.sleep(3)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── orders (kitchen dashboard) ────────────────────────────────────────────────

@app.get("/api/orders")
def get_orders(secret: str | None = None):
    if not _dashboard_auth_ok(secret):
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    return json.loads(_orders_payload())


@app.get("/api/orders/stream")
async def orders_stream(request: Request, secret: str | None = None):
    """SSE — pushes the full order list to the kitchen dashboard every 2 s."""
    if not _dashboard_auth_ok(secret):
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})

    async def generator():
        last_heartbeat = asyncio.get_event_loop().time()
        while True:
            if await request.is_disconnected():
                break
            now = asyncio.get_event_loop().time()
            if now - last_heartbeat >= 25:
                yield ": ping\n\n"
                last_heartbeat = now
            payload = await asyncio.to_thread(_orders_payload)
            yield f"data: {payload}\n\n"
            await asyncio.sleep(2)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.patch("/api/orders/{order_id}/status")
def update_order_status(
    order_id: str,
    req: StatusUpdateRequest,
    secret: str | None = None,
):
    if not _dashboard_auth_ok(secret):
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    from .database import Order as DbOrder
    db = SessionLocal()
    try:
        order = db.query(DbOrder).filter(DbOrder.id == order_id).first()
        if not order:
            return JSONResponse(status_code=404, content={"error": "Order not found"})
        allowed = ALLOWED_TRANSITIONS.get(order.status, [])
        if req.status not in allowed:
            return JSONResponse(
                status_code=400,
                content={"error": f"Cannot transition '{order.status}' → '{req.status}'"},
            )
        old_status       = order.status
        order.status     = req.status
        order.updated_at = datetime.utcnow()
        db.commit()
        events.record(
            order.session_id, "order_status_changed",
            order_id=order.id, **{"from": old_status, "to": req.status},
        )
        if req.status == "cancelled":
            events.record(order.session_id, "order_cancelled", order_id=order.id, by="kitchen")
        logger.info("Order %s: %s → %s", order_id[:8], old_status, req.status)
        return {"order_id": order.id, "status": order.status}
    finally:
        db.close()


# ── health ────────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {
        "restaurant":      menu.get("restaurant"),
        "dish_count":      len(menu.get("dishes", [])),
        "llm_configured":  llm_configured(),
        "index_ready":     dish_index is not None,
        "cache":           response_cache.stats(),
        "auth_enabled":    bool(DASHBOARD_SECRET),
        "allowed_origins": ALLOWED_ORIGINS,
    }


# ── background tasks ──────────────────────────────────────────────────────────

async def _session_cleanup_loop():
    """Prune orphan sessions (no orders, last active > 24 h) hourly."""
    while True:
        await asyncio.sleep(3600)
        try:
            await asyncio.to_thread(_do_session_cleanup)
        except Exception as e:
            logger.error("Session cleanup error: %s", e)


def _do_session_cleanup():
    from .database import DbSession, Order as DbOrder
    cutoff = datetime.utcnow() - timedelta(hours=24)
    db = SessionLocal()
    try:
        orphans = (
            db.query(DbSession)
            .outerjoin(DbOrder, DbSession.id == DbOrder.session_id)
            .filter(DbSession.updated_at < cutoff)
            .filter(DbOrder.id.is_(None))
            .all()
        )
        count = len(orphans)
        for sess in orphans:
            db.delete(sess)
        db.commit()
        if count:
            logger.info("Session cleanup: pruned %d orphan sessions", count)
    except Exception:
        db.rollback()
    finally:
        db.close()


# ── static files (must be last) ───────────────────────────────────────────────

app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
