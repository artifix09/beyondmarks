# Contributing

Three of us, one `main`, fourteen days. These rules exist so that nobody loses an
afternoon to a merge.

## Branches and pull requests

- Never commit to `main` directly. Branch, push, open a pull request, one approval, merge.
- Branch names: `feat/<short-name>`, `fix/<short-name>`, `chore/<short-name>`.
- Pull `main` before creating a branch, and again if your PR has been open overnight.
- Merged branches are deleted automatically.

## Local setup, once

```bash
python --version     # 3.11 or newer
node --version       # 20 LTS or newer
```

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # paste the real values in
uvicorn app.main:app --reload
```

`GET /health` reports which environment keys are still empty — check it first when
something does not work.

```bash
pytest                             # from backend/
```

### Frontend

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev                        # http://localhost:5173
```

The scaffold page shows whether it can reach the API and whether the API has its keys.

## Secrets

- `.env` and `.env.local` are gitignored. Keep it that way.
- Real values live in the shared team vault. Not in the repo, not in the group chat, not
  in a notebook cell, not in a Colab or Kaggle output.
- Only `VITE_`-prefixed values reach the browser, and only the Supabase **anon** key
  belongs there. The service-role key never leaves the backend.
- If a key is ever pasted somewhere public, rotate it rather than deleting the message.

## Database

`db/schema.sql` is the baseline and is not edited again. Every change after it is a
numbered file in `supabase/migrations/`, and the SQL gets shown to the team before it is
run against the shared project.

## Code

- Gemini is imported in `backend/app/ai/gemini.py` and nowhere else. That single import
  is what makes the timeout, the retry, the cache, the cost log and the daily budget true.
- Grading, question choice and Bloom levels are plain Python. Gemini explains; it never
  decides.
- The engine (`app/engine/`) takes plain data and returns plain data: no database, no
  network, no framework. That is what lets its tests run a synthetic student through five
  sessions in milliseconds.
- Nothing hard-codes Physics, Grade 9 or FBISE. All of it is data.
- Template answers are evaluated with a safe parser, never Python `eval`.

## What not to commit

`.env` files, API keys, the textbook PDF, model checkpoints, `factory/out/`,
`node_modules/`, notebook outputs.
