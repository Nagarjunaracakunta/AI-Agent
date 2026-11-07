import json
import time

from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from agent import run_agent
from tools.search import SEARCH_SCHEMAS, execute_search

from .agents import system_prompt
from .state import CrewState, ReviewResult, SeoResult

MAX_REVISIONS = 2   # reviewer feedback loop limit (prevents endless loops)
PASS_SCORE = 8      # revise if score is below this
FAST_MODEL = "openai/gpt-4o-mini"    # planner, researcher, seo
STRONG_MODEL = "openai/gpt-4o-mini"  # writer, reviewer (swap for a stronger model)


def parse_json(text: str, model):
    """Pull the first {...} block out of an LLM reply and validate it."""
    try:
        start, end = text.index("{"), text.rindex("}") + 1
        return model(**json.loads(text[start:end]))
    except (ValueError, ValidationError):
        return None


def build_graph(client):
    """Build the crew as a LangGraph. `client` is an OpenAI-compatible client."""

    def call(agent, model, user, tools=None, executor=None):
        usage = {"total": 0}
        started = time.time()
        reply, tool_log = run_agent(
            client, model,
            [{"role": "system", "content": system_prompt(agent)},
             {"role": "user", "content": user}],
            tool_schemas=tools, executor=executor, usage=usage,
        )
        entry = {
            "agent": agent,
            "seconds": round(time.time() - started, 1),
            "tokens": usage["total"],
            "tool_calls": [c["name"] for c in tool_log],
            "output": reply,
        }
        return reply, entry

    def ask_json(agent, model, user, schema):
        """Call an agent that must return JSON. Retry once on bad output."""
        entries = []
        for attempt in range(2):
            prompt = user if attempt == 0 else (
                user + "\n\nYour previous reply was not valid JSON. "
                       "Return ONLY the JSON object.")
            reply, entry = call(agent, model, prompt)
            entries.append(entry)
            result = parse_json(reply, schema)
            if result:
                return result, entries
        return None, entries

    # ---- nodes: each reads the shared state and returns only its own fields

    def planner(state):
        reply, entry = call("planner", FAST_MODEL, f"Topic: {state['topic']}")
        return {"outline": reply, "log": [entry]}

    def researcher(state):
        reply, entry = call(
            "researcher", FAST_MODEL,
            f"Topic: {state['topic']}\n\nOutline:\n{state['outline']}",
            tools=SEARCH_SCHEMAS, executor=execute_search,
        )
        return {"research": reply, "log": [entry]}

    def writer(state):
        revising = bool(state.get("draft"))
        user = (f"Topic: {state['topic']}\n\nOutline:\n{state['outline']}\n\n"
                f"Research notes:\n{state['research']}")
        if revising:
            issues = "\n".join(f"- {i}" for i in state.get("issues", []))
            user += (f"\n\nPrevious draft:\n{state['draft']}\n\n"
                     f"Reviewer issues to fix:\n{issues}")
        reply, entry = call("writer", STRONG_MODEL, user)
        return {
            "draft": reply,
            "revision_count": state.get("revision_count", 0) + (1 if revising else 0),
            "log": [entry],
        }

    def reviewer(state):
        user = (f"Outline:\n{state['outline']}\n\n"
                f"Research notes:\n{state['research']}\n\n"
                f"Draft to review:\n{state['draft']}")
        result, entries = ask_json("reviewer", STRONG_MODEL, user, ReviewResult)
        if result is None:  # don't loop forever on a broken reviewer
            result = ReviewResult(
                score=PASS_SCORE,
                issues=["Reviewer returned invalid JSON; draft accepted unreviewed."])
        return {"score": result.score, "issues": result.issues, "log": entries}

    def seo(state):
        result, entries = ask_json(
            "seo", FAST_MODEL, f"Topic: {state['topic']}\n\nArticle:\n{state['draft']}",
            SeoResult)
        if result is None:
            result = SeoResult(title=state["topic"], meta_description="", hashtags=[])
        data = result.model_dump()
        data["meta_description"] = data["meta_description"][:160]
        return {"seo": data, "log": entries}

    # ---- supervisor: the routing rule after each review

    def route_after_review(state):
        if state["score"] >= PASS_SCORE or state.get("revision_count", 0) >= MAX_REVISIONS:
            return "seo"
        return "writer"

    graph = StateGraph(CrewState)
    graph.add_node("planner", planner)
    graph.add_node("researcher", researcher)
    graph.add_node("writer", writer)
    graph.add_node("reviewer", reviewer)
    graph.add_node("seo", seo)

    graph.add_edge(START, "planner")
    graph.add_edge("planner", "researcher")
    graph.add_edge("researcher", "writer")
    graph.add_edge("writer", "reviewer")
    graph.add_conditional_edges("reviewer", route_after_review,
                                {"writer": "writer", "seo": "seo"})
    graph.add_edge("seo", END)
    return graph.compile()


def initial_state(topic: str) -> dict:
    return {"topic": topic, "revision_count": 0, "log": []}


def to_markdown(state) -> str:
    """Assemble the final blog.md from the shared state."""
    seo = state.get("seo") or {}
    parts = [f"# {seo.get('title') or state['topic']}"]
    if seo.get("meta_description"):
        parts.append(f"> {seo['meta_description']}")
    parts.append(state["draft"])
    if seo.get("hashtags"):
        parts.append(" ".join(seo["hashtags"]))
    return "\n\n".join(parts) + "\n"
