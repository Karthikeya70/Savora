# Recipe for running Savora on a server (used by Hugging Face Spaces).
#
# Builds a small Linux machine with Python, installs the app, downloads the
# AI model that finds relevant dishes, and starts the web server.

FROM python:3.11-slim

# Hugging Face runs apps as a normal user (id 1000), not as admin.
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1
WORKDIR /home/user/app

# The CPU-only version of torch is far smaller than the default GPU one,
# and the free server has no GPU anyway.
RUN pip install --no-cache-dir --user torch --index-url https://download.pytorch.org/whl/cpu

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Download the dish-matching model now, while building, so the site doesn't
# have to fetch it every time it wakes up.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

COPY --chown=user . .

# Settings for the public demo. The AI key is NOT here: add it as a secret
# named OPENROUTER_API_KEY in the Space's settings.
ENV DATABASE_URL=sqlite:////home/user/app/savora.db \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    SEED_DEMO_DATA=1 \
    DAILY_CHAT_LIMIT=300 \
    ALLOWED_ORIGINS=*

EXPOSE 7860

# --proxy-headers lets the app see each visitor's real address behind
# Hugging Face's front door, so the per-visitor limit works.
CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "7860", "--proxy-headers", "--forwarded-allow-ips", "*"]
