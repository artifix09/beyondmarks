# BeyondMarks

Pakistani marksheets give one percentage. **BeyondMarks** tells a student *where* they are weak
(remembering, understanding, applying, analysing), explains their own mistakes from their own
textbook, and gives them the next questions that target that weakness.

Scope for the MVP: FBISE, Grade 9, Physics. Nothing in the code hard-codes a board, grade or
subject — all of that is data.

## Stack

| Part | Choice |
|---|---|
| Frontend | React + Vite + TypeScript + Tailwind (Vercel) |
| Backend | FastAPI, Python 3.11+ (Render) |
| Database | Supabase Postgres + pgvector |
| Auth | Supabase Auth, Google sign-in only |
| AI | Gemini API, through one wrapper |
| Research | Kaggle notebooks, offline |

## Repo layout

```
CLAUDE.md                  full project context — read this first, it wins over older docs
CONTRIBUTING.md            branch rules, local setup, secrets
db/schema.sql              data model v3, the baseline
supabase/migrations/       numbered changes after the baseline
backend/                   FastAPI service
  app/engine/              the adaptive engine — plain, tested Python
  app/ai/gemini.py         the only module that imports the Gemini SDK
  tests/
frontend/src/              React pages
factory/                   offline content scripts (run on Colab)
research/bloom_classifier/ offline Bloom research (Kaggle)
docs/PLAN.md               modules, work order, phases, lanes
docs/diagrams/             architecture and system design
```

## Getting started

```bash
# backend
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && cp .env.example .env
uvicorn app.main:app --reload

# frontend
cd frontend && npm install && cp .env.example .env.local && npm run dev
```

Open http://localhost:5173 — it reports whether the API is reachable and which environment
keys are still missing. Full setup, including Colab and Kaggle, is in
[CONTRIBUTING.md](CONTRIBUTING.md) and [docs/PLAN.md](docs/PLAN.md).

## Working on this repo

Branch, then pull request, one approval before merge. Never commit to `main` directly, and
never commit a key. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Team

Hamna Fajar · Shawaiz Daud — BS Artificial Intelligence (2023–2027), Shifa Tameer-e-Millat
University, Islamabad. Supervisors: Sir Talha Mahmood, Sir Naveed Ahmed.
