"""Small helpers shared by the RAG steps."""
import os

from openai import OpenAI

from .config import RAG_MODEL


def make_client() -> OpenAI:
    return OpenAI(base_url="https://openrouter.ai/api/v1",
                  api_key=os.getenv("OPENROUTER_API_KEY"))


def chat(client, system: str, user: str, usage: dict | None = None,
         model: str = RAG_MODEL) -> str:
    """One deterministic chat call; adds token usage to `usage["total"]`."""
    response = client.chat.completions.create(
        model=model, temperature=0,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
    )
    if usage is not None and getattr(response, "usage", None):
        usage["total"] = usage.get("total", 0) + (response.usage.total_tokens or 0)
    return response.choices[0].message.content or ""
