"""
Local, free embeddings — no OpenRouter/API call involved.
Model loads once (lazily, on first use) and stays in memory.
"""
import numpy as np

_model = None


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


def embed(text: str) -> np.ndarray:
    return _get_model().encode(text, normalize_embeddings=True)


def embed_batch(texts: list[str]) -> list[np.ndarray]:
    """Encode a list of texts in one batched forward pass — much faster than
    looping embed() when building the dish index at startup."""
    model = _get_model()
    vecs = model.encode(texts, normalize_embeddings=True, batch_size=32, show_progress_bar=False)
    return list(vecs)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))
