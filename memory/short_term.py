"""Short-term memory: the chat turns of one session, kept in Redis."""
import json

import redis

from .config import REDIS_URL, SHORT_TERM_MAX_TURNS, SHORT_TERM_TTL_SECONDS


class ShortTermMemory:
    def __init__(self, url: str = REDIS_URL, max_turns: int = SHORT_TERM_MAX_TURNS,
                 ttl_seconds: int = SHORT_TERM_TTL_SECONDS):
        self.r = redis.Redis.from_url(url, decode_responses=True, socket_timeout=3,
                                      socket_connect_timeout=3)
        self.r.ping()  # fail fast if Redis is unreachable
        self.max_turns = max_turns
        self.ttl = ttl_seconds

    @staticmethod
    def _key(session_id: str) -> str:
        return f"chat:{session_id}:turns"

    def add(self, session_id: str, role: str, content: str) -> None:
        key = self._key(session_id)
        pipe = self.r.pipeline()
        pipe.rpush(key, json.dumps({"role": role, "content": content}))
        pipe.ltrim(key, -self.max_turns, -1)
        pipe.expire(key, self.ttl)
        pipe.execute()

    def get(self, session_id: str) -> list[dict]:
        return [json.loads(x) for x in self.r.lrange(self._key(session_id), 0, -1)]

    def replace(self, session_id: str, turns: list[dict]) -> None:
        key = self._key(session_id)
        pipe = self.r.pipeline()
        pipe.delete(key)
        if turns:
            pipe.rpush(key, *[json.dumps(t) for t in turns])
            pipe.expire(key, self.ttl)
        pipe.execute()

    def clear(self, session_id: str) -> None:
        self.r.delete(self._key(session_id))
