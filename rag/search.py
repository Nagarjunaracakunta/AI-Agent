from memory.embeddings import embed

from .config import DEFAULT_COLLECTION, RETRIEVE_K


def hybrid_search(client, store, query: str, collection: str = DEFAULT_COLLECTION,
                  k: int = RETRIEVE_K) -> list[dict]:
    """Vector + keyword search fused with RRF. Each hit gets a `key` such as
    'deploy-and-rollback.md#2', which is also the citation id."""
    [query_vec] = embed(client, [query])
    hits = store.hybrid(collection, query_vec, query, k)
    for h in hits:
        h["key"] = f"{h['source']}#{h['chunk_index']}"
        h["score"] = float(h["score"])
    return hits
