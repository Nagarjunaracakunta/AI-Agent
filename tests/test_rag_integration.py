"""Real Postgres + pgvector (docker compose). Skipped when it isn't running.
Embeddings are faked (hashed bag-of-words), so no API calls are made."""
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from fakes import fake_embedding

try:
    from rag.store import RagStore
    store = RagStore()
    AVAILABLE = True
except Exception:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="Postgres not running")

DIM = 1536


def fake_embed(client, texts):
    return [fake_embedding(t, DIM) for t in texts]


def fake_client():
    return NS(embeddings=NS(create=lambda model, input: NS(
        data=[NS(index=i, embedding=fake_embedding(t, DIM)) for i, t in enumerate(input)])))


def test_ingest_search_skip_update_prune():
    from rag.ingest import ingest
    from rag.search import hybrid_search

    collection = f"test-{uuid.uuid4().hex[:8]}"
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "certs.md").write_text(
            "# Certificates\n\n## Errors\n\nError TLS-1042 means the DNS challenge failed.\n")
        (root / "backups.md").write_text(
            "# Backups\n\nA full backup runs nightly and is kept for 14 days.\n")
        try:
            kw = dict(target=100, max_tokens=200, overlap=0, embed_fn=fake_embed, log=lambda *_: None)
            s1 = ingest(None, store, root, collection, **kw)
            assert sorted(s1["indexed"]) == ["backups.md", "certs.md"]
            assert {d["source"] for d in store.list_documents(collection)} == {"backups.md", "certs.md"}

            # hybrid search: the error code is found (keyword leg + vector leg)
            hits = hybrid_search(fake_client(), store, "TLS-1042", collection)
            assert hits[0]["key"] == "certs.md#0"
            assert hits[0]["kw_rank"] == 1
            assert hybrid_search(fake_client(), store, "TLS-1042", "other-collection") == []

            # unchanged files are skipped on re-run
            s2 = ingest(None, store, root, collection, **kw)
            assert s2["indexed"] == [] and len(s2["skipped"]) == 2

            # edited file is re-indexed, and its old chunks are replaced
            (root / "backups.md").write_text("# Backups\n\nBackups are kept for 30 days now.\n")
            s3 = ingest(None, store, root, collection, **kw)
            assert s3["indexed"] == ["backups.md"]
            hits = hybrid_search(fake_client(), store, "backups kept", collection)
            assert "30 days" in next(h["text"] for h in hits if h["source"] == "backups.md")
            assert not any("14 days" in h["text"] for h in hits)

            # deleted file is pruned
            (root / "certs.md").unlink()
            s4 = ingest(None, store, root, collection, prune=True, **kw)
            assert s4["pruned"] == ["certs.md"]
            assert [d["source"] for d in store.list_documents(collection)] == ["backups.md"]
        finally:
            store.delete_collection(collection)
    assert store.list_documents(collection) == []
