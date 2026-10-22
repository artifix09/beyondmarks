"""Gate D, as tests.

Every assertion here is a chunking failure that would otherwise only show up
as "retrieval feels bad" three days later, when it is much harder to trace.
"""

from __future__ import annotations

import pytest

from chunker import PageText, chunk_pages

LOREM = (
    "A body continues in its state of rest or of uniform motion in a straight "
    "line unless acted upon by an external unbalanced force. This property of "
    "a body is called inertia and it depends on the mass of the body. "
)


def words(n: int) -> str:
    """Roughly n words of plausible physics prose."""
    out: list[str] = []
    while len(" ".join(out).split()) < n:
        out.append(LOREM)
    return " ".join(" ".join(out).split()[:n])


def page(idx: int, printed: int | None, md: str) -> PageText:
    return PageText(pdf_index=idx, printed_page=printed, markdown=md)


# --- sizing -------------------------------------------------------------


def test_long_section_splits_into_several_chunks():
    pages = [page(10, 1, f"## Inertia\n\n{words(900)}\n")]
    chunks = chunk_pages(pages)
    assert len(chunks) >= 2
    assert all(c.words > 0 for c in chunks)


def test_chunks_stay_near_the_word_budget():
    pages = [page(10, 1, f"## Inertia\n\n{words(1500)}\n")]
    chunks = chunk_pages(pages)
    # The last chunk may be short; the rest should sit in a sane band.
    for chunk in chunks[:-1]:
        assert 100 <= chunk.words <= 600, chunk.words


def test_short_page_makes_one_chunk():
    pages = [page(10, 1, f"## Inertia\n\n{words(80)}\n")]
    chunks = chunk_pages(pages)
    assert len(chunks) == 1


def test_runt_chunk_is_merged_away():
    """A trailing fragment must not become its own 20-word chunk."""
    pages = [page(10, 1, f"## Inertia\n\n{words(320)}\n\n{words(15)}\n")]
    chunks = chunk_pages(pages)
    assert all(c.words >= 100 for c in chunks), [c.words for c in chunks]


# --- atomic blocks ------------------------------------------------------


def test_display_formula_is_never_split():
    formula = "$$\nF = m a \\quad \\text{and} \\quad p = m v\n$$"
    pages = [page(10, 1, f"## Second Law\n\n{words(290)}\n\n{formula}\n\n{words(290)}\n")]
    chunks = chunk_pages(pages)
    holding = [c for c in chunks if "F = m a" in c.content]
    assert len(holding) == 1
    assert holding[0].content.count("$$") == 2


def test_table_is_never_split():
    table = "\n".join(
        ["| Quantity | Symbol | Unit |", "|---|---|---|"]
        + [f"| Quantity {i} | q{i} | unit{i} |" for i in range(12)]
    )
    pages = [page(10, 1, f"## Units\n\n{words(290)}\n\n{table}\n\n{words(290)}\n")]
    chunks = chunk_pages(pages)
    holding = [c for c in chunks if "| Quantity 0 |" in c.content]
    assert len(holding) == 1
    assert "| Quantity 11 |" in holding[0].content


# --- headings -----------------------------------------------------------


def test_chunk_never_crosses_a_heading():
    pages = [
        page(10, 1, f"## Inertia\n\n{words(60)}\n\n## Momentum\n\n{words(60)}\n")
    ]
    chunks = chunk_pages(pages)
    assert len(chunks) == 2
    assert chunks[0].heading == "Inertia"
    assert chunks[1].heading == "Momentum"


def test_heading_path_nests():
    md = f"# Chapter 3 Dynamics\n\n## Newton's Laws\n\n### Second Law\n\n{words(60)}\n"
    chunks = chunk_pages([page(10, 1, md)])
    assert chunks[0].heading == "Chapter 3 Dynamics / Newton's Laws / Second Law"


def test_sibling_heading_pops_the_stack():
    md = (
        f"## Newton's Laws\n\n### First Law\n\n{words(60)}\n\n"
        f"### Second Law\n\n{words(60)}\n"
    )
    chunks = chunk_pages([page(10, 1, md)])
    assert chunks[-1].heading == "Newton's Laws / Second Law"


# --- pages --------------------------------------------------------------


def test_printed_pages_are_recorded_not_pdf_indices():
    """The student is told "page 34", not "PDF page 48"."""
    pages = [page(48, 34, f"## Inertia\n\n{words(60)}\n")]
    chunk = chunk_pages(pages)[0]
    assert (chunk.page_start, chunk.page_end) == (34, 34)
    assert (chunk.pdf_page_start, chunk.pdf_page_end) == (48, 48)


def test_chunk_spanning_two_pages_reports_a_range():
    pages = [
        page(48, 34, f"## Inertia\n\n{words(150)}"),
        page(49, 35, f"{words(150)}\n"),
    ]
    chunk = chunk_pages(pages)[0]
    assert chunk.page_start == 34
    assert chunk.page_end == 35


def test_unnumbered_front_matter_does_not_crash():
    pages = [page(3, None, f"## Preface\n\n{words(60)}\n")]
    chunk = chunk_pages(pages)[0]
    assert chunk.page_start is None
    assert chunk.pdf_page_start == 3


# --- page breaks --------------------------------------------------------


def test_sentence_cut_by_a_page_break_is_rejoined():
    pages = [
        page(48, 34, "## Inertia\n\nThe acceleration produced in a body is"),
        page(49, 35, "directly proportional to the applied force.\n"),
    ]
    chunks = chunk_pages(pages)
    assert len(chunks) == 1
    assert "body is directly proportional" in chunks[0].content


def test_finished_sentence_is_not_glued_to_the_next_page():
    pages = [
        page(48, 34, f"## Inertia\n\n{words(40)}."),
        page(49, 35, "A new paragraph starts here on the next page.\n"),
    ]
    chunks = chunk_pages(pages)
    assert "\n\n" in chunks[0].content


# --- overlap ------------------------------------------------------------


def test_consecutive_chunks_overlap():
    pages = [page(10, 1, f"## Inertia\n\n{words(1200)}\n")]
    chunks = chunk_pages(pages, overlap_words=45)
    assert len(chunks) >= 2
    first_tail = set(chunks[0].content.split()[-30:])
    second_head = set(chunks[1].content.split()[:60])
    assert first_tail & second_head


def test_overlap_can_be_turned_off():
    pages = [page(10, 1, f"## Inertia\n\n{words(1200)}\n")]
    chunks = chunk_pages(pages, overlap_words=0)
    joined = sum(c.words for c in chunks)
    assert joined <= 1250  # no material duplication


def test_formula_is_not_duplicated_by_overlap():
    """Repeating a formula across chunks returns the same block twice."""
    formula = "$$\nE_k = \\tfrac{1}{2} m v^2\n$$"
    pages = [page(10, 1, f"## Energy\n\n{words(290)}\n\n{formula}\n\n{words(600)}\n")]
    chunks = chunk_pages(pages)
    assert sum(c.content.count("E_k") for c in chunks) == 1


# --- whole chapter ------------------------------------------------------


def test_a_realistic_chapter_produces_sane_chunks():
    pages = [
        page(48, 34, f"# Chapter 3 Dynamics\n\n## Force\n\n{words(260)}"),
        page(49, 35, f"{words(240)}\n\n$$\nF = ma\n$$\n"),
        page(50, 36, f"## Momentum\n\n{words(300)}"),
        page(51, 37, f"{words(280)}\n\n| Quantity | Unit |\n|---|---|\n| Force | N |\n"),
    ]
    chunks = chunk_pages(pages)

    assert chunks, "chapter produced no chunks"
    for c in chunks:
        assert c.content.strip()
        assert c.page_start is not None and c.page_end is not None
        assert c.page_start <= c.page_end
        assert c.page_end - c.page_start <= 3, "a chunk should not span the chapter"
        assert c.heading

    # Pages come out in order and cover the chapter.
    assert min(c.page_start for c in chunks) == 34
    assert max(c.page_end for c in chunks) == 37


@pytest.mark.parametrize("n_pages", [1, 5, 20])
def test_no_content_is_lost(n_pages: int):
    """Every page's marker word survives into some chunk."""
    pages = [
        page(10 + i, 1 + i, f"## Section {i}\n\nmarker{i} {words(200)}\n")
        for i in range(n_pages)
    ]
    chunks = chunk_pages(pages)
    all_text = " ".join(c.content for c in chunks)
    for i in range(n_pages):
        assert f"marker{i}" in all_text
