"""In-memory stand-ins so memory logic can be tested without Redis, Postgres
or an LLM."""
import json
import math
import re
from types import SimpleNamespace as NS


def fake_embedding(text: str, dim: int = 64):
    """Bag-of-words hashing: texts sharing words get high cosine similarity."""
    v = [0.0] * dim
    for w in re.findall(r"[a-z]+", text.lower()):
        v[sum(map(ord, w)) % dim] += 1.0
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]


def cosine(a, b):
    return sum(x * y for x, y in zip(a, b))


class FakeShort:
    def __init__(self):
        self.data = {}

    def add(self, sid, role, content):
        self.data.setdefault(sid, []).append({"role": role, "content": content})

    def get(self, sid):
        return list(self.data.get(sid, []))

    def replace(self, sid, turns):
        self.data[sid] = list(turns)

    def clear(self, sid):
        self.data.pop(sid, None)


class FakeLong:
    def __init__(self):
        self.rows, self.next_id, self.summaries = [], 1, {}

    def search(self, user_id, embedding, k, min_similarity):
        hits = [{"id": r["id"], "fact": r["fact"],
                 "similarity": cosine(embedding, r["embedding"])}
                for r in self.rows if r["user_id"] == user_id]
        hits.sort(key=lambda h: -h["similarity"])
        return [h for h in hits[:k] if h["similarity"] >= min_similarity]

    def add(self, user_id, fact, embedding):
        self.rows.append({"id": self.next_id, "user_id": user_id, "fact": fact,
                          "embedding": embedding})
        self.next_id += 1
        return self.next_id - 1

    def update(self, user_id, memory_id, fact, embedding):
        for r in self.rows:
            if r["id"] == memory_id and r["user_id"] == user_id:
                r["fact"], r["embedding"] = fact, embedding

    def list_facts(self, user_id):
        return [{"id": r["id"], "fact": r["fact"]} for r in self.rows
                if r["user_id"] == user_id]

    def delete(self, user_id, memory_id):
        self.rows = [r for r in self.rows
                     if not (r["id"] == memory_id and r["user_id"] == user_id)]

    def delete_all(self, user_id):
        self.rows = [r for r in self.rows if r["user_id"] != user_id]
        self.summaries = {k: v for k, v in self.summaries.items() if k[0] != user_id}

    def get_summary(self, user_id, session_id):
        return self.summaries.get((user_id, session_id))

    def save_summary(self, user_id, session_id, summary):
        self.summaries[(user_id, session_id)] = summary

    def recent_summaries(self, user_id, exclude_session, n):
        return [v for (u, s), v in self.summaries.items()
                if u == user_id and s != exclude_session][-n:]


class FakeClient:
    """Fake OpenAI client for embeddings + the three memory LLM jobs.
    Script it with `facts` (what the extractor returns) and `decision`."""

    def __init__(self, facts=None, decision=None):
        self.facts = facts or []
        self.decision = decision or {"action": "add", "id": None}
        self.calls = []  # names of LLM jobs, in order
        self.embeddings = NS(create=self._embed)
        self.chat = NS(completions=NS(create=self._chat))

    def _embed(self, model, input):
        data = [NS(index=i, embedding=fake_embedding(t)) for i, t in enumerate(input)]
        return NS(data=data)

    def _chat(self, model, messages, **kwargs):
        system = messages[0]["content"]
        if system.startswith("You extract"):
            self.calls.append("extract")
            content = json.dumps({"facts": self.facts})
        elif system.startswith("You maintain"):
            self.calls.append("decide")
            content = json.dumps(self.decision)
        elif system.startswith("You summarise"):
            self.calls.append("summarise")
            content = "A short summary."
        else:
            raise AssertionError(f"unexpected prompt: {system[:40]}")
        return NS(choices=[NS(message=NS(content=content))])
