"""Token-aware chunking with overlap.

Blocks (paragraphs / code blocks) are packed into chunks of roughly
`target` tokens, never above `max_tokens`. The tail of each chunk is repeated
at the start of the next one (`overlap` tokens) so a fact that straddles a
boundary is still retrievable.
"""
import re
from dataclasses import dataclass
from functools import lru_cache

from .config import CHUNK_MAX_TOKENS, CHUNK_OVERLAP_TOKENS, CHUNK_TARGET_TOKENS
from .parse import Block


@lru_cache(maxsize=1)
def _encoder():
    try:
        import tiktoken
        return tiktoken.get_encoding("cl100k_base")
    except Exception:  # offline / missing file: fall back to an estimate
        return None


def count_tokens(text: str) -> int:
    enc = _encoder()
    return len(enc.encode(text)) if enc else max(1, len(text) // 4)


@dataclass
class Chunk:
    index: int
    text: str
    heading: str | None
    page: int | None
    tokens: int


def split_long(text: str, max_tokens: int) -> list[str]:
    """Split one oversized block: by lines, then sentences, then words."""
    if count_tokens(text) <= max_tokens:
        return [text]
    for pattern, joiner in ((r"\n", "\n"), (r"(?<=[.!?])\s+", " "), (r"\s+", " ")):
        parts = [p for p in re.split(pattern, text) if p.strip()]
        if len(parts) > 1:
            out, cur = [], ""
            for p in parts:
                candidate = f"{cur}{joiner}{p}" if cur else p
                if cur and count_tokens(candidate) > max_tokens:
                    out.append(cur)
                    cur = p
                else:
                    cur = candidate
            if cur:
                out.append(cur)
            # a part may still be too big: recurse with the next, finer pattern
            return [piece for o in out for piece in
                    ([o] if count_tokens(o) <= max_tokens else split_long(o, max_tokens))]
    # single huge "word" (e.g. a base64 blob): hard split by characters
    step = max_tokens * 3
    return [text[i:i + step] for i in range(0, len(text), step)]


def tail_of(text: str, budget: int) -> str | None:
    """The last whole sentences/lines of `text` that fit in `budget` tokens."""
    units = [u for u in re.split(r"(?<=[.!?])\s+|\n", text) if u.strip()]
    taken: list[str] = []
    for u in reversed(units):
        if count_tokens(" ".join([u] + taken)) > budget:
            break
        taken.insert(0, u)
    if not taken or len(taken) == len(units):
        return None            # nothing fits, or it is the whole block anyway
    return " ".join(taken)


def chunk_blocks(blocks: list[Block], target: int = CHUNK_TARGET_TOKENS,
                 max_tokens: int = CHUNK_MAX_TOKENS,
                 overlap: int = CHUNK_OVERLAP_TOKENS) -> list[Chunk]:
    # 0. glue a lead-in ("... run:") to the code block / list it introduces
    glued: list[Block] = []
    for b in blocks:
        if glued and glued[-1].text.endswith(":") and glued[-1].heading == b.heading \
                and glued[-1].page == b.page:
            glued[-1] = Block(glued[-1].text + "\n" + b.text, b.heading, b.page)
        else:
            glued.append(b)

    # 1. make sure no single block exceeds the maximum
    items: list[tuple[Block, int]] = []
    for b in glued:
        for piece in split_long(b.text, max_tokens):
            items.append((Block(piece, b.heading, b.page), count_tokens(piece)))

    chunks: list[Chunk] = []
    cur: list[tuple[Block, int]] = []   # blocks in the chunk being built
    n_carried = 0                        # how many of `cur` are overlap from the previous chunk

    def total(xs):
        return sum(t for _, t in xs)

    def label(new):
        """Heading label: all distinct sections this chunk's new text covers."""
        seen = []
        for b, _ in new:
            if b.heading and b.heading not in seen:
                seen.append(b.heading)
        if not seen:
            return None
        return " | ".join(seen[:3]) + (" | ..." if len(seen) > 3 else "")

    def emit():
        nonlocal cur, n_carried
        new = cur[n_carried:]
        if not new:
            return
        text = "\n\n".join(b.text for b, _ in cur)
        chunks.append(Chunk(len(chunks), text, label(new), new[0][0].page, total(cur)))
        # carry the tail of this chunk into the next one as overlap
        carried: list[tuple[Block, int]] = []
        for item in reversed(cur):
            if total(carried) + item[1] > overlap:
                break
            carried.insert(0, item)
        if not carried and overlap > 0:
            # The last block is too big to repeat whole: repeat its tail instead,
            # so a fact straddling the boundary is still found.
            last = cur[-1][0]
            tail = tail_of(last.text, overlap)
            if tail:
                carried = [(Block(tail, last.heading, last.page), count_tokens(tail))]
        cur, n_carried = carried, len(carried)

    for item in items:
        block, tokens = item
        new_tokens = total(cur[n_carried:])
        heading_changed = bool(cur[n_carried:]) and block.heading != cur[n_carried][0].heading
        if cur[n_carried:] and (
            total(cur) + tokens > max_tokens
            or new_tokens >= target
            or (heading_changed and new_tokens >= target / 2)
        ):
            emit()
        if cur and total(cur) + tokens > max_tokens:
            cur, n_carried = [], 0       # overlap would overflow: drop it
        cur.append(item)

    new = cur[n_carried:]
    if new:
        # avoid a tiny orphan chunk: fold it into the previous one if it fits
        new_tokens = total(new)
        if chunks and new_tokens < 80 and chunks[-1].tokens + new_tokens <= max_tokens:
            last = chunks[-1]
            last.text += "\n\n" + "\n\n".join(b.text for b, _ in new)
            last.tokens += new_tokens
        else:
            emit()
    return chunks
