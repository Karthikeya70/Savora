"""
Precomputed dish embedding index for fast semantic retrieval.

At startup, each dish gets an embedding built from its combined text fields
(name, description, category, tags, ingredients, aliases). Incoming queries
can then retrieve the top-k most semantically relevant dishes in ~1 ms via a
single numpy matrix multiply — no API call, no cost.

This powers the LLM tier: instead of having the model blindly guess which tool
arguments to call for vague queries ("comfort food", "date night", "something
light and refreshing"), we pre-load the relevant dishes as context so the LLM
can answer in one focused call rather than 2–4 tool-calling rounds.
"""
import numpy as np

from . import embeddings


def _dish_text(dish: dict) -> str:
    """Build a rich, searchable text blob for one dish."""
    price = dish.get("price_inr")
    cal = dish.get("approx_calories_kcal")
    parts = [
        dish.get("name", ""),
        dish.get("description", ""),
        dish.get("category", ""),
        dish.get("spice", ""),
        dish.get("preparation_method", ""),
        "dietary tags: " + ", ".join(dish.get("dietary_tags", [])),
        "badges: " + ", ".join(dish.get("badges", [])),
        "ingredients: " + ", ".join(
            i.get("ingredient", "") for i in dish.get("ingredients", [])
        ),
        "also known as: " + ", ".join(dish.get("also_known_as") or []),
        # Price and calorie strings let the embedding pick up superlative queries
        # ("cheapest", "most expensive", "lowest calorie") more reliably.
        f"price: {price} rupees" if price is not None else "",
        f"calories: {cal} kcal" if cal is not None else "",
    ]
    return ". ".join(p for p in parts if p.strip(". "))


class DishIndex:
    """Wraps a numpy embedding matrix for fast top-k dish retrieval."""

    def __init__(self, dishes: list[dict]):
        self.dishes = dishes
        texts = [_dish_text(d) for d in dishes]
        # encode all dishes in one batched call — much faster than looping
        vecs = embeddings.embed_batch(texts)
        # shape: (n_dishes, embedding_dim) — vecs are already L2-normalised
        self._matrix = np.stack(vecs)

    def top_k(self, query_vec: np.ndarray, k: int = 6) -> list[dict]:
        """Return the k dishes most semantically similar to query_vec.

        query_vec must be L2-normalised (as returned by embeddings.embed) so
        that the dot product equals cosine similarity.
        """
        scores = self._matrix @ query_vec          # (n_dishes,)
        top_indices = np.argsort(scores)[::-1][:k]
        return [self.dishes[int(i)] for i in top_indices]
