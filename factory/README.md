# Content factory

Offline scripts. Nothing here runs inside the API, and nothing in the API imports from
here.

## M4 — ingesting the book

The book is a 222-page PDF with no text layer: every page is a scan, so every page has
to go through a vision model. Seven stages, each writing to disk, each resumable.

```
S1  page map        by hand, from the contents page          page_map.csv
S2  extract pages   PDF -> image files                       extract_pages.py
S3  transcribe      image -> Markdown + LaTeX, via Gemini     transcribe_pages.py
S4  chunk           Markdown -> retrieval chunks              chunker.py
S5  embed           chunks -> 768-dim vectors                 embed_and_load.py
S6  load            vectors -> textbook_chunks                embed_and_load.py
S7  validate        five gates                                validate_ingestion.py
```

### S0 — diagnose first

```bash
python -I inspect_pdf.py ../path/to/physics9.pdf --out ./work/pdf_check
```

Prints whether there is a text layer, the native scan DPI, and whether each page is a
single full-page image. Read the DPI off this before choosing a render setting: rendering
above the native resolution buys tokens, not detail.

### S1 — the page map

Copy `page_map.example.csv` to `page_map.csv` and fill it from the book's contents page.
About twenty minutes.

This is the only thing standing between a student and a wrong page citation. The printed
page number is not the PDF index — front matter usually offsets them by ten to twenty
pages — and `printed_page = printed_start + (pdf_index - pdf_start)` is how every
citation in the product gets computed. `embed_and_load.py` cross-checks the map against
the number the model read off each page and warns when they disagree.

### S2 — extract pages

```bash
python -I extract_pages.py ../path/to/physics9.pdf \
    --out ./work/pages --page-map page_map.csv
```

`--mode auto` pulls the embedded scan straight out when a page is a single full-page
image, which is lossless and faster than rendering, and falls back to rendering at
`--dpi` otherwise. Re-running skips pages already done.

### S3 — transcribe

```bash
# pilot first: ten pages, read every one of them
python -I transcribe_pages.py --pages ./work/pages --out ./work/transcripts \
    --only 14,15,22,23,40,41,55,56,70,71

# then the rest
python -I transcribe_pages.py --pages ./work/pages --out ./work/transcripts
```

Pick the pilot pages deliberately: two plain, two formula-heavy, two with tables, two
with figures, one contents page, one of the worst scans. Read all ten against the PDF
before spending the full run. The prompt is `prompts/transcribe_page.md` and it is
versioned — every transcript records which version produced it.

Pages the model marks `low` confidence are listed at the end. Read those.

### S4-S6 — chunk, embed, load

```bash
# chunk only, no API calls, no writes - check the counts look sane
python -I embed_and_load.py --book-id <uuid> --page-map page_map.csv --dry-run

# for real
python -I embed_and_load.py --book-id <uuid> --page-map page_map.csv --replace
```

Two things here are easy to get wrong and expensive to find later:

- Documents are embedded as `RETRIEVAL_DOCUMENT` and queries as `RETRIEVAL_QUERY`. They
  are different vectors from the same model, and mixing them up costs accuracy that
  looks exactly like bad chunking.
- `textbook_chunks.embedding` is `vector(768)` and the index is cosine. Gemini normalises
  only at full width, so a 768-dim output is re-normalised before insert.

### S7 — validate

```bash
python -I validate_ingestion.py --book-id <uuid> --gold gold_set.csv
```

| Gate | Checks | Fails when |
|---|---|---|
| C | every mapped page transcribed, nothing silently empty | a page vanished |
| D | chunk sizes, page ranges, no split formulas | the chunker is wrong |
| E | 768 dimensions, no zero vectors, one model recorded | the embedding step is wrong |
| F | a chunk's own sentence retrieves that chunk at rank 1 | **the pipeline is broken** |
| G | 50 known questions find the right page in the top 3 | **retrieval is not good enough yet** |

Gate F is the one people skip and the one that saves the day. It tells a pipeline bug —
wrong task type, missing normalisation, wrong distance operator — apart from mediocre
retrieval quality. Those have completely different fixes and look identical from the
outside.

Gate G is acceptance. 85% recall@3 is good; below 70% means fix chunking before building
anything on top of it. Build the gold set from the end-of-chapter exercises, where the
answer's page is already known — see `gold_set.example.csv`. Include about five questions
the book does not answer: they set the score threshold below which the chat says "I am
not sure" instead of inventing something.

## Running in Colab

Keep the logic here, not in the notebook. The notebook clones this repo, installs the
requirements and calls a script. That way the pipeline survives the runtime being
recycled, and it lives somewhere the team can review it.

Secrets go in the Colab secrets panel (the key icon in the sidebar), never in a cell:
`GEMINI_API_KEY`, `GEMINI_MODEL`, `GEMINI_EMBED_MODEL`, `SUPABASE_DB_URL`.

```python
# cell 1 - setup
import os, subprocess
from google.colab import userdata, drive

drive.mount('/content/drive')
for key in ('GEMINI_API_KEY', 'GEMINI_MODEL', 'GEMINI_EMBED_MODEL', 'SUPABASE_DB_URL'):
    os.environ[key] = userdata.get(key)

subprocess.run(['git', 'clone', 'https://github.com/artifix09/beyondmarks.git'])
subprocess.run(['pip', 'install', '-q', '-r', 'beyondmarks/factory/requirements.txt'])
os.chdir('beyondmarks/factory')
```

```python
# cell 2 - work under Drive so a recycled runtime loses nothing
BOOK = '/content/drive/MyDrive/beyondmarks/physics9.pdf'
WORK = '/content/drive/MyDrive/beyondmarks/work'

!python inspect_pdf.py "$BOOK" --out "$WORK/pdf_check"
```

```python
# cell 3 - extract, then pilot ten pages
!python extract_pages.py "$BOOK" --out "$WORK/pages" --page-map page_map.csv
!python transcribe_pages.py --pages "$WORK/pages" --out "$WORK/transcripts" \
    --only 14,15,22,23,40,41,55,56,70,71
```

```python
# cell 4 - the full run, after the pilot pages read correctly
!python transcribe_pages.py --pages "$WORK/pages" --out "$WORK/transcripts"
```

```python
# cell 5 - chunk, embed, load, validate
BOOK_ID = '<uuid from the books table>'
!python embed_and_load.py --book-id $BOOK_ID --page-map page_map.csv \
    --transcripts "$WORK/transcripts" --replace
!python validate_ingestion.py --book-id $BOOK_ID --transcripts "$WORK/transcripts" \
    --gold gold_set.csv
```

Free Colab disconnects after roughly 90 minutes idle, which is why every stage keeps a
manifest and skips finished work. Re-running a cell after a disconnect continues where it
stopped. At 222 pages the whole run is small enough that a laptop works too — Colab is for
keeping the PDF, the cache and the credentials in one place the whole team can reach.

## Tests

```bash
cd factory && pytest
```

The chunker is pure functions over plain data, so its tests run the whole thing over a
fake book in milliseconds. They are Gate D, written down: formulas and tables never split,
prose splits at sentence boundaries, page numbers survive page breaks, and a sentence cut
in half by a page break is rejoined.

## The other scripts (M5)

| Script | Does |
|---|---|
| `make_templates.py` | Numerical templates, verified by generating 20 instances each |
| `make_from_facts.py` | `facts` rows -> MCQs and blanks |
| `make_from_sentences.py` | Bold key-term sentences -> fill in the blank |
| `draft_with_gemini.py` | RAG pages -> conceptual MCQs -> blind second call to double-check |
| `export_sheet.py` | Candidates -> CSV for review |
| `import_reviewed.py` | Approved rows -> `items` |

`factory/out/` and `factory/work/` are gitignored: candidate CSVs, page caches and
transcripts do not belong in the repo.
