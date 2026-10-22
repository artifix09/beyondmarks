# Content factory

Offline scripts. Nothing here runs inside the API, and nothing in the API
imports from here.

| Script | Does |
|---|---|
| `ingest_book.py` | PDF -> page images -> Gemini transcription -> chunks -> embeddings -> `textbook_chunks` |
| `make_templates.py` | Numerical templates, verified by generating 20 instances each |
| `make_from_facts.py` | `facts` rows -> MCQs and blanks |
| `make_from_sentences.py` | Bold key-term sentences -> fill in the blank |
| `draft_with_gemini.py` | RAG pages -> conceptual MCQs -> blind second call to double-check |
| `export_sheet.py` | Candidates -> CSV for review |
| `import_reviewed.py` | Approved rows -> `items` |

## Running in Colab

Keep the logic here, not in the notebook. The notebook clones this repo,
installs `factory/requirements.txt`, and calls a script. That way the pipeline
survives the runtime being recycled and lives somewhere the team can review it.

Secrets go in the Colab secrets panel, never in a cell:
`GEMINI_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`.

Ingestion checkpoints per page to Drive and skips pages already done, because
a free Colab runtime disconnects after about 90 minutes idle and a whole
textbook does not transcribe in one sitting.

`factory/out/` is gitignored: candidate CSVs and page caches do not belong in
the repo.
