"""
Start Savora on Hugging Face Spaces (free plan).

Hugging Face's free plan runs this file and expects a website on port 7860.
It doesn't need to be a Gradio app, so this simply starts Savora's own web
server there, with settings suited to a public demo.

The AI key is NOT here: add it in the Space's settings as a secret named
OPENROUTER_API_KEY.

To run on your own laptop, use run_local.py instead.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./savora.db")  # resets when the Space restarts
os.environ.setdefault("SEED_DEMO_DATA", "1")        # fill the Insights page with labelled practice data
os.environ.setdefault("DAILY_CHAT_LIMIT", "300")    # cap on chat messages per day, to protect the AI key
os.environ.setdefault("ALLOWED_ORIGINS", "*")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "backend.app:app",
        host="0.0.0.0",
        port=7860,
        # See each visitor's real address behind Hugging Face's front door,
        # so the per-visitor message limit works.
        proxy_headers=True,
        forwarded_allow_ips="*",
    )
