"""Postgres (pgvector + full-text) storage for documents and chunks.

Lives in the same database as the assistant's memory but in its own tables:
  rag_documents  one row per source file, with a content hash (for re-ingestion)
  rag_chunks     the chunks, their embeddings, and a generated tsvector
"""
import re

import psycopg
from psycopg.rows import dict_row

from .config import DATABASE_URL, EMBEDDING_DIM


def vec(embedding) -> str:
    return "[" + ",".join(str(float(x)) for x in embedding) + "]"


def to_or_query(text: str) -> str:
    """'How do I roll back?' -> 'how | do | i | roll | back' (OR semantics, so
    a long natural-language question still matches on its keywords)."""
    seen, tokens = set(), []
    for t in re.findall(r"[A-Za-z0-9]+", text.lower()):
        if t not in seen:
            seen.add(t)
            tokens.append(t)
    return " | ".join(tokens)


HYBRID_SQL = """
WITH vec AS (
    SELECT id, ROW_NUMBER() OVER (ORDER BY embedding <=> %(v)s::vector) AS rnk
    FROM rag_chunks WHERE collection = %(c)s
    ORDER BY embedding <=> %(v)s::vector LIMIT %(n)s
), kw AS (
    SELECT id, ROW_NUMBER() OVER (ORDER BY ts_rank_cd(tsv, q) DESC, id) AS rnk
    FROM rag_chunks, to_tsquery('english', %(q)s) AS q
    WHERE collection = %(c)s AND tsv @@ q
    ORDER BY ts_rank_cd(tsv, q) DESC, id LIMIT %(n)s
)
SELECT c.id, c.source, c.chunk_index, c.page, c.heading, c.text,
       COALESCE(1.0 / (60 + vec.rnk), 0) + COALESCE(1.0 / (60 + kw.rnk), 0) AS score,
       vec.rnk AS vec_rank, kw.rnk AS kw_rank
FROM vec FULL OUTER JOIN kw ON vec.id = kw.id
JOIN rag_chunks c ON c.id = COALESCE(vec.id, kw.id)
ORDER BY score DESC, c.id LIMIT %(n)s
"""


class RagStore:
    def __init__(self, dsn: str = DATABASE_URL, dim: int = EMBEDDING_DIM):
        self.dsn, self.dim = dsn, int(dim)
        self._init_schema()

    def _connect(self):
        return psycopg.connect(self.dsn, row_factory=dict_row, connect_timeout=5)

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS rag_documents (
                    id           BIGSERIAL PRIMARY KEY,
                    collection   TEXT NOT NULL,
                    source       TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    ingested_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
                    UNIQUE (collection, source)
                )""")
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS rag_chunks (
                    id          BIGSERIAL PRIMARY KEY,
                    doc_id      BIGINT NOT NULL REFERENCES rag_documents(id) ON DELETE CASCADE,
                    collection  TEXT NOT NULL,
                    source      TEXT NOT NULL,
                    chunk_index INT NOT NULL,
                    page        INT,
                    heading     TEXT,
                    text        TEXT NOT NULL,
                    embedding   vector({self.dim}) NOT NULL,
                    tsv         tsvector GENERATED ALWAYS AS
                                (to_tsvector('english', coalesce(heading, '') || ' ' || text)) STORED
                )""")
            conn.execute("CREATE INDEX IF NOT EXISTS rag_chunks_collection_idx ON rag_chunks (collection)")
            conn.execute("CREATE INDEX IF NOT EXISTS rag_chunks_tsv_idx ON rag_chunks USING gin (tsv)")
            conn.execute("CREATE INDEX IF NOT EXISTS rag_chunks_embedding_idx "
                         "ON rag_chunks USING hnsw (embedding vector_cosine_ops)")

    # ---- ingestion -------------------------------------------------------

    def get_document(self, collection: str, source: str) -> dict | None:
        with self._connect() as conn:
            return conn.execute(
                "SELECT id, content_hash FROM rag_documents WHERE collection=%s AND source=%s",
                (collection, source)).fetchone()

    def replace_document(self, collection: str, source: str, content_hash: str,
                         chunks: list[dict]) -> int:
        """Atomically swap a document's chunks. Each chunk dict has: index,
        text, heading, page, embedding."""
        with self._connect() as conn:  # one transaction: all or nothing
            conn.execute("DELETE FROM rag_documents WHERE collection=%s AND source=%s",
                         (collection, source))
            doc_id = conn.execute(
                "INSERT INTO rag_documents (collection, source, content_hash) "
                "VALUES (%s,%s,%s) RETURNING id", (collection, source, content_hash),
            ).fetchone()["id"]
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO rag_chunks (doc_id, collection, source, chunk_index, page, "
                    "heading, text, embedding) VALUES (%s,%s,%s,%s,%s,%s,%s,%s::vector)",
                    [(doc_id, collection, source, c["index"], c["page"], c["heading"],
                      c["text"], vec(c["embedding"])) for c in chunks])
            return doc_id

    def prune(self, collection: str, keep_sources: set[str]) -> list[str]:
        """Delete documents whose source file no longer exists."""
        with self._connect() as conn:
            rows = conn.execute("SELECT source FROM rag_documents WHERE collection=%s",
                                (collection,)).fetchall()
            gone = [r["source"] for r in rows if r["source"] not in keep_sources]
            for s in gone:
                conn.execute("DELETE FROM rag_documents WHERE collection=%s AND source=%s",
                             (collection, s))
        return gone

    def delete_collection(self, collection: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM rag_documents WHERE collection=%s", (collection,))

    # ---- reading ---------------------------------------------------------

    def list_documents(self, collection: str) -> list[dict]:
        with self._connect() as conn:
            return conn.execute(
                """SELECT d.source, d.ingested_at, count(c.id) AS chunks
                   FROM rag_documents d LEFT JOIN rag_chunks c ON c.doc_id = d.id
                   WHERE d.collection = %s GROUP BY d.id ORDER BY d.source""",
                (collection,)).fetchall()

    def hybrid(self, collection: str, query_embedding, query_text: str, n: int) -> list[dict]:
        """Vector + keyword search merged with Reciprocal Rank Fusion."""
        with self._connect() as conn:
            return conn.execute(HYBRID_SQL, {
                "v": vec(query_embedding), "c": collection,
                "q": to_or_query(query_text), "n": n}).fetchall()
