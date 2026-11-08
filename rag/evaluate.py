"""Score the Docs Q&A agent on a golden set.

    python -m rag.evaluate                       # eval/golden.jsonl
    python -m rag.evaluate --limit 3             # quick smoke run
    python -m rag.evaluate --json eval/last.json

Retrieval metrics need no LLM judge and show whether chunking + search work:
  hit@5 (hybrid)   is the evidence in the top 5 hybrid results?
  hit@5 (rerank)   ...and after LLM reranking? (the reranker's uplift)
  MRR              how high does the first relevant passage rank?
  context precision  share of the kept passages that come from the right document
Answer metrics (LLM-judged, each judge is a separate call):
  correct, relevant, faithful, citation validity, and refusal accuracy for
  questions the documents cannot answer.
"""
import argparse
import json
import re
from pathlib import Path

from memory.llm_tasks import parse_json
from pydantic import BaseModel

from .agent import ask, extract_citations
from .config import DEFAULT_COLLECTION, RERANK_TOP_N
from .llm import chat, make_client
from .rerank import rerank
from .search import hybrid_search
from .store import RagStore

JUDGE_SYSTEM = (
    "You grade an answer to a question. EXPECTED lists the facts a correct answer "
    "must convey. Go through each expected fact and list the ones the ANSWER does "
    "not convey (missing_facts). Extra correct detail beyond EXPECTED is fine and "
    "is NOT a problem. Set contradicts=true only if the answer states something "
    "that conflicts with an expected fact. relevant = the answer addresses the "
    'question asked. Return ONLY JSON: {"missing_facts": ["..."], '
    '"contradicts": true|false, "relevant": true|false}'
)
FAITHFUL_SYSTEM = (
    "You check faithfulness. faithful = every factual claim in the ANSWER is "
    "supported by the PASSAGES. Ignore wording and formatting. "
    'Return ONLY JSON: {"faithful": true|false}'
)


class _Judge(BaseModel):
    missing_facts: list[str] = []
    contradicts: bool = False
    relevant: bool

    @property
    def correct(self) -> bool:  # decided in code from the judge's findings
        return not self.missing_facts and not self.contradicts


class _Faithful(BaseModel):
    faithful: bool


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower())


def contains(chunks: list[dict], evidence: str) -> int | None:
    """1-based rank of the first chunk containing the evidence string."""
    for i, c in enumerate(chunks, start=1):
        if _norm(evidence) in _norm(c["text"]):
            return i
    return None


def evaluate_one(client, store, item: dict, collection: str) -> dict:
    row = {"id": item["id"], "answerable": item["answerable"]}
    result = ask(client, store, item["question"], collection=collection)
    answer = result["answer"]
    row.update(refused=result["refused"], tokens=result["tokens"],
               attempts=result["attempt"])

    cited = extract_citations(answer)
    row["citations_valid"] = all(c in result["evidence"] for c in cited)

    if not item["answerable"]:
        row["refusal_correct"] = result["refused"]
        return row

    # --- retrieval (independent of what the agent chose to search for) ---
    hits = hybrid_search(client, store, item["question"], collection)
    reranked = rerank(client, item["question"], hits)
    top_hybrid = hits[:RERANK_TOP_N]
    row["hit_hybrid"] = contains(top_hybrid, item["evidence"]) is not None
    rank = contains(reranked, item["evidence"])
    row["hit_rerank"] = rank is not None
    row["rr"] = 1 / rank if rank else 0.0
    row["context_precision"] = (
        sum(h["source"] == item["expected_source"] for h in reranked) / len(reranked)
        if reranked else 0.0)

    # --- answer quality ---
    if result["refused"]:
        row.update(correct=False, relevant=False, faithful=None)
        return row
    judged = parse_json(chat(client, JUDGE_SYSTEM,
        f"QUESTION: {item['question']}\n\nEXPECTED: {item['key_facts']}\n\nANSWER:\n{answer}"), _Judge)
    row["correct"] = bool(judged and judged.correct)
    row["relevant"] = bool(judged and judged.relevant)
    if judged and not judged.correct:
        row["why_wrong"] = judged.missing_facts or ["contradicts the expected facts"]
    passages = "\n\n".join(f"[{c}]\n{result['evidence'][c]['text']}"
                           for c in cited if c in result["evidence"])
    verdict = parse_json(chat(client, FAITHFUL_SYSTEM,
        f"PASSAGES:\n{passages}\n\nANSWER:\n{answer}"), _Faithful)
    row["faithful"] = bool(verdict and verdict.faithful)
    return row


def rate(rows, key):
    vals = [r[key] for r in rows if r.get(key) is not None]
    return f"{sum(vals) / len(vals):.0%} ({sum(bool(v) for v in vals)}/{len(vals)})" if vals else "n/a"


def summarise(rows: list[dict]) -> str:
    ans = [r for r in rows if r["answerable"]]
    unans = [r for r in rows if not r["answerable"]]
    mrr = sum(r["rr"] for r in ans) / len(ans) if ans else 0
    cp = sum(r["context_precision"] for r in ans) / len(ans) if ans else 0
    lines = [
        f"Questions: {len(rows)} ({len(ans)} answerable, {len(unans)} not in the docs)", "",
        "RETRIEVAL (answerable questions)",
        f"  hit@5 hybrid only      {rate(ans, 'hit_hybrid')}",
        f"  hit@5 after rerank     {rate(ans, 'hit_rerank')}",
        f"  MRR (after rerank)     {mrr:.2f}",
        f"  context precision      {cp:.0%}   (kept passages from the right document)", "",
        "ANSWERS",
        f"  correct                {rate(ans, 'correct')}",
        f"  answer relevance       {rate(ans, 'relevant')}",
        f"  faithfulness           {rate(ans, 'faithful')}   (answered questions only)",
        f"  citations valid        {rate(rows, 'citations_valid')}",
        f"  correct refusals       {rate(unans, 'refusal_correct')}   (questions the docs can't answer)", "",
        f"  avg tokens / question  {sum(r['tokens'] for r in rows) / len(rows):,.0f}",
        f"  questions that retried {sum(r['attempts'] > 1 for r in rows)}",
    ]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", type=Path, default=Path("eval/golden.jsonl"))
    ap.add_argument("--collection", default=DEFAULT_COLLECTION)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--json", type=Path, help="write per-question results here")
    a = ap.parse_args()

    items = [json.loads(l) for l in a.file.read_text().splitlines() if l.strip()][:a.limit]
    client, store = make_client(), RagStore()
    rows = []
    print(f"{'question':<20}{'retrieval':<12}{'answer':<10}{'tokens':>8}")
    for item in items:
        r = evaluate_one(client, store, item, a.collection)
        rows.append(r)
        if r["answerable"]:
            ret = "hit" if r["hit_rerank"] else "MISS"
            ans = "ok" if r["correct"] else ("refused" if r["refused"] else "WRONG")
            if r.get("why_wrong"):
                print(f"{'':<20}  ↳ missing: {'; '.join(r['why_wrong'])[:100]}")
        else:
            ret, ans = "-", "ok" if r["refusal_correct"] else "ANSWERED"
        print(f"{r['id']:<20}{ret:<12}{ans:<10}{r['tokens']:>8,}")
    print("\n" + summarise(rows))
    if a.json:
        a.json.write_text(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
