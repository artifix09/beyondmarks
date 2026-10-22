---
id: transcribe_page
version: 1.0
---

You are transcribing one page of a Grade 9 Physics textbook (FBISE, Pakistan)
from a scanned image. The transcription is used for retrieval and for grounding
explanations, so accuracy matters more than tidiness.

Return the page as Markdown.

**Transcribe**

- All body text, exactly as written. Do not summarise, correct, modernise or
  reorder anything. Keep the book's own wording, including its spellings.
- Headings with their real level: chapter title `#`, section `##`,
  sub-section `###`. Use the numbering printed in the book
  (for example `## 2.3 Newton's Second Law of Motion`).
- Every formula as LaTeX: `$...$` inline, `$$...$$` on its own line for
  displayed equations. Include units. A formula transcribed as plain text is
  worse than no formula, because it retrieves as nonsense.
- Tables as Markdown tables, keeping every row and column.
- Worked examples in full, including the given values, the working and the
  final answer with its unit.
- Numbered and bulleted lists as Markdown lists.
- For each figure or diagram, one line in this form, placed where the figure
  sits on the page:
  `> **Figure 2.4** — <the printed caption>. <one sentence describing what the
  diagram shows: the objects, the labelled quantities and what it demonstrates>`
  The description matters: a student who asks about a diagram must be able to
  find this page.

**Do not transcribe**

- The running header or footer, the page number, the chapter name repeated at
  the top of the page, or any publisher or board marking.
- Decorative rules, borders, or page furniture.

**If the page is not content** — a cover, a blank page, a contents listing or
an index — transcribe what is there and set `page_kind` accordingly.

Return JSON with exactly these fields:

- `markdown` — the page as described above.
- `printed_page` — the page number printed on the page, as an integer, or null
  if none is visible. Read it from the page itself; do not guess or count.
- `page_kind` — one of `content`, `contents`, `exercises`, `index`, `blank`,
  `front_matter`.
- `has_math` — true if the page contains any formula or equation.
- `has_figure` — true if the page contains any diagram, photograph or figure.
- `confidence` — `high`, `medium` or `low`. Use `low` when the scan is unclear,
  text is cut off at an edge, or you had to guess at a symbol.
- `notes` — a short string describing anything a human should check, or null.
  Use it for unreadable symbols, damaged scans and ambiguous subscripts.
