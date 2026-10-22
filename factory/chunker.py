"""Turn transcribed pages into retrieval chunks.

Pure functions over plain data: no database, no network, no Gemini. That is
what lets the tests run the whole chunker over a fake book in milliseconds,
and it is why this file is where the chunking rules live rather than inside
the ingestion script.

Two rules do most of the work:

  1. Never split an atomic block. A display formula, a Markdown table or a
     worked example that gets cut in half retrieves as nonsense and explains
     as nonsense. A chunk is allowed to run over the word budget to keep one
     whole.

  2. Carry the printed page with every block. The student is told "page 34",
     so page numbers have to survive chunking, including across the page
     breaks that cut sentences in half in every scanned textbook.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Chunk sizing, in words. CLAUDE.md section 5 asks for 200-400.
TARGET_WORDS = 300
MAX_WORDS = 400
MIN_WORDS = 120
OVERLAP_WORDS = 45

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
# Tokens that end in a full stop without ending a sentence. A physics book is
# full of them, and "Fig." or "9.8 m/s" splitting a sentence in half would put
# half a statement in each chunk.
ABBREVIATIONS = {
    "fig.", "figs.", "eq.", "eqs.", "no.", "nos.", "e.g.", "i.e.", "etc.",
    "vs.", "approx.", "dr.", "mr.", "mrs.", "ms.", "prof.", "sec.", "ch.",
    "vol.", "p.", "pp.", "cf.", "ref.", "refs.",
}
TABLE_ROW_RE = re.compile(r"^\s*\|")
DISPLAY_MATH_RE = re.compile(r"^\s*\$\$")
FENCE_RE = re.compile(r"^\s*```")
# A paragraph that ends without sentence-final punctuation is probably cut off
# by the page break rather than finished.
SENTENCE_END_RE = re.compile(r"[.!?:;\"')\]]\s*$")


@dataclass(frozen=True)
class PageText:
    """One transcribed page.

    `printed_page` is the number the student sees on the paper page, which is
    not the PDF index: front matter offsets them. It may be None for pages
    before the numbering starts.
    """

    pdf_index: int
    printed_page: int | None
    markdown: str


@dataclass
class Block:
    """An indivisible piece of a page: paragraph, heading, table or formula."""

    kind: str  # paragraph | heading | table | math | list | code
    text: str
    pages: list[int | None] = field(default_factory=list)
    pdf_pages: list[int] = field(default_factory=list)
    level: int = 0  # headings only

    @property
    def words(self) -> int:
        return len(self.text.split())


@dataclass(frozen=True)
class Chunk:
    """What lands in one textbook_chunks row."""

    heading: str | None
    content: str
    page_start: int | None
    page_end: int | None
    pdf_page_start: int
    pdf_page_end: int

    @property
    def words(self) -> int:
        return len(self.content.split())


def _parse_blocks(markdown: str, page: int | None, pdf_index: int) -> list[Block]:
    """Split one page's Markdown into atomic blocks, tagged with its page."""
    lines = markdown.splitlines()
    blocks: list[Block] = []
    buf: list[str] = []
    kind = "paragraph"

    def flush() -> None:
        nonlocal buf, kind
        text = "\n".join(buf).strip()
        if text:
            blocks.append(
                Block(kind=kind, text=text, pages=[page], pdf_pages=[pdf_index])
            )
        buf = []
        kind = "paragraph"

    i = 0
    while i < len(lines):
        line = lines[i]

        if not line.strip():
            flush()
            i += 1
            continue

        heading = HEADING_RE.match(line)
        if heading:
            flush()
            blocks.append(
                Block(
                    kind="heading",
                    text=heading.group(2),
                    pages=[page],
                    pdf_pages=[pdf_index],
                    level=len(heading.group(1)),
                )
            )
            i += 1
            continue

        if DISPLAY_MATH_RE.match(line):
            flush()
            body = [line]
            i += 1
            # Run to the closing $$ — or to the end of the page, because a
            # formula split by a page break is still one formula.
            while i < len(lines):
                body.append(lines[i])
                if "$$" in lines[i]:
                    i += 1
                    break
                i += 1
            blocks.append(
                Block(
                    kind="math",
                    text="\n".join(body),
                    pages=[page],
                    pdf_pages=[pdf_index],
                )
            )
            continue

        if FENCE_RE.match(line):
            flush()
            body = [line]
            i += 1
            while i < len(lines):
                body.append(lines[i])
                if FENCE_RE.match(lines[i]):
                    i += 1
                    break
                i += 1
            blocks.append(
                Block(
                    kind="code",
                    text="\n".join(body),
                    pages=[page],
                    pdf_pages=[pdf_index],
                )
            )
            continue

        if TABLE_ROW_RE.match(line):
            flush()
            body = []
            while i < len(lines) and TABLE_ROW_RE.match(lines[i]):
                body.append(lines[i])
                i += 1
            blocks.append(
                Block(
                    kind="table",
                    text="\n".join(body),
                    pages=[page],
                    pdf_pages=[pdf_index],
                )
            )
            continue

        buf.append(line)
        i += 1

    flush()
    return blocks


def _join_pages(pages: list[PageText]) -> list[Block]:
    """Parse every page and stitch paragraphs that the page break cut in half."""
    blocks: list[Block] = []
    for page in pages:
        page_blocks = _parse_blocks(page.markdown, page.printed_page, page.pdf_index)
        if (
            blocks
            and page_blocks
            and blocks[-1].kind == "paragraph"
            and page_blocks[0].kind == "paragraph"
            and not SENTENCE_END_RE.search(blocks[-1].text)
        ):
            tail, head = blocks[-1], page_blocks.pop(0)
            tail.text = f"{tail.text} {head.text}".strip()
            tail.pages = tail.pages + head.pages
            tail.pdf_pages = tail.pdf_pages + head.pdf_pages
        blocks.extend(page_blocks)
    return blocks


def _sentences(text: str) -> list[str]:
    """Split prose into sentences, keeping abbreviations and decimals intact."""
    rough = SENTENCE_SPLIT_RE.split(text)
    out: list[str] = []
    for piece in rough:
        last = out[-1].split()[-1].lower() if out and out[-1].split() else ""
        # A single initial ("A.") or a known abbreviation did not end a sentence.
        if out and (last in ABBREVIATIONS or (len(last) == 2 and last[0].isalpha() and last[1] == ".")):
            out[-1] = f"{out[-1]} {piece}"
        else:
            out.append(piece)
    return [s for s in out if s.strip()]


def _split_long_prose(block: Block, target_words: int) -> list[Block]:
    """Break an oversized paragraph at sentence boundaries.

    The no-splitting rule protects tables and formulas, where half a block is
    meaningless. Prose is different: one 900-word paragraph left whole is a
    chunk that matches everything and answers nothing, so it is split — but
    only between sentences, never mid-statement.
    """
    if block.kind not in ("paragraph", "list") or block.words <= target_words:
        return [block]

    pieces: list[Block] = []
    current: list[str] = []
    count = 0
    for sentence in _sentences(block.text):
        current.append(sentence)
        count += len(sentence.split())
        if count >= target_words:
            pieces.append(
                Block(
                    kind=block.kind,
                    text=" ".join(current),
                    pages=list(block.pages),
                    pdf_pages=list(block.pdf_pages),
                )
            )
            current, count = [], 0
    if current:
        pieces.append(
            Block(
                kind=block.kind,
                text=" ".join(current),
                pages=list(block.pages),
                pdf_pages=list(block.pdf_pages),
            )
        )
    return pieces or [block]


def _heading_path(stack: list[Block]) -> str | None:
    if not stack:
        return None
    return " / ".join(b.text for b in stack)


def _pages_of(blocks: list[Block]) -> tuple[int | None, int | None, int, int]:
    printed = [p for b in blocks for p in b.pages if p is not None]
    pdf = [p for b in blocks for p in b.pdf_pages]
    return (
        min(printed) if printed else None,
        max(printed) if printed else None,
        min(pdf) if pdf else 0,
        max(pdf) if pdf else 0,
    )


def _overlap_tail(blocks: list[Block], words: int) -> list[Block]:
    """The last few blocks of a chunk, repeated at the top of the next one.

    Overlap keeps a sentence that straddles a chunk boundary findable. Only
    prose carries over: repeating a table or a formula would return the same
    block twice for one query.
    """
    if words <= 0 or not blocks:
        return []

    last = blocks[-1]
    # A trailing table or formula is not carried: the same block retrieved
    # twice is noise, not continuity.
    if last.kind not in ("paragraph", "list"):
        return []

    sentences = _sentences(last.text)
    picked: list[str] = []
    total = 0
    for sentence in reversed(sentences):
        picked.insert(0, sentence)
        total += len(sentence.split())
        if total >= words:
            break

    # One sentence longer than twice the budget is not an overlap, it is a
    # duplicate. Skip it rather than copying a paragraph into two chunks.
    if total > words * 2:
        return []

    return [
        Block(
            kind=last.kind,
            text=" ".join(picked),
            pages=list(last.pages),
            pdf_pages=list(last.pdf_pages),
        )
    ]


def chunk_pages(
    pages: list[PageText],
    *,
    target_words: int = TARGET_WORDS,
    max_words: int = MAX_WORDS,
    min_words: int = MIN_WORDS,
    overlap_words: int = OVERLAP_WORDS,
) -> list[Chunk]:
    """Chunk a run of pages — normally one chapter — by heading, then by size.

    A chunk never crosses a heading, never splits a block, and always knows
    which printed pages it came from.
    """
    blocks = [
        piece
        for block in _join_pages(pages)
        for piece in _split_long_prose(block, target_words)
    ]
    chunks: list[Chunk] = []

    stack: list[Block] = []
    current: list[Block] = []

    def emit() -> None:
        nonlocal current
        body = [b for b in current if b.kind != "heading"]
        if not body:
            current = []
            return
        content = "\n\n".join(b.text for b in current).strip()
        p_start, p_end, pdf_start, pdf_end = _pages_of(current)
        chunks.append(
            Chunk(
                heading=_heading_path(stack),
                content=content,
                page_start=p_start,
                page_end=p_end,
                pdf_page_start=pdf_start,
                pdf_page_end=pdf_end,
            )
        )
        current = []

    for block in blocks:
        if block.kind == "heading":
            emit()
            while stack and stack[-1].level >= block.level:
                stack.pop()
            stack.append(block)
            continue

        words_so_far = sum(b.words for b in current)

        # Emit before adding, when adding would overshoot and we already have
        # enough. The block itself is never cut.
        if current and words_so_far >= target_words:
            carried = _overlap_tail(current, overlap_words) if overlap_words else []
            emit()
            current = list(carried)
        elif current and words_so_far + block.words > max_words and words_so_far >= min_words:
            carried = _overlap_tail(current, overlap_words) if overlap_words else []
            emit()
            current = list(carried)

        current.append(block)

    emit()
    return _merge_runts(chunks, min_words)


def _merge_runts(chunks: list[Chunk], min_words: int) -> list[Chunk]:
    """Fold a too-short chunk into the one before it, under the same heading.

    A 20-word chunk is a retrieval hazard: it matches a query strongly on a
    fragment and then carries no information to answer it.
    """
    merged: list[Chunk] = []
    for chunk in chunks:
        if (
            merged
            and chunk.words < min_words
            and merged[-1].heading == chunk.heading
        ):
            prev = merged.pop()
            starts = [p for p in (prev.page_start, chunk.page_start) if p is not None]
            ends = [p for p in (prev.page_end, chunk.page_end) if p is not None]
            merged.append(
                Chunk(
                    heading=prev.heading,
                    content=f"{prev.content}\n\n{chunk.content}",
                    page_start=min(starts) if starts else None,
                    page_end=max(ends) if ends else None,
                    pdf_page_start=min(prev.pdf_page_start, chunk.pdf_page_start),
                    pdf_page_end=max(prev.pdf_page_end, chunk.pdf_page_end),
                )
            )
        else:
            merged.append(chunk)
    return merged
