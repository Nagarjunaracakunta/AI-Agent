"""Ingestion pipeline: parse -> clean -> chunk -> embed -> store.

    python -m rag.ingest docs/                      # index a folder
    python -m rag.ingest docs/ --prune              # also drop deleted files
    python -m rag.ingest docs/ --target-tokens 200 --max-tokens 300 --overlap-tokens 40

Re-running is cheap: unchanged files (same content + chunk settings) are
skipped. Run it on a schedule to keep the index fresh.
"""
import argparse
import hashlib
from pathlib import Path

from memory.embeddings import embed

from .chunk import chunk_blocks
from .config import (CHUNKER_VERSION, CHUNK_MAX_TOKENS, CHUNK_OVERLAP_TOKENS, CHUNK_TARGET_TOKENS,
                     DEFAULT_COLLECTION, EMBEDDING_MODEL)
from .parse import SUPPORTED_SUFFIXES, parse_file

EMBED_BATCH = 64


def discover(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    return sorted(p for p in root.rglob("*")
                  if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES
                  and not any(part.startswith(".") for part in p.parts))


def embedding_text(source: str, heading: str | None, text: str) -> str:
    """What gets embedded: the chunk plus where it came from (adds context
    the chunk alone may lack, e.g. which runbook and section)."""
    return f"{source} — {heading}\n{text}" if heading else f"{source}\n{text}"


def ingest(client, store, root: Path, collection: str = DEFAULT_COLLECTION, *,
           target: int = CHUNK_TARGET_TOKENS, max_tokens: int = CHUNK_MAX_TOKENS,
           overlap: int = CHUNK_OVERLAP_TOKENS, prune: bool = False,
           embed_fn=embed, log=print) -> dict:
    root = Path(root)
    base = root if root.is_dir() else root.parent
    summary = {"indexed": [], "skipped": [], "empty": [], "pruned": [], "chunks": 0}

    files = discover(root)
    for path in files:
        source = path.relative_to(base).as_posix()
        # The hash covers the chunk settings, chunker version and embedding
        # model too, so changing any of them re-indexes everything.
        digest = hashlib.sha256(
            path.read_bytes() + f"|{target}|{max_tokens}|{overlap}|{EMBEDDING_MODEL}|v{CHUNKER_VERSION}".encode()
        ).hexdigest()

        existing = store.get_document(collection, source)
        if existing and existing["content_hash"] == digest:
            summary["skipped"].append(source)
            log(f"  skip     {source} (unchanged)")
            continue

        chunks = chunk_blocks(parse_file(path), target, max_tokens, overlap)
        if not chunks:
            summary["empty"].append(source)
            log(f"  empty    {source} (no text found)")
            continue

        texts = [embedding_text(source, c.heading, c.text) for c in chunks]
        vectors = []
        for i in range(0, len(texts), EMBED_BATCH):
            vectors += embed_fn(client, texts[i:i + EMBED_BATCH])

        store.replace_document(collection, source, digest, [
            {"index": c.index, "text": c.text, "heading": c.heading, "page": c.page,
             "embedding": v} for c, v in zip(chunks, vectors)])
        summary["indexed"].append(source)
        summary["chunks"] += len(chunks)
        log(f"  indexed  {source} -> {len(chunks)} chunks")

    if prune:
        summary["pruned"] = store.prune(collection, {
            p.relative_to(base).as_posix() for p in files})
        for s in summary["pruned"]:
            log(f"  pruned   {s} (file no longer exists)")
    return summary


def main():
    from .llm import make_client
    from .store import RagStore

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", type=Path, help="file or folder to index")
    ap.add_argument("--collection", default=DEFAULT_COLLECTION)
    ap.add_argument("--target-tokens", type=int, default=CHUNK_TARGET_TOKENS)
    ap.add_argument("--max-tokens", type=int, default=CHUNK_MAX_TOKENS)
    ap.add_argument("--overlap-tokens", type=int, default=CHUNK_OVERLAP_TOKENS)
    ap.add_argument("--prune", action="store_true",
                    help="remove indexed documents whose files are gone")
    a = ap.parse_args()

    print(f"Ingesting {a.path} into collection '{a.collection}'")
    s = ingest(make_client(), RagStore(), a.path, a.collection, target=a.target_tokens,
               max_tokens=a.max_tokens, overlap=a.overlap_tokens, prune=a.prune)
    print(f"Done: {len(s['indexed'])} indexed ({s['chunks']} chunks), "
          f"{len(s['skipped'])} unchanged, {len(s['pruned'])} pruned")


if __name__ == "__main__":
    main()
