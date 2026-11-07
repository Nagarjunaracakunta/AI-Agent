from .config import EMBEDDING_MODEL


def embed(client, texts, model=EMBEDDING_MODEL):
    """Embed texts via OpenRouter's OpenAI-compatible /embeddings endpoint."""
    if not texts:
        return []
    response = client.embeddings.create(model=model, input=texts)
    return [d.embedding for d in sorted(response.data, key=lambda d: d.index)]
