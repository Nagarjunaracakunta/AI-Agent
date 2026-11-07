import os

from dotenv import load_dotenv

# Load .env here so settings are right regardless of import order.
load_dotenv()

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://assistant:assistant@localhost:5432/assistant"
)

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "openai/text-embedding-3-small")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1536"))
UTILITY_MODEL = os.getenv("MEMORY_MODEL", "openai/gpt-4o-mini")  # extract/judge/summarise

# Recall: top-k by cosine similarity. Short queries ("suggest a project idea")
# score low against related facts (~0.2), so the floor is deliberately low.
RECALL_K = 5
RECALL_MIN_SIMILARITY = 0.10

# Dedupe (calibrated on text-embedding-3-small):
#   paraphrase ~0.9, contradiction ("lives in A" vs "lives in B") ~0.7
DUPLICATE_SIMILARITY = 0.90   # at/above: same fact, refresh it, no LLM call
CANDIDATE_SIMILARITY = 0.50   # at/above: ask the LLM to ADD / UPDATE / SKIP

# Short-term buffer and summarising
SHORT_TERM_MAX_TURNS = 100
SHORT_TERM_TTL_SECONDS = 7 * 24 * 3600
SUMMARY_AFTER_TURNS = 20      # summarise sessions longer than this
KEEP_RECENT_TURNS = 6         # raw turns kept after summarising
