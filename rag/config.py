import os

# Reuses the project's DB / embedding settings (this also loads .env).
from memory.config import DATABASE_URL, EMBEDDING_DIM, EMBEDDING_MODEL  # noqa: F401

RAG_MODEL = os.getenv("RAG_MODEL", "openai/gpt-4o-mini")  # answer, rerank, verify
DEFAULT_COLLECTION = os.getenv("RAG_COLLECTION", "default")

# Chunking (blueprint: 500-800 tokens + overlap)
CHUNK_TARGET_TOKENS = 500
CHUNK_MAX_TOKENS = 800
CHUNK_OVERLAP_TOKENS = 100
CHUNKER_VERSION = 2   # bump when chunking logic changes: forces re-indexing

# Retrieval: fetch wide, rerank, keep a few
RETRIEVE_K = 20
RERANK_TOP_N = 5
MIN_RERANK_SCORE = 3      # 0-10; passages below this are treated as irrelevant

# Agentic loop: how many times a failed self-check may trigger a retry
MAX_RETRIES = 2

REFUSAL = "I couldn't find this in the documents."
