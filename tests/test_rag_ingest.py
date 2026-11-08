import tempfile
from pathlib import Path

from rag.chunk import chunk_blocks, count_tokens, split_long
from rag.parse import Block, parse_markdown, parse_pdf
from rag.store import to_or_query

MD = """# Runbook

Intro paragraph.

## Rollback

To roll back, run:

```
deployctl rollback --service x

still inside the code block
```

Rollbacks take 3 minutes.

## Backups

Backups are kept 14 days.
"""


def test_markdown_headings_and_code_fences():
    blocks = parse_markdown(MD)
    by_text = {b.text: b for b in blocks}
    assert by_text["Intro paragraph."].heading == "Runbook"
    assert by_text["Rollbacks take 3 minutes."].heading == "Runbook > Rollback"
    assert by_text["Backups are kept 14 days."].heading == "Runbook > Backups"
    code = next(b for b in blocks if b.text.startswith("```"))
    # the blank line inside the fence must not split the code block
    assert "deployctl rollback" in code.text and "still inside the code block" in code.text


def test_lead_in_is_kept_with_its_command():
    chunks = chunk_blocks(parse_markdown(MD), target=20, max_tokens=60, overlap=0)
    joined = [c.text for c in chunks if "deployctl rollback" in c.text]
    assert joined and "To roll back, run:" in joined[0]


def test_chunks_respect_max_tokens_and_overlap():
    para = "Sentence number {} is here to add some length to the text. "
    blocks = [Block("".join(para.format(i * 10 + j) for j in range(8)), "Doc") for i in range(12)]
    chunks = chunk_blocks(blocks, target=150, max_tokens=250, overlap=60)
    assert len(chunks) > 3
    assert all(c.tokens <= 250 for c in chunks)
    # overlap: paragraphs (~110 tokens) are bigger than the 60-token budget, so the
    # last *sentence* of each chunk must reappear at the start of the next one
    import re
    for a, b in zip(chunks, chunks[1:]):
        last_sentence = re.findall(r"Sentence number \d+", a.text)[-1]
        assert last_sentence in b.text
        assert b.text.startswith("Sentence number")        # carried tail comes first


def test_overlap_of_small_blocks_carries_whole_blocks():
    blocks = [Block(f"Step {i}: do the thing carefully.", "Doc") for i in range(30)]
    chunks = chunk_blocks(blocks, target=60, max_tokens=100, overlap=25)
    for a, b in zip(chunks, chunks[1:]):
        last_step = a.text.split("\n\n")[-1]
        assert last_step in b.text


def test_no_overlap_means_no_repeated_text():
    blocks = [Block(f"Unique paragraph {i}. " * 15, "Doc") for i in range(10)]
    chunks = chunk_blocks(blocks, target=100, max_tokens=200, overlap=0)
    all_text = "\n\n".join(c.text for c in chunks)
    for i in range(10):
        assert all_text.count(f"Unique paragraph {i}.") == 15


def test_oversized_block_is_split():
    huge = "A long sentence about nothing in particular. " * 200
    pieces = split_long(huge, 100)
    assert len(pieces) > 5 and all(count_tokens(p) <= 100 for p in pieces)
    assert chunk_blocks([Block(huge)], target=100, max_tokens=150, overlap=0)


def test_tiny_tail_is_merged_not_orphaned():
    blocks = [Block("word " * 150, "A"), Block("tail.", "A")]
    chunks = chunk_blocks(blocks, target=140, max_tokens=400, overlap=0)
    assert len(chunks) == 1 and chunks[0].text.endswith("tail.")


def test_chunk_heading_lists_every_section_it_covers():
    blocks = [Block("a " * 10, "Doc > One"), Block("b " * 10, "Doc > Two")]
    [chunk] = chunk_blocks(blocks, target=500, max_tokens=800, overlap=0)
    assert chunk.heading == "Doc > One | Doc > Two"


def test_empty_input():
    assert chunk_blocks([]) == []


def test_keyword_query_uses_or_semantics():
    assert to_or_query("How do I roll back? TLS-1042!") == "how | do | i | roll | back | tls | 1042"
    assert to_or_query("???") == ""


def _make_pdf(pages):
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for lines in pages:
        n = len(objs) + 1
        stream = "BT /F1 12 Tf 72 720 Td 14 TL " + " ".join(f"({l}) Tj T*" for l in lines) + " ET"
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {n} 0 R "
                    f"/Resources << /Font << /F1 3 0 R >> >> >>")
        kids.append(f"{n + 1} 0 R")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(pages)} >>"
    out, offsets = "%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n" + "".join(f"{o:010d} 00000 n \n" for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    return out.encode("latin-1")


def test_pdf_pages_and_running_headers_removed():
    pdf = _make_pdf([["ACME Confidential", "Rollback takes 3 minutes.", "Page 1"],
                     ["ACME Confidential", "Backups are kept 14 days.", "Page 2"],
                     ["ACME Confidential", "Certificates renew at 30 days.", "Page 3"]])
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "t.pdf"
        path.write_bytes(pdf)
        blocks = parse_pdf(path)
    assert [(b.page, b.text) for b in blocks] == [
        (1, "Rollback takes 3 minutes."), (2, "Backups are kept 14 days."),
        (3, "Certificates renew at 30 days.")]
