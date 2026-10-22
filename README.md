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
| AI | Gemini API |

## Repo layout

```
context/    project context, data model (schema.sql) and design diagrams
```

Start with `context/CLAUDE.md` — it is the complete, current picture of the project and wins over
any older document.

## Getting started

Clone, then create your own `.env` from `.env.example` (never commit `.env`).

```bash
git clone https://github.com/<owner>/beyondmarks.git
cd beyondmarks
```

## Working on this repo

- `main` is protected by convention: no direct pushes. Branch, then open a pull request.
- Branch names: `feat/<short-name>`, `fix/<short-name>`, `chore/<short-name>`.
- One reviewer approves before merge.

## Team

Hamna Fajar · Shawaiz Daud — BS Artificial Intelligence (2023–2027), Shifa Tameer-e-Millat
University, Islamabad. Supervisors: Sir Talha Mahmood, Sir Naveed Ahmed.
