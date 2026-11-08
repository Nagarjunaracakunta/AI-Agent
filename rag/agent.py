"""The Docs Q&A agent (LangGraph).

    answer ──► verify ──┬─ grounded (or retries used up) ──► finish ──► END
       ▲                │
       └── not grounded ┘   (retry with feedback, max MAX_RETRIES times)

`answer` is a tool-calling agent: it decides what to search for, rewrites the
question into search queries, and can search again. Each search runs hybrid
retrieval + LLM reranking. `verify` checks the citations in code, then asks an
LLM judge whether the answer is supported by the passages it cited.
"""
import json
import operator
import re
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from memory.llm_tasks import parse_json
from pydantic import BaseModel, Field, ValidationError

from agent import run_agent

from .config import (DEFAULT_COLLECTION, MAX_RETRIES, RAG_MODEL, REFUSAL,
                     RERANK_TOP_N, RETRIEVE_K)
from .llm import chat
from .rerank import rerank
from .search import hybrid_search

CITATION = re.compile(r"\[([^\[\]\n]+?#\d+)\]")  # e.g. [deploy-and-rollback.md#2]

ANSWER_SYSTEM = f"""You are a documentation assistant. Answer ONLY from passages returned by the search_docs tool.

How to work:
- Always call search_docs before answering. Turn the user's question into a focused search query (key terms, error codes, command names). If the results do not contain the answer, search again with different wording. For multi-part questions, search for each part.
- Cite every factual statement with the passage's cite id in square brackets, exactly as given, e.g. [deploy-and-rollback.md#2]. Never cite something you did not retrieve.
- If the documents do not contain the answer, reply with exactly: {REFUSAL}
- Never use outside knowledge. Do not guess.
- Be concise. Use numbered steps for procedures and quote commands exactly."""

VERIFY_SYSTEM = (
    "You verify answers against source passages. Check that every factual claim "
    "in the ANSWER (numbers, times, commands, names, conditions) is supported by "
    "the PASSAGES. Ignore wording and formatting. Commands must match exactly. "
    'Return ONLY JSON: {"grounded": true|false, "unsupported_claims": ["..."]}'
)


class SearchDocsArgs(BaseModel):
    query: str = Field(description="A focused search query: key terms, error codes, command names")


SEARCH_SCHEMA = [{
    "type": "function",
    "function": {
        "name": "search_docs",
        "description": "Search the internal documentation (runbooks, wikis). Returns "
                       "the most relevant passages, each with a cite id.",
        "parameters": SearchDocsArgs.model_json_schema(),
    },
}]


class _Verdict(BaseModel):
    grounded: bool
    unsupported_claims: list[str] = Field(default_factory=list)


class RagState(TypedDict, total=False):
    question: str
    history: list          # earlier [{role, content}] turns, for follow-ups
    answer: str
    evidence: dict         # cite id -> passage, everything retrieved so far
    cited: list            # valid cite ids used by the answer
    grounded: bool
    issues: list
    attempt: int
    refused: bool
    trace: Annotated[list, operator.add]      # step-by-step log for the UI
    tokens: Annotated[int, operator.add]


def extract_citations(answer: str) -> list[str]:
    seen = []
    for c in CITATION.findall(answer):
        if c not in seen:
            seen.append(c)
    return seen


def is_refusal(answer: str) -> bool:
    return answer.strip().lower().startswith(REFUSAL.lower()[:25])


def build_rag_graph(client, store, collection: str = DEFAULT_COLLECTION, *,
                    model: str = RAG_MODEL, k: int = RETRIEVE_K, top_n: int = RERANK_TOP_N):

    def answer_node(state: RagState):
        usage = {"total": 0}
        evidence = dict(state.get("evidence", {}))
        trace: list = []
        attempt = state.get("attempt", 0) + 1

        def search_tool(name: str, raw_args: str) -> dict:
            if name != "search_docs":
                return {"error": f"Unknown tool '{name}'"}
            try:
                query = SearchDocsArgs(**json.loads(raw_args or "{}")).query
            except (json.JSONDecodeError, ValidationError) as e:
                return {"error": f"Invalid arguments: {e}"}
            hits = hybrid_search(client, store, query, collection, k)
            top = rerank(client, query, hits, top_n, usage=usage)
            for h in top:
                evidence[h["key"]] = h
            trace.append({"step": "search", "query": query, "candidates": len(hits),
                          "kept": [(h["key"], h["rerank_score"]) for h in top]})
            if not top:
                return {"results": [], "note": "No relevant passages found. Rephrase and "
                        "search again, or say the documents do not cover it."}
            return {"results": [{
                "cite": h["key"], "source": h["source"], "section": h.get("heading"),
                "page": h.get("page"), "text": h["text"]} for h in top]}

        user = state["question"]
        if state.get("issues"):
            user += ("\n\nYour previous answer failed verification:\n- "
                     + "\n- ".join(state["issues"])
                     + "\nSearch again (use different wording if needed) and answer "
                       "using only supported, correctly cited facts.")
        messages = ([{"role": "system", "content": ANSWER_SYSTEM}]
                    + list(state.get("history", []))[-4:]
                    + [{"role": "user", "content": user}])
        reply, _ = run_agent(client, model, messages, max_steps=6,
                             tool_schemas=SEARCH_SCHEMA, executor=search_tool, usage=usage,
                             temperature=0)
        trace.append({"step": "answer", "attempt": attempt})
        return {"answer": reply.strip(), "evidence": evidence, "attempt": attempt,
                "trace": trace, "tokens": usage["total"]}

    def verify_node(state: RagState):
        usage = {"total": 0}
        answer, evidence = state["answer"], state.get("evidence", {})
        cites = extract_citations(answer)
        valid = [c for c in cites if c in evidence]
        invalid = [c for c in cites if c not in evidence]

        issues: list[str] = []
        if is_refusal(answer):
            grounded = True                      # an honest "not found" is fine
        elif not cites:
            grounded, issues = False, ["The answer has no citations. Every fact must cite a retrieved passage."]
        elif invalid:
            grounded = False
            issues = [f"Citation {c} was never retrieved. Cite only passages returned by search_docs." for c in invalid]
        else:
            passages = "\n\n".join(f"[{c}]\n{evidence[c]['text']}" for c in valid)
            reply = chat(client, VERIFY_SYSTEM, f"PASSAGES:\n{passages}\n\nANSWER:\n{answer}",
                         usage, model)
            verdict = parse_json(reply, _Verdict)
            if verdict is None:                  # unusable judge reply: don't block the user
                grounded = True
            else:
                grounded = verdict.grounded
                issues = [f"Unsupported claim: {c}" for c in verdict.unsupported_claims]
                if not grounded and not issues:
                    issues = ["Some claims are not supported by the cited passages."]
        return {"grounded": grounded, "issues": issues, "cited": valid,
                "trace": [{"step": "verify", "grounded": grounded, "issues": issues,
                           "invalid_citations": invalid}],
                "tokens": usage["total"]}

    def route(state: RagState):
        if state["grounded"] or state["attempt"] > MAX_RETRIES:
            return "finish"
        return "answer"

    def finish_node(state: RagState):
        answer = state["answer"]
        if is_refusal(answer):
            return {"refused": True}
        if not state["cited"]:
            # No valid citation after all retries: no citation = no answer.
            return {"answer": REFUSAL + " (I could not back an answer with a source.)",
                    "refused": True, "grounded": False}
        return {"refused": False}  # cited, but maybe unverified: UI shows a warning

    graph = StateGraph(RagState)
    graph.add_node("answer", answer_node)
    graph.add_node("verify", verify_node)
    graph.add_node("finish", finish_node)
    graph.add_edge(START, "answer")
    graph.add_edge("answer", "verify")
    graph.add_conditional_edges("verify", route, {"answer": "answer", "finish": "finish"})
    graph.add_edge("finish", END)
    return graph.compile()


def initial_state(question: str, history: list | None = None) -> dict:
    return {"question": question, "history": history or [], "evidence": {},
            "attempt": 0, "issues": [], "trace": [], "tokens": 0}


def ask(client, store, question: str, history: list | None = None,
        collection: str = DEFAULT_COLLECTION, **kwargs) -> dict:
    """Run the agent to completion and return the final state."""
    graph = build_rag_graph(client, store, collection, **kwargs)
    return graph.invoke(initial_state(question, history))
