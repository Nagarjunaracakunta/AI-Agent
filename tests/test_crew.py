import json
from types import SimpleNamespace as NS

from crew.graph import MAX_REVISIONS, build_graph, initial_state, to_markdown


class FakeClient:
    """Scripted stand-in for the OpenAI client. Picks its reply from the
    agent role in the system prompt."""

    def __init__(self, scores, reviewer_text=None):
        self.scores = list(scores)
        self.reviewer_text = reviewer_text
        self.calls = []  # agent names, in call order
        self.chat = NS(completions=NS(create=self._create))

    def _create(self, model, messages, tools=None):
        system = messages[0]["content"]
        agent = next(a for a in ("Planner", "Researcher", "Writer", "Reviewer", "SEO")
                     if f"ROLE: {a}" in system)
        self.calls.append(agent)

        tool_calls = None
        if agent == "Researcher" and messages[-1]["role"] != "tool":
            content = None
            tool_calls = [NS(id="c1", function=NS(
                name="search_web", arguments=json.dumps({"query": "topic"})))]
        elif agent == "Reviewer":
            score = self.scores.pop(0) if len(self.scores) > 1 else self.scores[0]
            content = self.reviewer_text or json.dumps(
                {"score": score, "issues": ["fix claim"]})
        elif agent == "SEO":
            content = json.dumps({"title": "Great Title", "meta_description": "x" * 200,
                                  "hashtags": ["#a", "#b", "#c", "#d", "#e"]})
        else:
            content = f"{agent} output"
        msg = NS(content=content, tool_calls=tool_calls)
        return NS(choices=[NS(message=msg)], usage=NS(total_tokens=10))


def run(client):
    return build_graph(client).invoke(initial_state("K8s networking"))


def test_passes_first_review():
    client = FakeClient([9])
    state = run(client)
    assert client.calls.count("Writer") == 1
    assert client.calls.count("Reviewer") == 1
    assert state["revision_count"] == 0
    assert state["seo"]["title"] == "Great Title"
    assert len(state["seo"]["meta_description"]) == 160  # truncated


def test_revises_once_then_passes():
    client = FakeClient([5, 9])
    state = run(client)
    assert client.calls.count("Writer") == 2
    assert state["revision_count"] == 1
    assert state["score"] == 9


def test_stops_after_max_revisions():
    client = FakeClient([3])  # never passes
    state = run(client)
    assert state["revision_count"] == MAX_REVISIONS
    assert client.calls.count("Writer") == MAX_REVISIONS + 1
    assert "SEO" in client.calls  # still finishes


def test_invalid_reviewer_json_does_not_loop():
    client = FakeClient([0], reviewer_text="not json at all")
    state = run(client)
    assert client.calls.count("Writer") == 1
    assert client.calls.count("Reviewer") == 2  # one retry
    assert "invalid JSON" in state["issues"][0]


def test_log_and_markdown():
    state = run(FakeClient([9]))
    assert [e["agent"] for e in state["log"]][:3] == ["planner", "researcher", "writer"]
    assert state["log"][1]["tool_calls"] == ["search_web"]
    md = to_markdown(state)
    assert md.startswith("# Great Title") and "#a #b" in md
