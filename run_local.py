"""
Run Savora on your own computer with a local database file.

    python run_local.py

Why this exists: .env points the app at an online Supabase database. When that
project is paused (free projects pause after a week unused), the app can't
start. This launcher uses a local file, savora_local.db, instead — without
editing .env, so switching back to Supabase later needs no changes.

Everything else (AI answers, kitchen board, insights page) works the same.
Then open:
    http://127.0.0.1:8000                  customer chat
    http://127.0.0.1:8000/dashboard.html   kitchen board
    http://127.0.0.1:8000/insights.html    insights
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)

# Set before the app loads .env. load_dotenv never overrides a variable that
# already exists, so this local database wins over the Supabase address.
os.environ["DATABASE_URL"] = f"sqlite:///{(ROOT / 'savora_local.db').as_posix()}"

# Use the already-downloaded embedding model instead of checking the internet
# for a newer copy on every start. Without this, startup can hang for minutes
# on a slow or restricted connection. Delete these two lines if you ever want
# to pull a fresh model.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.app:app", host="127.0.0.1", port=8000)
