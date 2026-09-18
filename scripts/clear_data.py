"""
Delete tracked data so you can start a fresh round of testing.

    python scripts/clear_data.py --demo    # remove pretend customers only
    python scripts/clear_data.py --real    # remove real activity: events, orders, carts
    python scripts/clear_data.py --all     # remove both

Nothing is deleted unless you pass one of those flags, and you are asked to
confirm before real data goes. Add --yes to skip the confirmation.

--real also removes orders and shopping carts, so the kitchen board starts empty
too. This cannot be undone, so take a copy of savora_local.db first if unsure.
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ.setdefault("DATABASE_URL", f"sqlite:///{(ROOT / 'savora_local.db').as_posix()}")

from backend.database import (  # noqa: E402
    DbSession, Event, Order, OrderItem, SessionLocal, init_db,
)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--demo", action="store_true", help="delete pretend (demo) data")
    ap.add_argument("--real", action="store_true", help="delete real activity, orders and carts")
    ap.add_argument("--all",  action="store_true", help="delete both")
    ap.add_argument("--yes",  action="store_true", help="don't ask for confirmation")
    args = ap.parse_args()

    demo = args.demo or args.all
    real = args.real or args.all
    if not (demo or real):
        ap.print_help()
        return

    init_db()
    db = SessionLocal()
    try:
        if demo:
            n = db.query(Event).filter(Event.source == "demo").delete()
            db.commit()
            print(f"Deleted {n} demo events.")

        if real:
            counts = {
                "events":      db.query(Event).filter(Event.source == "live").count(),
                "orders":      db.query(Order).count(),
                "order items": db.query(OrderItem).count(),
                "sessions":    db.query(DbSession).count(),
            }
            print("About to permanently delete:")
            for name, n in counts.items():
                print(f"  {n:>6}  {name}")
            if not any(counts.values()):
                print("Nothing to delete.")
                return
            if not args.yes and input('Type "delete" to confirm: ').strip().lower() != "delete":
                print("Cancelled. Nothing was deleted.")
                return
            db.query(Event).filter(Event.source == "live").delete()
            db.query(OrderItem).delete()
            db.query(Order).delete()
            db.query(DbSession).delete()
            db.commit()
            print("Real data deleted.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
