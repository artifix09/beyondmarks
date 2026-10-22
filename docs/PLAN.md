# Build plan

Re-baselined 22 Oct 2026. The schedule in `CLAUDE.md` §11 gave 21–23 Oct for the first
end-to-end topic; this replaces those dates. Scope is unchanged — only the dates moved.

Demo: **5 Nov 2026**.

## Modules

| # | Module | Depends on | Runs on | Lane |
|---|---|---|---|---|
| M0 | Repo scaffold | — | local | A |
| M1 | Database — Supabase, `db/schema.sql`, seed curriculum | M0 | Supabase | A |
| M2 | Auth — Google sign-in, JWT verification | M1 | local | A |
| M3 | Curriculum API — books, chapters, topics | M1 | local | A |
| M4 | Book ingestion — PDF → transcription → chunks → embeddings | M1 | Colab | C |
| M5 | Item factory — templates, facts, sentences, drafts, review, import | M1, M4 | Colab + Sheets | C |
| M6 | Quiz service — sessions, serving, instancing, grading, attempts | M1, M3 | local | B |
| M7 | Adaptive engine — `rules_v1` | M6 | local | B |
| M8 | RAG retrieval — hybrid vector + full text | M4 | local | B |
| M9 | Gemini wrapper | M1 | local | A |
| M10 | Explanations — grounded, streamed | M8, M9 | local | A |
| M11 | Chat — whole book, citations | M8, M9 | local | A |
| M12 | Frontend — Login, Topics, Quiz, Results, Progress, Chat, ShareCard | M2, M6 | local + Vercel | B |
| M13 | Share card + referral | M7, M12 | local | B |
| M14 | Tests — engine, grading, templates, retrieval | M6, M7 | local | B |
| M15 | Deployment — Render + Vercel | M12 | Render + Vercel | A |
| M16 | Bloom classifier — offline research | M5 | Kaggle | C |

## Work order

Critical path: **M0 → M1 → M2 → M6 → M7 → M12 → M15**.

Two things start immediately and sit off that path:

- **M4 ingestion.** Transcribing a textbook page by page through Gemini is hours of wall
  clock. M5, M8, M10 and M11 all queue behind it. Start it the moment M1 exists.
- **M5 review.** Human review of candidate questions is calendar time, not coding time.
  Candidates must reach the review sheet by 27 Oct.

Rules that keep the order honest:

- Build the vertical slice before widening. One topic end to end beats six half-built modules.
- Hand-seed about 8 items for one topic on day two, so M6, M7 and M12 can be built before the
  factory delivers anything.
- M7 is pure Python over plain data. It gets tests from its first commit — it is the part the
  committee will interrogate.
- M16 never blocks anything.
- M13 and the Roman Urdu toggle are the first cuts if 2 Nov arrives without a running pilot.

## Phases

| Dates | Phase | Done when | Modules |
|---|---|---|---|
| 22 Oct | P0 Foundations | All three run API + frontend locally against Supabase with the schema applied; ingestion running on Colab | M0 M1 M2 M4 |
| 23–25 Oct | P1 Vertical slice | Login → 8-question pre-test → graded → Bloom bars → streamed explanation with pages. Ugly is fine | M3 M6 M9 M10 M12 |
| 26–29 Oct | P2 Factory + adaptivity | 2 chapters reviewed and in the bank; sessions 2–5 differ per student with visible reasons; post-test matched; engine tests green | M5 M7 M14 |
| 30 Oct–1 Nov | P3 Product feel | Chat with citations, progress page, result card, Roman Urdu, deployed on a real URL that works on a phone | M8 M11 M13 M15 |
| 2–3 Nov | P4 Pilot | 10–20 real students have taken a pre-test; before/after numbers collected | — |
| 4 Nov | P5 Freeze | Pilot bugs fixed, demo accounts X and Y seeded, backup video recorded | — |
| 5 Nov | P6 Demo | Two students, same pre-test, visibly different session 2, real numbers | — |

M16 slots into 30 Oct–2 Nov, after P2 produces labelled items.

## Lanes

| Lane | Owns | Modules |
|---|---|---|
| A — Platform | Database, auth, Gemini wrapper, streaming, deployment | M0 M1 M2 M3 M9 M10 M11 M15 |
| B — Product | Quiz flow, engine, frontend, tests | M6 M7 M8 M12 M13 M14 |
| C — Content & research | Ingestion, question factory, review, Bloom classifier | M4 M5 M16 |

Question review is shared: both content reviewers cross-check each other.

## Decide before the work needs it

| Needed by | Question | Blocks |
|---|---|---|
| today | Exact Gemini model names on the paid key — chat model and a 768-dim embedding model | M4 M9 |
| today | Is the FBISE Grade 9 Physics PDF in the shared Drive folder? | M4 |
| 25 Oct | Which 2 chapters go adaptive first? | M5 |
| 29 Oct | Pilot group: a school, an academy, or individual students? | P4 |
| 4 Nov | Does the department need the classifier visible in the app, or is an offline result enough? | M16 |

## Environment

See `CONTRIBUTING.md` for local setup, `factory/README.md` for Colab, and
`research/bloom_classifier/README.md` for Kaggle.
