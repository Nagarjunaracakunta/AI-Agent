"""Runs against the real Redis + Postgres from docker-compose.yml.
Skipped automatically when they aren't running (e.g. in CI)."""
import uuid

import pytest

from fakes import fake_embedding

try:
    from memory.long_term import LongTermMemory
    from memory.short_term import ShortTermMemory
    short, long = ShortTermMemory(), LongTermMemory()
    AVAILABLE = True
except Exception:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="Redis/Postgres not running")


def test_redis_short_term_roundtrip():
    sid = f"test-{uuid.uuid4().hex}"
    short.add(sid, "user", "hello")
    short.add(sid, "assistant", "hi")
    assert short.get(sid) == [{"role": "user", "content": "hello"},
                              {"role": "assistant", "content": "hi"}]
    short.replace(sid, [{"role": "user", "content": "only"}])
    assert len(short.get(sid)) == 1
    short.clear(sid)
    assert short.get(sid) == []


def test_pgvector_search_update_delete():
    uid = f"test-{uuid.uuid4().hex}"
    try:
        # real column is 1536-d; pad the fake 64-d vectors
        pad = lambda v: v + [0.0] * (1536 - len(v))
        a = long.add(uid, "User likes Python", pad(fake_embedding("User likes Python")))
        long.add(uid, "Window seats please", pad(fake_embedding("Window seats please")))

        hits = long.search(uid, pad(fake_embedding("python")), 2, 0.0)
        assert hits[0]["fact"] == "User likes Python"
        assert long.search("someone-else", pad(fake_embedding("python")), 2, 0.0) == []

        long.update(uid, a, "User loves Rust", pad(fake_embedding("User loves Rust")))
        assert "User loves Rust" in [r["fact"] for r in long.list_facts(uid)]

        long.save_summary(uid, "s1", "first")
        long.save_summary(uid, "s1", "second")  # upsert
        assert long.get_summary(uid, "s1") == "second"
        assert long.recent_summaries(uid, "s1", 5) == []
    finally:
        long.delete_all(uid)
    assert long.list_facts(uid) == []
