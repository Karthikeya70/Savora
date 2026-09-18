"""
Database setup using SQLAlchemy.

Currently uses SQLite (zero install, works immediately).
To switch to PostgreSQL for production, change DATABASE_URL to:
  postgresql://user:password@localhost/savora
and install psycopg2:  pip install psycopg2-binary
Everything else stays identical.
"""
import os
import uuid
from datetime import datetime

from sqlalchemy import (
    Column, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, create_engine
)
from sqlalchemy.orm import DeclarativeBase, Session, relationship, sessionmaker

try:
    from sqlalchemy import JSON
except ImportError:
    from sqlalchemy import Text as JSON  # fallback for older SQLite versions


DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./savora.db")

if DATABASE_URL.startswith("sqlite"):
    # SQLite — single-file, dev only
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
    )
else:
    # PostgreSQL / Supabase
    # sslmode=require is enforced via connect_args so you don't need to add
    # it to DATABASE_URL manually — Supabase rejects unencrypted connections.
    engine = create_engine(
        DATABASE_URL,
        pool_size=5,        # persistent connections (Supabase free tier: 25 limit)
        max_overflow=5,     # max 10 total — leaves headroom for other clients
        pool_pre_ping=True, # test connection before use — survives DB restarts
        pool_recycle=3600,  # recycle connections every hour
        connect_args={"sslmode": "require"},
    )
SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass


# ── models ────────────────────────────────────────────────────────────────────

class DbSession(Base):
    """One chat session = one customer conversation."""
    __tablename__ = "sessions"

    id             = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    table_number   = Column(String, nullable=True)
    customer_name  = Column(String, nullable=True)
    cart           = Column(JSON, default=list)   # live cart before checkout
    created_at     = Column(DateTime, default=datetime.utcnow)
    updated_at     = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    orders = relationship("Order", back_populates="session")


class Order(Base):
    """A placed order — snapshot of the cart at checkout time."""
    __tablename__ = "orders"

    id              = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id      = Column(String, ForeignKey("sessions.id"), nullable=False)
    status          = Column(String, default="pending")   # pending → confirmed → preparing → ready → completed
    total_amount    = Column(Numeric(10, 2), nullable=False)
    customer_name   = Column(String, nullable=True)
    table_number    = Column(String, nullable=True)
    customer_note   = Column(Text, nullable=True)
    created_at      = Column(DateTime, default=datetime.utcnow)
    updated_at      = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    session = relationship("DbSession", back_populates="orders")
    items   = relationship("OrderItem", back_populates="order")


class OrderItem(Base):
    """One line item inside an order."""
    __tablename__ = "order_items"

    id              = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    order_id        = Column(String, ForeignKey("orders.id"), nullable=False)
    dish_name       = Column(String, nullable=False)
    dish_price      = Column(Numeric(10, 2), nullable=False)
    quantity        = Column(Integer, default=1)
    customizations  = Column(JSON, default=dict)  # {"add": ["extra chutney"], "reduce": ["butter"]}
    subtotal        = Column(Numeric(10, 2), nullable=False)

    order = relationship("Order", back_populates="items")


class Event(Base):
    """
    One row per thing a customer did — a diary of the whole visit.

    event_type is one of:
      question_asked         customer typed a question
      dish_suggested         the assistant named a dish in its answer (one row per dish)
      cart_added             a dish went into the cart
      cart_removed           a dish came out of the cart
      order_placed           checkout finished
      order_cancelled        customer or kitchen cancelled
      order_status_changed   kitchen moved the order along
      dish_rated             customer said they liked / didn't like a dish

    source separates real visits ("live") from generated practice data ("demo"),
    so the two are never mixed up in the insights page.
    """
    __tablename__ = "events"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    session_id = Column(String, nullable=False)
    event_type = Column(String, nullable=False)
    dish_name  = Column(String, nullable=True)
    properties = Column(JSON, default=dict)
    source     = Column(String, default="live", nullable=False)

    __table_args__ = (
        Index("ix_events_source_type", "source", "event_type"),
        Index("ix_events_session", "session_id"),
    )


# ── helpers ───────────────────────────────────────────────────────────────────

def init_db():
    """Create all tables. Safe to call multiple times (no-op if tables exist)."""
    Base.metadata.create_all(bind=engine)
    # Add columns introduced after initial deployment — IF NOT EXISTS is idempotent.
    if not DATABASE_URL.startswith("sqlite"):
        from sqlalchemy import text
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE orders ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP"
            ))


def get_db() -> Session:
    """Dependency for FastAPI routes — yields a session and closes it after."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
