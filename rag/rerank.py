"""LLM-based reranking: a cheap model scores each candidate passage against
the question. Swap this function for a cross-encoder later without touching
anything else."""
from memory.llm_tasks import parse_json
from pydantic import BaseModel

from .config import MIN_RERANK_SCORE, RERANK_TOP_N
from .llm import chat

SNIPPET_CHARS = 900

RERANK_SYSTEM = (
    "You rank passages for a search question. Score every passage from 0 to 10 "
    "for how directly it helps answer the question: 10 = contains the answer, "
    "5 = related background, 0 = irrelevant. Judge only the passage text. "
    'Return ONLY JSON: {"scores": [{"id": <passage number>, "score": <0-10>}, ...]} '
    "covering every passage."
)


class _Scores(BaseModel):
    scores: list[dict]


def rerank(client, query: str, hits: list[dict], top_n: int = RERANK_TOP_N,
           min_score: float = MIN_RERANK_SCORE, usage: dict | None = None) -> list[dict]:
    """Return the best `top_n` hits, each with a `rerank_score`, dropping
    passages scored below `min_score`. If the model's reply is unusable, fall
    back to the original (hybrid) order so search never breaks."""
    if not hits:
        return []
    passages = "\n\n".join(
        f"[{i}] ({h['source']}" + (f" > {h['heading']}" if h.get("heading") else "") + ")\n"
        + h["text"][:SNIPPET_CHARS]
        for i, h in enumerate(hits, start=1))
    reply = chat(client, RERANK_SYSTEM, f"Question: {query}\n\nPassages:\n{passages}", usage)
    parsed = parse_json(reply, _Scores)

    scores: dict[int, float] = {}
    if parsed:
        for item in parsed.scores:
            try:
                scores[int(item["id"])] = float(item["score"])
            except (KeyError, TypeError, ValueError):
                continue
    if not scores:
        return [dict(h, rerank_score=None) for h in hits[:top_n]]

    ranked = sorted(
        ((scores.get(i, 0.0), -i, h) for i, h in enumerate(hits, start=1)),
        key=lambda t: (t[0], t[1]), reverse=True)  # ties keep the hybrid order
    return [dict(h, rerank_score=s) for s, _, h in ranked if s >= min_score][:top_n]
