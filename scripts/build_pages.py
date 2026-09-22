"""
Build the GitHub Pages website in the docs/ folder.

    python scripts/build_pages.py

GitHub Pages can only host plain files, with no server behind them. So the
chat (which needs a server and an AI key) can't run there. What it can host:

  docs/index.html          the project page (written by hand, not touched here)
  docs/insights.html       the real Insights dashboard, copied from frontend/
  docs/insights.js         ...and its script
  docs/insights-demo.json  a snapshot of the dashboard's numbers, made from
                           practice data in a throwaway database

Your real data and savora_local.db are never read or changed.
Run this again whenever the dashboard changes, then commit and push.
"""
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

# A brand-new throwaway database, set before any app code loads.
_tmp = tempfile.mkdtemp(prefix="savora_pages_")
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_tmp, 'pages.db').as_posix()}"
sys.path.insert(0, str(ROOT))

from backend import insights                 # noqa: E402
from backend.data import load_menu           # noqa: E402
from backend.database import SessionLocal    # noqa: E402


def main():
    DOCS.mkdir(exist_ok=True)

    # 1. Practice data, then the same numbers the live dashboard would show.
    spec = importlib.util.spec_from_file_location("demo_data", ROOT / "scripts" / "demo_data.py")
    demo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(demo)
    demo.generate()

    db = SessionLocal()
    try:
        snapshot = insights.build(db, load_menu()["dishes"], source="demo")
    finally:
        db.close()
    (DOCS / "insights-demo.json").write_text(json.dumps(snapshot, indent=1), encoding="utf-8")

    # 2. The dashboard page, switched into "no server" mode.
    page = (ROOT / "frontend" / "insights.html").read_text(encoding="utf-8")
    marker = '<script src="insights.js'
    assert marker in page, "insights.html no longer loads insights.js as expected"
    page = page.replace(marker, "<script>window.SAVORA_STATIC = true;</script>\n" + marker, 1)
    (DOCS / "insights.html").write_text(page, encoding="utf-8")
    (DOCS / "insights.js").write_text(
        (ROOT / "frontend" / "insights.js").read_text(encoding="utf-8"), encoding="utf-8")

    # 3. Tell GitHub Pages to serve files as they are.
    (DOCS / ".nojekyll").write_text("", encoding="utf-8")

    print(f"Built docs/ with {snapshot['headline']['customers']} practice visitors.")
    print("Commit and push, then turn on Pages: Settings > Pages > main branch, /docs folder.")


if __name__ == "__main__":
    main()
