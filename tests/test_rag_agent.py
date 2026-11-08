"""The RAG agent with a scripted LLM and an in-memory store (no network)."""
import json
from types import SimpleNamespace as NS

from rag.agent import extract_citations, is_refusal, ask
from rag.config import MAX_RETRIES, REFUSAL
from rag.rerank import rerank

from fakes import fake_embedding

PASSAGE = {"id": 1, "source": "runbook.md", "chunk_index": 0, "page": None,
           "heading": "Rollback", "text": "A rollback takes 3 minutes.",
           "score": 0.03, "vec_rank": 1, "kw_rank": 1}


class FakeStore:
    def __init__(self, rows=None):
        self.rows = [PASSAGE] if rows is None else rows

    def hybrid(self, collection, query_embedding, query_text, n):
        return [dict(r) for r in self.rows]


class FakeClient:
    """answers: what the answer model says on attempt 1, 2, ... (last repeats).
    judge_grounded: what the verifier says about cited answers."""

    def __init__(self, answers, judge_grounded=True, rerank_score=10, search=True):
        self.answers, self.judge_grounded = answers, judge_grounded
        self.rerank_score, self.search = rerank_score, search
        self.attempt = 0
        self.calls = []
        self.embeddings = NS(create=lambda model, input: NS(
            data=[NS(index=i, embedding=fake_embedding(t)) for i, t in enumerate(input)]))
        self.chat = NS(completions=NS(create=self._chat))

    def _reply(self, content=None, tool_calls=None):
        return NS(choices=[NS(message=NS(content=content, tool_calls=tool_calls))],
                  usage=NS(total_tokens=10))

    def _chat(self, model, messages, tools=None, temperature=None):
        system = messages[0]["content"]
        if system.startswith("You are a documentation assistant"):
            if messages[-1]["role"] != "tool" and self.search:
                self.attempt += 1
                self.calls.append("answer-search")
                call = NS(id=f"c{self.attempt}", function=NS(
                    name="search_docs", arguments=json.dumps({"query": "rollback time"})))
                return self._reply(tool_calls=[call])
            if messages[-1]["role"] != "tool":
                self.attempt += 1
            self.calls.append("answer-final")
            return self._reply(self.answers[min(self.attempt, len(self.answers)) - 1])
        if system.startswith("You rank passages"):
            self.calls.append("rerank")
            n = system and sum(1 for m in messages[1]["content"].split("\n") if m.startswith("["))
            return self._reply(json.dumps({"scores": [
                {"id": i, "score": self.rerank_score} for i in range(1, n + 1)]}))
        if system.startswith("You verify answers"):
            self.calls.append("verify")
            return self._reply(json.dumps({"grounded": self.judge_grounded,
                                           "unsupported_claims": [] if self.judge_grounded else ["it takes 3 minutes"]}))
        raise AssertionError(system[:40])


def test_citation_helpers():
    assert extract_citations("A [a.md#1] and B [b.md#2][a.md#1] but [link](x) and [note]") == ["a.md#1", "b.md#2"]
    assert is_refusal(REFUSAL) and is_refusal(REFUSAL + " (details)")
    assert not is_refusal("Rollbacks take 3 minutes [runbook.md#0].")


def test_grounded_answer_first_try():
    client = FakeClient(["A rollback takes 3 minutes [runbook.md#0]."])
    r = ask(client, FakeStore(), "How long does a rollback take?")
    assert r["grounded"] and not r["refused"] and r["attempt"] == 1
    assert r["cited"] == ["runbook.md#0"]
    assert "verify" in client.calls and r["tokens"] > 0
    search = next(t for t in r["trace"] if t["step"] == "search")
    assert search["kept"] == [("runbook.md#0", 10)]


def test_invented_citation_triggers_retry_then_succeeds():
    client = FakeClient(["It takes 3 minutes [runbook.md#9].",      # never retrieved
                         "It takes 3 minutes [runbook.md#0]."])
    r = ask(client, FakeStore(), "How long does a rollback take?")
    assert r["attempt"] == 2 and r["grounded"] and r["cited"] == ["runbook.md#0"]
    first_verify = next(t for t in r["trace"] if t["step"] == "verify")
    assert first_verify["invalid_citations"] == ["runbook.md#9"]


def test_no_citation_means_no_answer():
    client = FakeClient(["It takes about 3 minutes."])               # never cites
    r = ask(client, FakeStore(), "How long does a rollback take?")
    assert r["attempt"] == MAX_RETRIES + 1                           # retried, then gave up
    assert r["refused"] and not r["grounded"]
    assert r["answer"].startswith(REFUSAL) and r["cited"] == []


def test_honest_refusal_is_accepted_without_a_judge_call():
    client = FakeClient([REFUSAL], rerank_score=0)                   # nothing relevant
    r = ask(client, FakeStore(), "What is the parental leave policy?")
    assert r["refused"] and r["grounded"] and r["attempt"] == 1
    assert "verify" not in client.calls
    search = next(t for t in r["trace"] if t["step"] == "search")
    assert search["kept"] == []                                      # reranker dropped everything


def test_cited_but_unverified_answer_is_returned_with_a_flag():
    client = FakeClient(["It takes 3 minutes [runbook.md#0]."], judge_grounded=False)
    r = ask(client, FakeStore(), "How long does a rollback take?")
    assert r["attempt"] == MAX_RETRIES + 1
    assert not r["grounded"] and not r["refused"]                    # UI shows a warning
    assert r["cited"] == ["runbook.md#0"] and r["issues"]


def test_rerank_orders_filters_and_falls_back():
    hits = [dict(PASSAGE, key=f"d.md#{i}", id=i, text=f"passage {i}") for i in range(1, 5)]

    class Scorer:
        def __init__(self, reply):
            self.chat = NS(completions=NS(create=lambda **kw: NS(
                choices=[NS(message=NS(content=reply))], usage=None)))

    reply = json.dumps({"scores": [{"id": 1, "score": 2}, {"id": 2, "score": 9},
                                   {"id": 3, "score": 9}, {"id": 4, "score": 5}]})
    top = rerank(Scorer(reply), "q", hits, top_n=3)
    assert [h["key"] for h in top] == ["d.md#2", "d.md#3", "d.md#4"]   # ties keep hybrid order; 2 < min dropped
    assert rerank(Scorer("garbage"), "q", hits, top_n=2) == [dict(h, rerank_score=None) for h in hits[:2]]
    assert rerank(Scorer("{}"), "q", [], top_n=2) == []
