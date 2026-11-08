"""Parse documents into blocks (paragraphs) that keep their source metadata:
the heading path for Markdown, the page number for PDFs."""
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

SUPPORTED_SUFFIXES = {".md", ".markdown", ".txt", ".pdf"}


@dataclass
class Block:
    text: str
    heading: str | None = None
    page: int | None = None


def clean(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def parse_markdown(text: str) -> list[Block]:
    """Paragraphs and fenced code blocks, each tagged with its heading path
    (e.g. 'Deployments and Rollbacks > Manual rollback')."""
    blocks: list[Block] = []
    stack: list[tuple[int, str]] = []
    buf: list[str] = []
    in_fence = False

    def heading() -> str | None:
        return " > ".join(t for _, t in stack) or None

    def flush():
        if buf and "".join(buf).strip():
            blocks.append(Block("\n".join(buf).strip(), heading()))
        buf.clear()

    for line in clean(text).split("\n"):
        if line.lstrip().startswith("```"):
            if not in_fence:
                flush()          # a code fence starts its own block
            buf.append(line)
            if in_fence:
                flush()          # ...and ends it
            in_fence = not in_fence
            continue
        if in_fence:
            buf.append(line)
            continue
        m = re.match(r"^(#{1,6})\s+(.*\S)\s*$", line)
        if m:
            flush()
            level = len(m.group(1))
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, m.group(2)))
        elif not line.strip():
            flush()
        else:
            buf.append(line)
    flush()
    return blocks


def _strip_page_furniture(pages: list[str]) -> list[str]:
    """Remove running headers/footers: lines that repeat on at least half the
    pages (page numbers are normalised so 'Page 3' matches 'Page 4')."""
    if len(pages) < 3:
        return pages

    def norm(line: str) -> str:
        return re.sub(r"\d+", "#", line.strip())

    counts = Counter(norm(l) for p in pages for l in set(p.split("\n")) if l.strip())
    repeated = {k for k, n in counts.items() if n >= len(pages) / 2}
    return ["\n".join(l for l in p.split("\n") if norm(l) not in repeated) for p in pages]


def parse_pdf(path: Path) -> list[Block]:
    from pypdf import PdfReader

    pages = [(p.extract_text() or "") for p in PdfReader(str(path)).pages]
    pages = _strip_page_furniture([clean(p) for p in pages])
    blocks: list[Block] = []
    for number, text in enumerate(pages, start=1):
        text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)  # re-join hyphenated words
        for para in re.split(r"\n\s*\n", text):
            if para.strip():
                blocks.append(Block(para.strip(), None, number))
    return blocks


def parse_file(path: Path) -> list[Block]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return parse_pdf(path)
    if suffix in {".md", ".markdown", ".txt"}:
        return parse_markdown(path.read_text(encoding="utf-8", errors="replace"))
    raise ValueError(f"Unsupported file type: {path.suffix}")
