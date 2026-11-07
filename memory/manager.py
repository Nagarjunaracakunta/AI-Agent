"""MemoryManager: the single entry point the app uses.

  recall()    before answering: top-k relevant facts for this user
  remember()  after replying: extract facts, dedupe/update, embed, store
  summary helpers keep long sessions inside the context window
  forget / list: let users see and delete what is stored
"""
from .config import (CANDIDATE_SIMILARITY, DUPLICATE_SIMILARITY, EMBEDDING_MODEL,
                     KEEP_RECENT_TURNS, RECALL_K, RECALL_MIN_SIMILARITY,
                     SUMMARY_AFTER_TURNS, UTILITY_MODEL)
from .embeddings import embed
from .llm_tasks import decide, extract_facts, summarise


class MemoryManager:
    def __init__(self, client, short, long, *, embedding_model: str = EMBEDDING_MODEL,
                 chat_model: str = UTILITY_MODEL):
        self.client = client
        self.short = short   # ShortTermMemory (Redis)
        self.long = long     # LongTermMemory (Postgres + pgvector)
        self.embedding_model = embedding_model
        self.chat_model = chat_model

    # ---- recall ----------------------------------------------------------

    def recall(self, user_id: str, query: str, k: int = RECALL_K) -> list[dict]:
        [vec] = embed(self.client, [query], self.embedding_model)
        return self.long.search(user_id, vec, k, RECALL_MIN_SIMILARITY)

    # ---- write -----------------------------------------------------------

    def remember(self, user_id: str, user_msg: str, assistant_msg: str) -> list[dict]:
        """Extract facts from one exchange and store them. Returns what was
        done, e.g. [{'action': 'add', 'fact': ...}], for display or debugging."""
        facts = extract_facts(self.client, self.chat_model, user_msg, assistant_msg)
        if not facts:
            return []
        vectors = embed(self.client, facts, self.embedding_model)
        return [self._store(user_id, fact, vec) for fact, vec in zip(facts, vectors)]

    def _store(self, user_id: str, fact: str, vec) -> dict:
        near = self.long.search(user_id, vec, 3, CANDIDATE_SIMILARITY)
        if not near:
            self.long.add(user_id, fact, vec)
            return {"action": "add", "fact": fact}

        if near[0]["similarity"] >= DUPLICATE_SIMILARITY:
            # Same fact again: refresh it instead of appending a duplicate.
            self.long.update(user_id, near[0]["id"], fact, vec)
            return {"action": "refresh", "fact": fact}

        decision = decide(self.client, self.chat_model, fact, near)
        if decision.action == "skip":
            return {"action": "skip", "fact": fact}
        if decision.action == "update":
            self.long.update(user_id, decision.id, fact, vec)
            return {"action": "update", "fact": fact}
        self.long.add(user_id, fact, vec)
        return {"action": "add", "fact": fact}

    # ---- short-term buffer ----------------------------------------------

    def add_turn(self, session_id: str, role: str, content: str) -> None:
        self.short.add(session_id, role, content)

    def get_turns(self, session_id: str) -> list[dict]:
        return self.short.get(session_id)

    # ---- summaries -------------------------------------------------------

    def maybe_summarise(self, user_id: str, session_id: str) -> bool:
        """When a session gets long, fold its oldest turns into a summary and
        keep only the recent ones in Redis."""
        turns = self.short.get(session_id)
        if len(turns) <= SUMMARY_AFTER_TURNS:
            return False
        old, recent = turns[:-KEEP_RECENT_TURNS], turns[-KEEP_RECENT_TURNS:]
        prior = self.long.get_summary(user_id, session_id)
        summary = summarise(self.client, self.chat_model, prior, old)
        self.long.save_summary(user_id, session_id, summary)
        self.short.replace(session_id, recent)
        return True

    def close_session(self, user_id: str, session_id: str) -> None:
        """Called on 'New chat': summarise what's left so it can be recalled
        in future sessions, then clear the buffer."""
        turns = self.short.get(session_id)
        if len(turns) >= 2:
            prior = self.long.get_summary(user_id, session_id)
            summary = summarise(self.client, self.chat_model, prior, turns)
            self.long.save_summary(user_id, session_id, summary)
        self.short.clear(session_id)

    def context_summaries(self, user_id: str, session_id: str, past: int = 2) -> dict:
        return {
            "current": self.long.get_summary(user_id, session_id),
            "past": self.long.recent_summaries(user_id, session_id, past),
        }

    # ---- privacy: view and delete ---------------------------------------

    def list_memories(self, user_id: str) -> list[dict]:
        return self.long.list_facts(user_id)

    def forget(self, user_id: str, memory_id: int) -> None:
        self.long.delete(user_id, memory_id)

    def forget_all(self, user_id: str) -> None:
        self.long.delete_all(user_id)


def build_manager(client) -> MemoryManager:
    """Connect to Redis and Postgres. Raises if either is unreachable."""
    from .long_term import LongTermMemory
    from .short_term import ShortTermMemory
    return MemoryManager(client, ShortTermMemory(), LongTermMemory())
