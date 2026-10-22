# BeyondMarks — full project context for Claude Code

Read this first. It is the complete, current picture of the project: what we are building, why,
every decision made so far (and what we dropped), the stack, the data model, and the build plan.
If something here conflicts with older documents (scope doc, incubation proposal, earlier
design docs), **this file wins**. Last updated: 21 Oct 2026.

---

## 1. Who we are and what we are building

- Team: **Hamna Fajar** and **Shawaiz Daud**, BS Artificial Intelligence (2023–2027), Shifa
  Tameer-e-Millat University (STMU), Islamabad. Supervisors: Sir Talha Mahmood, Sir Naveed Ahmed.
- It is our FYP **and** an incubation-centre startup. We want a real, market-level product,
  starting with an MVP. We are students: little money, no GPU, two developers.
- Product name: **BeyondMarks**. ("EduTrack" was an older name for the same product. Ignore it.)
- Team chats in English + Roman Urdu. Code, comments and UI text are in English; the student
  can switch explanations to Roman Urdu.

**The idea in one line:** Pakistani marksheets give one percentage. BeyondMarks tells a student
*where* they are weak (remembering, understanding, applying, analysing), explains their own
mistakes from their own textbook, and gives them the next questions that target that weakness.

**The "magic moment" we build towards first:**
A student does 8 Physics questions and the app says something like: *"You remember the formulas,
but you get stuck when the situation changes. Here is exactly where you went wrong (textbook
p. 34)."* Then the next questions go straight at that weakness. If this moment works, we have a
product. Everything else is secondary.

## 2. Scope right now

- **Board / grade / subject:** FBISE, Grade 9, **Physics** (we switched from Biology).
- **Book:** the FBISE Grade 9 Physics textbook (PDF supplied by the team). We also have notes,
  past papers and board learning outcomes (SLOs) to use as references.
- **MVP coverage:**
  - The **whole book** is ingested into RAG, so chat works across the entire book.
  - The **adaptive question bank** covers **2 chapters** (about 6 topics) for the demo, then we add
    roughly one chapter per week. Which 2 chapters: not decided yet (see section 16).
- **Platform:** one responsive **web app** (phone-first). No native mobile app for now.
- **Demo / incubation presentation: 5 Nov 2026.**
- **Later:** more chapters → other Grade 9 subjects → Grade 10–12 → other boards. The code must
  never hard-code Physics, Grade 9 or FBISE; all of that is data.

## 3. The student journey (final)

1. Sign in with **Google** (no passwords).
2. Pick a topic (the student chooses the topic; the engine chooses the questions).
3. **Pre-test:** 8 questions, 2 per Bloom level, mixed formats. Graded instantly by code.
4. **Results:** a bar per Bloom level, the correct answer and a one-line reason for every question.
5. **Explanation:** Gemini explains *this student's* mistakes, grounded in textbook pages (RAG),
   with page numbers, streamed like ChatGPT. Optional Roman Urdu.
6. **Chat unlocks** for that topic (RAG over the book, page citations). Locked before the pre-test
   so the pre-test measures what the student knew on their own.
7. **Sessions 2–5:** 6 questions each, chosen to target the weakest level. Template questions give
   fresh numbers every time.
8. **Post-test:** 8 questions matched to the pre-test → before/after "learning gain".
9. **Result card:** an image ("My Physics profile") the student can share on WhatsApp. Friends who
   join through it are tracked with a referral code.

Optional, cheap extras (build only if time allows): a confidence/prediction tap before the quiz,
"Fix my mistake" (one similar fresh question right after a wrong answer), "3 things to revise
before your paper" list, and a teacher class link with a CSV summary.

## 4. Where questions come from (the question factory)

We do not hand-write hundreds of questions. Four sources, all ending in one reviewed item bank:

| Source | Produces | How it stays correct | Typical Bloom level |
|---|---|---|---|
| **Number templates** | Numerical questions with fresh values every time | Code computes the answer from a formula | Apply, some Analyze |
| **Facts table** | MCQs and blanks: units, symbols, formulas, scalar/vector, definitions | Rows reviewed once; wrong options come from other rows of the same table | Remember, Understand |
| **Book sentences** | Fill-in-the-blank from definition sentences (bold key terms) | It is the book's own sentence | Remember |
| **Gemini drafts** | Conceptual MCQs ("why does a passenger jerk forward…") | Drafted from RAG pages; a **second blind Gemini call** answers each one, and disagreements are flagged; then human review | Understand, Analyze |

- Distractors for Gemini MCQs should be based on **common student misconceptions**.
- Approved Gemini MCQs can be reworded into 2–3 variants (same answer) for variety.
- **Review workflow:** scripts write candidates to a **Google Sheet / CSV**; Hamna and Shawaiz
  cross-review (OK / fix / reject); an import script loads approved rows into `items`.
  No admin panel for now. There is no subject teacher; we review ourselves using the book,
  notes, past papers and SLOs. Every item cites its textbook page.
- **Short-answer questions** (LLM rubric grading) are postponed until after the demo.
- Rough bank size per topic: 8 pre-test + 8 post-test (matched via `pair_id`) + 20–24 adaptive.
  Templates count as one item but generate endless variants.

### Template format (stored in `items.template`, numerical only)

```json
{
  "params": {"d": {"min": 50, "max": 500, "step": 10}, "t": {"min": 5, "max": 60, "step": 1}},
  "answer_expr": "d / t",
  "unit": "m/s",
  "round": 2,
  "abs_tol": 0.05,
  "rel_tol": 0.01,
  "constraints": ["d / t < 100"]
}
```

Stem: `"A car covers {d} m in {t} s. Find its average speed."`. When served, the backend draws
values that satisfy the constraints, renders the stem, computes the answer, and stores all of it
in `session_items.instance`. Grading uses that stored instance. Evaluate `answer_expr` safely
(e.g. a small whitelist parser or `numexpr`/SymPy), **never Python `eval`**.

## 5. RAG (in the MVP from day one)

Used for: (1) chat over the whole book, (2) grounding explanations with page numbers,
(3) giving Gemini the right pages when drafting conceptual questions.

Ingestion (offline script, run once per book):
1. Render each PDF page to an image and let **Gemini transcribe it** to Markdown with formulas as
   LaTeX. Normal PDF text extraction breaks Physics formulas. Spot-check pages with heavy maths.
2. **Chunk by heading** (~200–400 words), keeping `book_id`, `chapter_id`, `topic_id`,
   `page_start/page_end`.
3. **Embed** with a Gemini embedding model at 768 dimensions (must match
   `textbook_chunks.embedding vector(768)`); store `embedding_model` on each row.
4. Store in Supabase `textbook_chunks` (pgvector HNSW index + generated `tsv` full-text column).

Retrieval: filter first (book → chapter → topic when known), then **hybrid** search = vector
similarity + Postgres full-text, merged by rank (e.g. reciprocal rank fusion). Return top ~4
chunks with page numbers. If the best match is weak, the bot says it is not sure and points to the
chapter instead of guessing.

## 6. The adaptive engine (plain Python, no AI)

Keep it simple, explainable and testable. This is the part we own and can explain to the
committee.

- **State** per student × topic × Bloom level in `skill_states`: decayed evidence `a`, `b`
  (start at 1), `n_items`, difficulty `tier` (1–3), streaks, `mastered_at`.
- **Update per answer** with score s ∈ [0, 1]: `a += s`, `b += 1 − s`, `n_items += 1`.
  "I don't know" = score 0 with `attempts.dont_know = true` (so we know it was not a guess).
  In the "challenge zone" (status strong and tier 3) a wrong answer adds 1.5 to `b`.
- **Decay at session start:** `a = 1 + 0.9·(a − 1)`, same for `b`.
- **mastery = a / (a + b).** Show a level only after **3+ answered items**:
  weak < 0.5 ≤ developing < 0.8 ≤ strong; **mastered** = 2 correct in a row at tier 3 and
  mastery ≥ 0.8. Below 3 items, show "Not enough evidence yet". Levels can go down too.
- **Staircase per level:** 2 correct in a row → tier + 1; 2 wrong in a row → tier − 1.
- **Next session (6 items):** 1 warm-up (strongest level, easy) + 2 from the weakest level +
  1 each from the next two weakest + 1 stretch (one tier up on a developing level). Every 2nd
  session, swap one for a retention check on a mastered level. No repeats from the student's
  last 3 sessions on that topic (templates are exempt because their values change). Prefer items
  whose concept the student got wrong in 2+ sessions.
- **Stuck** (mastery < 0.5 after 3 sessions on a level): drop to tier 1, show the textbook
  section, offer a chat starter about that concept.
- **Log everything:** each planned item stores `reason` (e.g. `weak_level`), `reason_bloom`,
  `tier`, `predicted_p` (a rough P(correct): mastery ± 0.15 by difficulty). Each session stores
  `policy_version` (`rules-v1.0`). This lets us test smarter models (Elo / IRT, Duolingo-style)
  offline later without rewriting anything.
- `skill_states` must always be **recomputable from `attempts`**.

Grading (code): MCQ exact key; fill-blank normalised text + accepted synonyms, second try = 0.5;
numerical within `abs_tol` or `rel_tol`, wrong unit = 0.5.

## 7. How we use Gemini

- **Model:** a Gemini **Flash-Lite**-class model for chat, explanations and drafting; a Gemini
  embedding model for RAG. Check the current model names in Google AI Studio (2.5 Flash-Lite
  may be limited to existing projects; 3.1 Flash-Lite was current in Oct 2026). Keep the model
  name in config so it can be swapped.
- **Use the paid tier/key.** Free-tier content may be used by Google to improve its products, and
  our users are minors.
- **One wrapper module** for every Gemini call (`backend/app/ai/gemini.py`): prompts, timeout
  (~20 s), retry once, cache, and a row in `llm_calls` (model, prompt id/version, tokens, cost,
  latency, ok). Nothing else imports the Gemini SDK.
- **Gemini explains; it never decides.** Grading, question choice and levels are code. When it
  explains a mistake, it always receives the question, the student's answer, **the correct answer
  and worked solution**, and the textbook pages. After generation, check that any final number it
  states matches the key.
- **Fallback** when Gemini fails or times out: show the item's worked solution + the textbook
  page. The quiz itself never depends on Gemini.
- **Explanation templates by weakest level:** Remember → key terms + mnemonic; Understand → "why"
  chain + analogy; Apply → worked example in a new situation; Analyze → compare/contrast or
  cause→effect. Style: simple + examples (default), step-by-step, or Roman Urdu mix.
- **Never put personal data in prompts** (no names, emails, ids).
- Cache explanations by (prompt version, item, wrong answer pattern, weak level, style).
- Chat: limit to ~30 messages per student per day; politely refuse off-topic requests; for
  questions that match bank items, give hints and steps instead of just the final answer.

## 8. Stack (cheap on purpose: roughly $10–20 a month)

| Part | Choice |
|---|---|
| Frontend | React + Vite + TypeScript + Tailwind, hosted on **Vercel** (free) |
| Backend | **FastAPI** (Python 3.11+), one service, hosted on **Render** (~$7/month always-on instance) |
| Database | **Supabase** Postgres + **pgvector** + full-text search |
| Auth | Supabase Auth, **Google sign-in only**; the API verifies the Supabase JWT |
| Files | Supabase Storage (book PDF, share-card images) |
| AI | Gemini API (paid key) via one wrapper |
| Content tools | Python scripts on a laptop / Colab + Google Sheets for review |
| BERT research | Kaggle notebooks (free GPU), offline only |

- **No background worker or job queue for now.** Explanations and chat stream directly from
  the API (Server-Sent Events). Add a worker only if something becomes too slow.
- The browser talks to Supabase **only for Google sign-in**. All data goes through FastAPI, which
  uses the service-role key. RLS is enabled on every table with no client policies, so the
  browser can never read answer keys directly.
- No GPU needed anywhere.

## 9. Data model (`db/schema.sql`, v3, 29 tables, validated on Postgres 16)

Curriculum is data, so new books/grades need no code changes.

| Area | Tables / views |
|---|---|
| Users | `users` (role: student / editor / admin, style, consent, `referral_code`, `referred_by`), `enrollments` (student × book) |
| Curriculum | `books` (board, grade, subject, edition, language), `chapters` (`in_adaptive`), `topics`, `concepts`, `concept_prereqs`, `learning_outcomes`, `topic_outcomes` |
| RAG | `textbook_chunks` (book/chapter/topic, pages, `embedding vector(768)`, `embedding_model`, generated `tsv`) |
| Question factory | `facts` (quantity, symbol, SI unit, scalar/vector, formula, definition) |
| Item bank | `items` (Bloom, difficulty 1–3, format, pool pretest/posttest/adaptive, `pair_id`, `source`, `kind` fixed/template, `template`, answer, feedback, `worked_solution`, `source_pages`, `double_check`, reviewers, version/`supersedes_id`, `classifier_*` for BERT, stats), `item_concepts`, `item_outcomes`, `item_flags` |
| Engine | `engine_policies` (seeded with `rules-v1.0`), `sessions` (kind, `session_no` 1 = pre-test, 2–5 adaptive, 6 = post-test, `policy_version`), `session_items` (reason, tier, `predicted_p`, `instance` for templates), `attempts` (append-only, `idempotency_key`, `dont_know`), `skill_states`, `concept_states` (future), `self_reports` |
| AI | `llm_calls`, `explanations`, `note_cache`, `chat_threads`, `chat_messages`, `eval_runs` |
| Analytics | `events` (e.g. `pretest_started`, `card_shared`) |
| Views | `v_skill_summary` (mastery, status, confidence label), `v_concept_errors`, `v_prediction_log`, `v_daily_ai_cost` |

Rules of thumb: items are **immutable once live** (edit = new version with `supersedes_id`, so old
attempts keep the exact text); attempts are never edited; later schema changes go into
`supabase/migrations/` as numbered SQL files.

## 10. Suggested repo layout

```
beyondmarks/
  CLAUDE.md
  db/schema.sql                    baseline (v3)
  supabase/migrations/             numbered changes after the baseline
  backend/
    app/
      main.py  config.py  db.py  auth.py
      curriculum/                  books, chapters, topics (read APIs)
      quiz/                        sessions, picker (engine), grading, templates, attempts
      engine/rules_v1.py           update / levels / plan_session / predicted_p
      rag/                         retrieve (filter + vector + keyword)
      ai/gemini.py                 the only Gemini wrapper
      ai/prompts/                  explain_*.md, chat.md, draft_mcq.md, double_check.md, transcribe.md
      tutor/                       explanations + chat (SSE)
      share/                       result card image
    tests/                         unit + engine tests (synthetic students X and Y)
  frontend/src/                    pages: Login, Topics, Quiz, Results, Chat, Progress, ShareCard
  factory/                         offline scripts
    ingest_book.py                 PDF → page images → Gemini transcription → chunks → embeddings
    make_templates.py              numerical templates (+ verify by generating 20 instances each)
    make_from_facts.py             facts table → MCQs / blanks
    make_from_sentences.py         bold key-term sentences → blanks
    draft_with_gemini.py           RAG pages → conceptual MCQs → blind double-check
    export_sheet.py / import_reviewed.py
  research/bloom_classifier/       Kaggle notebooks (SVM baseline, BERT fine-tune)
  docs/diagrams/                   beyondmarks-architecture.*, beyondmarks-system-design.*
```

Organise code however works best as long as these hold: Gemini only through `ai/gemini.py`;
engine and grading are plain, unit-tested Python; nothing hard-codes a book or chapter.

## 11. Build plan to the 5 Nov demo

| Dates | Goal |
|---|---|
| 21–23 Oct | **One topic end-to-end, even if ugly:** Google login → 8-question pre-test → grading → Bloom bars → streamed Gemini explanation. Supabase set up with `schema.sql`. Start `ingest_book.py` and get the whole book into pgvector. |
| 24–27 Oct | **Question factory + adaptivity:** templates, facts table, book sentences, Gemini drafts + double-check → Sheet → import, for 2 chapters. Sessions 2–5 picker, post-test. Engine tests with synthetic students. |
| 28 Oct – 1 Nov | **Make it feel like a product:** RAG chat with page citations, proper UI, progress page, result card + WhatsApp share, Roman Urdu toggle. |
| 2–3 Nov | **Real students:** 10–20 students (juniors, relatives, a nearby academy) use it. Collect data and feedback. |
| 4 Nov | Fix what broke, seed demo accounts, record a backup demo video. |
| 5 Nov | Demo with real usage numbers. |

Demo script: two prepared students, X (weak at Apply) and Y (weak at Remember), take the same
pre-test and get **different session 2 questions with visible reasons**; show a grounded
explanation with page refs, chat, the result card, and the real pilot numbers.

## 12. Testing that matters

- Engine unit tests: synthetic X vs Y get different session-2 lists; levels never shown with
  fewer than 3 items; staircase and mastery rules; recompute-from-attempts equals stored state.
- Template tests: generate many instances per template; answers finite, constraints respected,
  units correct.
- Grading tests for each format, including tolerance, units and fill-blank synonyms.
- Gemini down (mock errors/timeouts): the quiz still completes and the fallback appears.
- Student A cannot read Student B's data; answer keys never appear in API responses before
  submission.
- A small retrieval check: ~50 questions with the expected page; aim for the right chunk in the
  top 3 most of the time.

## 13. Decisions log (what we chose and why)

| Decision | Why |
|---|---|
| Physics instead of Biology | Team choice; Physics also suits code-generated numericals |
| Web app, not Flutter | One codebase, works on phones, no app-store delay |
| Test first, then teach (pre-test before chat) | Otherwise the baseline is contaminated, and we lose the before/after number |
| Rule-based engine, not ML/RL | No data yet; rules are explainable and testable. Smarter models later, tested on logged data |
| Gemini explains, code decides | Accuracy, cost and testability |
| RAG in the MVP | Needed for whole-book chat, page citations and grounded question drafting anyway |
| Gemini page transcription for ingestion | Normal PDF extraction breaks formulas |
| Four question sources + Sheet review | Few hours of review instead of hundreds; no teacher available |
| No worker/job queue, stream responses instead | Simpler, faster to build, feels fast |
| Google sign-in only | Students hate passwords; less code |
| WhatsApp result card + referral | Free growth for a student product; good pitch slide |
| Roman Urdu option | Real local differentiator, costs one prompt line |
| Keep BERT, but as offline side research | Literature accuracy (~59% once higher levels are included) is too low to gate the bank; it suggests Bloom labels during review and stays in the FYP |
| Paid Gemini key | Minors' data must not go to the free tier |

## 14. What we deliberately are NOT building now

Native mobile app, student document upload, Q-learning/RL hints, mood/sleep/"psychological"
tracking or long surveys, N-back/Stroop cognitive games, a content admin panel, a background
worker, microservices, a separate vector database, teacher/parent portals (beyond an optional
CSV), payments, multi-board support. Don't add these unless the team asks.

## 15. Market context (why the product looks like this)

- Competitors: Parhai Buddy (Knowledge Platform: diagnostic + adaptive pathway, Grades 6–10),
  Khan Academy Pakistan + Khanmigo (MoU for Islamabad government schools), Maqsad (photo-a-question
  → video), Taleemabad, Edkasa, free MCQ test sites (ilmkidunya), and free AI tutors (ChatGPT
  Study Mode, Gemini Guided Learning).
- What we copy from the leaders: predict-then-serve and logging (Duolingo), mastery levels that go
  up and down (Khan Academy, IXL), "why this question" shown to the student (CENTURY), an "I don't
  know" option (IXL, CENTURY), and giving the LLM the correct answer when it explains (Duolingo).
- Our edge: Bloom-level diagnosis per topic **on the student's own FBISE book**, explanations
  with **page references**, Roman Urdu, and a free core. The chatbot alone is not the edge.
- Likely first buyers: tuition academies and private schools (a teacher brings a whole class);
  students use it free.

## 16. Open questions (ask the team if a task depends on them)

- Which 2 Physics chapters go adaptive first?
- Exact Gemini model names and the embedding model available on our key.
- Does the department need the BERT classifier shown in the live app, or is an offline result enough?
- First pilot group: a school, an academy, or individual students?
- Textbook usage permission for public launch (fine for a closed pilot; needed before going public).

## 17. Working with the team (how to behave)

- Be a practical teammate, not a rule-checker. Prefer the simplest thing that works for the demo,
  and say so when something is over-engineered.
- Ship vertical slices: get one topic working end-to-end before widening.
- Keep costs near zero; flag anything that would add a paid service.
- Explain decisions briefly in plain English (Roman Urdu is fine if the team writes in it).
- Before changing the shared database, show the migration SQL first.
- Write tests for engine, grading and templates; keep everything else lightweight.

## 18. Commands (update as the repo grows)

```bash
# backend
cd backend && uvicorn app.main:app --reload
cd backend && pytest -q
# frontend
cd frontend && npm run dev
# content factory (examples)
python factory/ingest_book.py --book-id <uuid> --pdf path/to/physics9.pdf
python factory/make_templates.py --chapter 2 --out factory/out/templates.csv
```

Environment variables (backend `.env`): `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`,
`SUPABASE_JWT_SECRET`, `GEMINI_API_KEY`, `GEMINI_MODEL`, `GEMINI_EMBED_MODEL`,
`DAILY_AI_BUDGET_USD`. Frontend: `VITE_API_URL`, `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`.
Never commit keys.
