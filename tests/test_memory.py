from memory.config import KEEP_RECENT_TURNS, SUMMARY_AFTER_TURNS
from memory.llm_tasks import Decision, decide, extract_facts, parse_json
from memory.manager import MemoryManager

from fakes import FakeClient, FakeLong, FakeShort


def make(client):
    return MemoryManager(client, FakeShort(), FakeLong())


def test_remember_then_recall_in_new_session():
    """The blueprint's Monday/Friday test, with fakes."""
    client = FakeClient(facts=["User's favourite stack is Python and FastAPI"])
    m = make(client)
    assert m.remember("u1", "My favourite stack is Python and FastAPI", "Nice!") == [
        {"action": "add", "fact": "User's favourite stack is Python and FastAPI"}]
    facts = m.recall("u1", "Suggest a Python project idea")
    assert facts and "FastAPI" in facts[0]["fact"]


def test_recall_is_per_user():
    m = make(FakeClient(facts=["User lives in Vijayawada"]))
    m.remember("alice", "I live in Vijayawada", "ok")
    assert m.recall("bob", "Vijayawada") == []


def test_near_duplicate_is_refreshed_not_appended():
    m = make(FakeClient(facts=["User lives in Vijayawada"]))
    m.remember("u1", "x", "y")
    result = m.remember("u1", "x", "y")  # same fact again
    assert result[0]["action"] == "refresh"
    assert len(m.list_memories("u1")) == 1


def test_contradiction_updates_existing_memory():
    client = FakeClient(facts=["User lives in Vijayawada city India"])
    m = make(client)
    m.remember("u1", "x", "y")
    old_id = m.list_memories("u1")[0]["id"]

    client.facts = ["User lives in Bangalore city India"]  # similar, not identical
    client.decision = {"action": "update", "id": old_id}
    result = m.remember("u1", "x", "y")

    assert result[0]["action"] == "update"
    memories = m.list_memories("u1")
    assert len(memories) == 1 and "Bangalore" in memories[0]["fact"]


def test_unrelated_fact_is_added():
    client = FakeClient(facts=["User lives in Vijayawada"])
    m = make(client)
    m.remember("u1", "x", "y")
    client.facts = ["Prefers window seats on flights"]
    m.remember("u1", "x", "y")
    assert len(m.list_memories("u1")) == 2


def test_nothing_extracted_means_no_writes():
    client = FakeClient(facts=[])
    m = make(client)
    assert m.remember("u1", "hello", "hi") == []
    assert client.calls == ["extract"]


def test_forget_one_and_all():
    m = make(FakeClient(facts=["User likes trains"]))
    m.remember("u1", "x", "y")
    m.forget("u1", m.list_memories("u1")[0]["id"])
    assert m.list_memories("u1") == []

    m.remember("u1", "x", "y")
    m.long.save_summary("u1", "s1", "summary")
    m.forget_all("u1")
    assert m.list_memories("u1") == [] and m.long.get_summary("u1", "s1") is None


def test_summarise_long_session_keeps_recent_turns():
    client = FakeClient()
    m = make(client)
    for i in range(SUMMARY_AFTER_TURNS + 4):
        m.add_turn("s1", "user" if i % 2 == 0 else "assistant", f"turn {i}")
    assert m.maybe_summarise("u1", "s1") is True
    assert len(m.get_turns("s1")) == KEEP_RECENT_TURNS
    assert m.long.get_summary("u1", "s1") == "A short summary."


def test_short_session_is_not_summarised():
    m = make(FakeClient())
    m.add_turn("s1", "user", "hi")
    assert m.maybe_summarise("u1", "s1") is False


def test_close_session_saves_summary_for_future_sessions():
    m = make(FakeClient())
    m.add_turn("s1", "user", "plan a trip to Goa")
    m.add_turn("s1", "assistant", "Sure!")
    m.close_session("u1", "s1")
    assert m.get_turns("s1") == []
    ctx = m.context_summaries("u1", "s2")  # a *new* session
    assert ctx["past"] == ["A short summary."]


def test_parse_json_and_bad_input():
    assert parse_json('noise {"action": "skip"} tail', Decision).action == "skip"
    assert parse_json("not json", Decision) is None


def test_decide_falls_back_to_add_on_bad_reply():
    client = FakeClient(decision={"action": "update", "id": 999})  # id not a candidate
    result = decide(client, "m", "new", [{"id": 1, "fact": "old"}])
    assert result.action == "add"


def test_extract_facts_dedupes_and_caps():
    client = FakeClient(facts=["A", "a", " B ", "C", "D", "E", "F"])
    assert extract_facts(client, "m", "u", "a") == ["A", "B", "C", "D", "E"]
