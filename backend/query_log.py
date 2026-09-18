"""
Append-only log of every question and which path answered it (structured /
cache / llm), so you can see over time what fraction of traffic is free vs
paid, and spot recurring LLM questions worth turning into a new structured
filter rule instead.
"""
import json
import time
from pathlib import Path

LOG_PATH = Path(__file__).parent.parent / "logs" / "queries.jsonl"


def log_query(question: str, route: str, latency_ms: float, detail: dict | None = None) -> None:
    LOG_PATH.parent.mkdir(exist_ok=True)
    entry = {
        "ts": time.time(),
        "question": question,
        "route": route,  # "structured" | "cache" | "llm"
        "latency_ms": round(latency_ms, 1),
        **(detail or {}),
    }
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
