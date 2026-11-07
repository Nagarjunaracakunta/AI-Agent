"""Long-term memory in PostgreSQL + pgvector: per-user facts (with embeddings)
and per-session summaries."""
import psycopg
from psycopg.rows import dict_row

from .config import DATABASE_URL, EMBEDDING_DIM


def _vec(embedding) -> str:
    """pgvector text literal, e.g. '[0.1,0.2]' (cast with ::vector in SQL)."""
    return "[" + ",".join(str(float(x)) for x in embedding) + "]"


class LongTermMemory:
    def __init__(self, dsn: str = DATABASE_URL, dim: int = EMBEDDING_DIM):
        self.dsn = dsn
        self.dim = int(dim)
        self._init_schema()

    def _connect(self):
        # A short-lived connection per operation: simple and robust with
        # Streamlit's multi-threaded reruns.
        return psycopg.connect(self.dsn, row_factory=dict_row, connect_timeout=3)

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS memories (
                    id         BIGSERIAL PRIMARY KEY,
                    user_id    TEXT NOT NULL,
                    fact       TEXT NOT NULL,
                    embedding  vector({self.dim}) NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )""")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS memories_user_idx ON memories (user_id)")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS memories_embedding_idx ON memories "
                "USING hnsw (embedding vector_cosine_ops)")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS session_summaries (
                    user_id    TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    summary    TEXT NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    PRIMARY KEY (user_id, session_id)
                )""")

    # ---- facts -----------------------------------------------------------

    def search(self, user_id: str, embedding, k: int, min_similarity: float) -> list[dict]:
        """Top-k facts for this user by cosine similarity (highest first)."""
        v = _vec(embedding)
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT id, fact, 1 - (embedding <=> %s::vector) AS similarity
                   FROM memories WHERE user_id = %s
                   ORDER BY embedding <=> %s::vector LIMIT %s""",
                (v, user_id, v, k),
            ).fetchall()
        return [r for r in rows if r["similarity"] >= min_similarity]

    def add(self, user_id: str, fact: str, embedding) -> int:
        with self._connect() as conn:
            return conn.execute(
                "INSERT INTO memories (user_id, fact, embedding) "
                "VALUES (%s, %s, %s::vector) RETURNING id",
                (user_id, fact, _vec(embedding)),
            ).fetchone()["id"]

    def update(self, user_id: str, memory_id: int, fact: str, embedding) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE memories SET fact = %s, embedding = %s::vector, "
                "updated_at = now() WHERE id = %s AND user_id = %s",
                (fact, _vec(embedding), memory_id, user_id),
            )

    def list_facts(self, user_id: str) -> list[dict]:
        with self._connect() as conn:
            return conn.execute(
                "SELECT id, fact, updated_at FROM memories WHERE user_id = %s "
                "ORDER BY updated_at DESC", (user_id,),
            ).fetchall()

    def delete(self, user_id: str, memory_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM memories WHERE id = %s AND user_id = %s",
                         (memory_id, user_id))

    def delete_all(self, user_id: str) -> None:
        """Forget everything about a user: facts and summaries."""
        with self._connect() as conn:
            conn.execute("DELETE FROM memories WHERE user_id = %s", (user_id,))
            conn.execute("DELETE FROM session_summaries WHERE user_id = %s", (user_id,))

    # ---- session summaries ----------------------------------------------

    def get_summary(self, user_id: str, session_id: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT summary FROM session_summaries "
                "WHERE user_id = %s AND session_id = %s", (user_id, session_id),
            ).fetchone()
        return row["summary"] if row else None

    def save_summary(self, user_id: str, session_id: str, summary: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO session_summaries (user_id, session_id, summary)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (user_id, session_id)
                   DO UPDATE SET summary = EXCLUDED.summary, updated_at = now()""",
                (user_id, session_id, summary),
            )

    def recent_summaries(self, user_id: str, exclude_session: str, n: int) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT summary FROM session_summaries "
                "WHERE user_id = %s AND session_id <> %s "
                "ORDER BY updated_at DESC LIMIT %s", (user_id, exclude_session, n),
            ).fetchall()
        return [r["summary"] for r in rows]
