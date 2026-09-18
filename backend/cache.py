"""
Two-layer answer cache for stateless (no-history) questions.

Layer 1: exact normalized-text match   — instant, no embedding
Layer 2: semantic match via embeddings — catches paraphrases like
         "what's good for a date" ≈ "what would you recommend for a first date"

Deliberately not used for follow-up questions (ones with history), since those
depend on conversation context and reusing a cached answer would be wrong.

Answers are also kept separate per A/B test group. Otherwise an answer written
for group B could be served to someone in group A, and the two groups would no
longer be seeing different versions — which would quietly ruin the test.
"""
import re
import time

import numpy as np

from . import embeddings

_TTL_SECONDS = 60 * 60 * 6   # 6 h — long enough to matter, short enough that menu edits aren't stuck
_SIMILARITY_THRESHOLD = 0.86  # tuned: paraphrase pair ~0.88, unrelated pair ~-0.07

_store: dict[tuple[str, str], dict] = {}  # (group, normalized_text) → {ts, embedding, payload}


def _normalize(question: str) -> str:
    q = question.lower().strip()
    q = re.sub(r"[^a-z0-9 ]", "", q)
    return re.sub(r"\s+", " ", q)


def _prune_expired() -> None:
    now = time.time()
    expired = [k for k, v in _store.items() if now - v["ts"] > _TTL_SECONDS]
    for k in expired:
        del _store[k]


def get(question: str, group: str = "A") -> dict | None:
    _prune_expired()
    key = (group, _normalize(question))

    # Layer 1: exact match — no embedding needed
    hit = _store.get(key)
    if hit:
        return hit["payload"]

    keys = [k for k in _store if k[0] == group]
    if not keys:
        return None

    # Layer 2: vectorized cosine — one matrix multiply instead of a Python loop
    query_vec = embeddings.embed(question)
    matrix = np.stack([_store[k]["embedding"] for k in keys])  # (n, dim)
    scores = matrix @ query_vec                                  # (n,)
    best_idx = int(np.argmax(scores))
    if scores[best_idx] >= _SIMILARITY_THRESHOLD:
        return _store[keys[best_idx]]["payload"]
    return None


def set(question: str, payload: dict, group: str = "A") -> None:
    _store[(group, _normalize(question))] = {
        "ts": time.time(),
        "embedding": embeddings.embed(question),
        "payload": payload,
    }


def stats() -> dict:
    return {"cached_questions": len(_store)}
