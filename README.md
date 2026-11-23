# Contract Review Assistant

A signed-in user uploads a contract (PDF, DOCX or TXT) and the app checks it
against a fixed 8-item checklist — parties, start date and term, payment
terms, termination, limitation of liability, confidentiality, governing law,
auto-renewal. For each item it says whether the contract covers it, quotes
the clause word for word with its page/section, and links the quote back to
the full clause in the contract text. Findings come only from the contract:
anything not covered is reported as not found, never guessed. Follow-up
questions can be asked in a chat, under the same rules, with answers
streamed as they are generated.

Built for the IntelliBooks second-round take-home task (issued 23 Nov 2026).

## Quick start

### With Docker Compose (recommended)

```bash
cp .env.example .env        # fill in your keys (see "Keys" below)
docker compose up --build
```

- Frontend: http://localhost:5173
- Backend API + docs: http://localhost:8000/docs
- Postgres 16 + pgvector runs in the `db` container; no local setup needed.

### Local dev (no Docker)

```bash
# Backend
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp ../.env.example ../.env   # fill in your keys
# Without a local Postgres, use SQLite for dev (tests do this too):
DATABASE_URL="sqlite:///./contract_review.db" ../.venv/bin/python -m uvicorn app.main:app --reload --port 8000

# Frontend (another terminal)
cd frontend
npm install
cp .env.example .env.local   # VITE_CLERK_PUBLISHABLE_KEY + VITE_API_URL
npm run dev                  # http://localhost:5173, proxies /api to :8000
```

## Keys — where each one goes

| Key | Where to create it | Where it goes |
|---|---|---|
| `CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY` | [Clerk dashboard](https://dashboard.clerk.com) → create an application → API Keys | Backend `.env`; publishable key also in `frontend/.env.local` as `VITE_CLERK_PUBLISHABLE_KEY` |
| `CLERK_JWKS_URL`, `CLERK_ISSUER` | Same Clerk API Keys page: JWKS URL is `https://<your-frontend-api-domain>/.well-known/jwks.json`; issuer is that same frontend API domain | Backend `.env` |
| `OPENROUTER_API_KEY` | [openrouter.ai/keys](https://openrouter.ai/keys) — free, no card | Backend `.env` |
| `GROQ_API_KEY` (optional backup) | [console.groq.com/keys](https://console.groq.com/keys) — free, no card | Backend `.env` |

Never commit a real `.env` — it is gitignored. `.env.example` carries
placeholders only. The backend reads keys at runtime; the frontend only
ever sees the Clerk *publishable* key (safe to expose) and never sees any
API key.

**Clerk setup in 2 minutes:** create an application in the Clerk dashboard
(any name), leave the defaults, copy the four values above. Sign-up/sign-in
screens are Clerk's hosted components rendered inline; sign-out is the
`UserButton` in the header.

**OpenRouter free tier:** the chat model is
`nvidia/nemotron-3-ultra-550b-a55b:free` and embeddings are
`nvidia/nemotron-3.5-embed-1b:free` (2048 dims). Free accounts get **50
free-model requests/day**; when that is exhausted the app falls back to
Groq instead of failing the review (see "Rate limits and the Groq backup").

## Stack — and why

| Layer | Choice | Why |
|---|---|---|
| Backend | FastAPI (Python) + SQLAlchemy 2.0 | Small, typed, async-ready; the API surface is ~6 endpoints |
| Database | PostgreSQL 16 + pgvector | The brief requires it; `vector(2048)` columns store embeddings and `<=>` does cosine similarity in SQL |
| Frontend | React 18 + Vite | Fast dev loop, tiny bundle (~177 kB); no UI framework, plain CSS, so the UI is easy to follow |
| Auth | Clerk (`@clerk/react`) | The brief requires it; the backend verifies Clerk session JWTs itself (RS256 against Clerk's JWKS) instead of trusting the frontend |
| AI chat | OpenRouter free models | No card, OpenAI-compatible API, JSON mode + SSE streaming |
| AI embeddings | OpenRouter `nemotron-3.5-embed-1b:free` | 2048-dim, free, batched (16/request) |
| Backup AI | Groq `qwen/qwen3.8-27b` | Same OpenAI-compatible API, generous free tier; only used when OpenRouter is rate-limited |
| Run it | Docker Compose | One command: db + backend + frontend, with healthchecks |

## Architecture

```
                    ┌────────────────────┐
                    │  React + Vite SPA  │  ClerkProvider, sign in/up,
                    │  (port 5173)        │  upload, review, chat, text
                    └──────┬───────┬─────┘
                           │ Bearer token (Clerk session JWT)
                           │ on every API call; never a user id
                           ▼
                    ┌────────────────────┐      ┌──────────────────┐
                    │  FastAPI backend   │─────▶│  Clerk JWKS      │
                    │  (port 8000)       │ RS256│  (cached 1h)     │
                    │                    │      └──────────────────┘
                    │  routers/          │
                    │   contracts.py     │ upload/list/delete
                    │   reviews.py       │ read review, retry
                    │   chat.py          │ ask + SSE stream
                    │   pipeline.py      │ background processing
                    │  review.py chat.py │ grounded prompts, quote checks
                    │  retrieval.py      │ hybrid keyword + vector search
                    └──────┬───────┬─────┘
                           │                 ┌──────────────────┐
                           ▼                 │  OpenRouter      │
                    ┌────────────────────┐   │  chat + embeddings│
                    │  Postgres +        │──▶│  (free models)   │
                    │  pgvector          │   └──────────────────┘
                    │  contracts, chunks │   ┌──────────────────┐
                    │  (vector 2048),    │──▶│  Groq (backup)   │
                    │  review_items,     │   │  chat only       │
                    │  chat_messages     │   └──────────────────┘
                    └────────────────────┘
```

Request flow for an upload: the file is stored and the contract is created
as `processing` immediately (a large file never blocks the upload request).
A background task then extracts the text, splits it into clause-sized
chunks, embeds them, and runs the review; the frontend polls every 3 s
until the status is `reviewed` or `failed`. A failed review can be retried
from the UI.

## How the review works

### Chunking — clauses, not fixed slices

Contracts are split on paragraph/section boundaries: a chunk is a paragraph
or a numbered section, never a blind 500-character slice, so a clause is
never cut in half. Headings become the chunk's `section`; PDF page breaks
are tracked (`[[PAGE n]]` markers), so every chunk knows its page. A
paragraph longer than 2000 characters is split on sentence boundaries.
`backend/app/chunking.py`, `parsing.py` (pypdf / python-docx / plain text,
20 MB limit, checked by extension and size).

### Retrieval — keyword first, vector second

For each checklist item the backend retrieves the 6 most relevant chunks
(`backend/app/retrieval.py`):

1. **Keyword overlap first.** Each item has a keyword list (e.g. term:
   `term, commencement, effective date, start date, duration, expires`).
   Contracts reuse the same legal vocabulary everywhere, so a literal
   mention is the strongest signal that a chunk is about that item.
2. **Vector similarity second.** Embeddings break ties and catch
   paraphrases. On Postgres this is pgvector cosine similarity (`<=>` in
   SQL); on SQLite (tests/dev) the same cosine is computed in Python.

Item questions are embedded once up front (one batch), not once per item.
Embeddings are sent in batches of 16. Retrieval is always scoped to the
signed-in user and the one contract.

### The grounded prompt

Each item is judged in its own call, with **only** the retrieved excerpts
in the prompt and a system prompt that forbids inventing anything:
status is `found` only when an excerpt clearly covers the item; the quote
must be copied word for word from the excerpts, with the excerpt's chunk
id; otherwise `not_found` with an empty quote and a one-line summary
saying so. Temperature is 0 and `response_format` is `json_object`, so the
answer parses as JSON. `backend/app/review.py`.

### How quotes are checked as real

Every quote the model returns is verified by the backend before it is
stored (`backend/app/quotes.py`): the quote and the contract text are
normalised the same way (Unicode NFKC, smart quotes/dashes unified,
lowercased, whitespace collapsed) and the quote must appear verbatim as a
substring of the contract. If it does not, the item becomes `unclear` and
the quote is flagged unverified — the app never shows an unverified quote
as a finding. A `not_found` verdict always has an empty quote. The same
check runs on the `Sources:` section of every chat answer.

### Follow-up chat

The question is answered from the same retrieved chunks, with the last few
chat turns for context. The model must end its answer with a `Sources:`
section (`- [chunk <id> | page <n>] "exact quote"`); the backend parses
and verifies each quote, stores the verified sources with the message, and
streams the answer token by token (SSE) so it appears as it is generated.
Review and chat history are stored per contract and survive a refresh.
`backend/app/chat.py`.

### Risk flags (bonus)

Derived from the verdicts (`backend/app/checklist.py`):

- No cap on liability → "needs attention: a party's exposure is uncapped."
- No termination clause → "needs attention: it may be unclear how to exit."
- Auto-renewal present → "check the notice window for stopping it."
- No governing law → "needs attention: disputes have no agreed forum."

### Rate limits and the Groq backup

- A 429 from a chat provider is **retried** (up to 4 attempts, 15 s / 30 s /
  60 s backoff, honouring `Retry-After`) before it is reported — free tiers
  recover within a minute. When a backup provider is configured, the
  primary fails fast (1 attempt) and the backup is the retry instead, so a
  review never burns minutes re-trying a quota that resets tomorrow.
- If OpenRouter's **daily** free quota (50 requests/day) is exhausted,
  retries cannot help, so the review falls back to Groq (`qwen/qwen3.8-27b`)
  for chat and to keyword retrieval for embeddings, and says so on the
  contract (`review_note`, shown as a notice in the UI). Groq has no
  embeddings API, so the embedding fallback is the same hash-vector
  stand-in the tests use — retrieval still works because keyword hits rank
  first. `backend/app/llm.py` (`FallbackLLM`), `backend/app/routers/pipeline.py`.
- If there is no key at all, the review fails with a clear message
  ("OPENROUTER_API_KEY is not set…") and the contract shows `failed` with a
  Retry button; uploads, lists and chat history still work.

## How each user's data is kept separate

- The frontend never sends a user id. On every request the backend
  verifies the Clerk session JWT (RS256 signature against Clerk's JWKS,
  issuer checked, cached for an hour) and takes the user id from the
  token's `sub` claim. `backend/app/auth.py`.
- Every query filters on that user id — contracts, chunks (including
  vector search), review items, chat messages (`backend/app/isolation.py`).
  A request for another user's contract id returns **404**, never 403, so
  it does not even confirm the contract exists.
- There are tests that prove this: user B gets 404 on user A's contract,
  review, chat and delete endpoints, including by direct API call with the
  id. `backend/tests/test_isolation.py`.

## API

| Method | Path | Notes |
|---|---|---|
| GET | `/api/health` | `{ok, ai_configured, auth_configured}` — no auth |
| POST | `/api/contracts` | Multipart upload (PDF/DOCX/TXT, ≤ 20 MB) → contract, `processing` |
| GET | `/api/contracts` | Own contracts: name, size, upload date, status |
| GET | `/api/contracts/{id}` | One contract (incl. `review_note`) |
| DELETE | `/api/contracts/{id}` | Deletes contract + chunks + review + chat |
| GET | `/api/contracts/{id}/review` | Checklist verdicts + risk flags |
| POST | `/api/contracts/{id}/review/retry` | Re-run a failed review (background) |
| GET | `/api/contracts/{id}/text` | Chunk list with page/section (jump target) |
| GET | `/api/contracts/{id}/chat` | Chat history |
| POST | `/api/contracts/{id}/chat` | Ask a question (SSE stream) |

Full interactive docs at `/docs` when the backend runs.

## Sample contracts and the eval script

`samples/` holds two contracts plus the expected checklist results:

- `sample-contract-complete.txt` — Master Services Agreement; all 8 items found.
- `sample-contract-missing-items.txt` — Consulting Agreement; 5 found, 3
  not found (limitation of liability, governing law, auto-renewal), so the
  demo can show honest "not found" verdicts.
- `expected-results.json` — per-item expected status + a phrase the quote must contain.
- `generate_pdfs.py` — builds the matching PDFs (same text, footer page numbers).

Run the eval:

```bash
# No key needed: rule-based stand-in measures the PIPELINE only
# (chunking, retrieval, quote verification, statuses).
python3 eval/eval.py

# With a live key: measures real review quality (uses the Groq backup
# automatically if OpenRouter is rate-limited).
OPENROUTER_API_KEY=... GROQ_API_KEY=... python3 eval/eval.py --live
```

It scores each checklist item (status + quote phrase + quote verification)
and one follow-up question per contract, and exits 0 only if everything
passes.

## Tests

```bash
cd backend && .venv/bin/python -m pytest tests -q
```

45 tests, no key and no network needed: parsing, chunking, quote
verification, Clerk-token verification (throwaway RSA key + local JWKS),
per-user isolation (404s for another user's ids), upload validation,
review pipeline (both sample contracts), chat grounding, and the Groq
fallback + 429 retry behaviour. Tests blank the API keys in the
environment — pydantic-settings reads `.env` when a variable is absent, so
merely unsetting them would leak a real key from `.env` into the suite
(`backend/tests/conftest.py`).

## Results

- **Tests: 45 passed, 0 failed** (SQLite, rule-based stand-in).
- **Eval, pipeline mode (no key): 18/18 = 100%.**
- **Eval, live mode (OpenRouter quota exhausted that day, so Groq backup +
  keyword retrieval): 18/18 = 100%.** All 16 checklist items correct on
  both contracts, both follow-up chats answered with verified quotes. A few
  Groq per-minute rate limits were hit mid-run and recovered by the retry
  backoff (15–30 s waits); total live-eval runtime ~3.5 min.
- **Frontend production build: passes** (`npm run build`, 177 kB JS).
- **HTTP smoke test (SQLite):** `/api/health` reports
  `ai_configured: true, auth_configured: false` (no Clerk keys yet);
  `/api/contracts` without a token → 401, with a bogus token → 401;
  `/docs` → 200.

## Known limitations — and what would improve with more time

- **Live Clerk is untested.** The Clerk keys are still empty: Clerk
  refuses account creation from this cloud network, so the account must be
  created once from a normal network, then the keys go in `.env`. The
  integration code (provider, sign-in/up, token on every call, JWKS
  verification) is written and unit-tested with locally built tokens, but
  no real sign-up/sign-in has run through it yet.
- **Live pgvector is untested.** No Docker in this environment, so the
  Postgres + pgvector path has not run end to end; tests and the eval use
  SQLite with a Python cosine fallback (the same `Vector(2048)` column
  degrades to JSON on SQLite). The `docker-compose.yml` path is the one to
  run before the demo.
- **Live OpenRouter review is untested at full quality.** On the test day
  the account's 50/day free quota was already exhausted, so the live eval
  ran on the Groq backup; OpenRouter's own review quality (and the
  `nemotron-3-ultra` JSON discipline) still needs one run after the quota
  resets (00:00 UTC). The pipeline is provider-agnostic, so this is a
  verification gap, not a code gap.
- **No contract-version comparison** (bonus) — comparing two versions of a
  contract and listing changed clauses is not built; the chunk table
  already has everything it needs (per-contract chunks with page/section),
  so it is a small addition: diff chunk texts between two contracts.
- **Contract text lives in the database**, not object storage. Fine for
  the 20 MB limit, but a real deployment would put files in S3-style
  storage and keep only text + metadata in Postgres.
- **No migrations** — tables are created with `create_all` on startup. A
  real deployment would use Alembic; adding a column today means deleting
  the dev SQLite file.
- **One embedding model, one chunking strategy.** A production version
  would A/B the chunk size and the retrieval mix (keyword vs vector
  weight) against the eval, and add a re-ranker.
- **Rate-limit retries block the worker** (`time.sleep` in the request
  path). Acceptable for a take-home; a production version would queue the
  review and poll, which the upload path already does.

## How AI tools were used

The app was built with an AI coding assistant (Muse) directed by the
candidate: the candidate set the architecture (FastAPI + React + Postgres +
pgvector + Clerk + OpenRouter, per the brief), the chunking/retrieval
design, and the grounding rules; the assistant wrote the code, tests and
docs. Every behaviour the README claims was verified by a test or by
running it: the test suite caught and fixed 6 real bugs during development
(wrong UUID handling, stopwords matching every chunk, keyword ranking,
quote excerpts swallowing prompt lines, two drafting errors in the sample
contracts), and the eval script exists precisely so the review quality can
be re-measured after any change. Nothing is claimed that was not run — the
"Results" and "Known limitations" sections above say exactly what was
tested and what was not.

## Repo layout

```
.
├── docker-compose.yml          # db (pgvector/pgvector:pg16) + backend + frontend
├── .env.example                # placeholders only — copy to .env
├── backend/
│   ├── requirements.txt
│   ├── Dockerfile
│   ├── app/
│   │   ├── main.py             # FastAPI app, /api/health, routers
│   │   ├── config.py           # settings from .env (no secrets hard-coded)
│   │   ├── db.py               # engine/session, pgvector-or-JSON embedding type
│   │   ├── models.py           # Contract, Chunk, ReviewItem, ChatMessage
│   │   ├── auth.py             # Clerk JWT verification (RS256 + JWKS)
│   │   ├── isolation.py        # user-scoped lookups (404, never 403)
│   │   ├── parsing.py          # PDF/DOCX/TXT extraction, page markers
│   │   ├── chunking.py         # clause-aware chunking
│   │   ├── quotes.py           # quote verification (normalised substring)
│   │   ├── checklist.py        # the 8 items, keywords, risk flags
│   │   ├── embeddings.py       # OpenRouter embeddings (batched) + hash stand-in
│   │   ├── llm.py              # OpenRouter + Groq clients, fallback, 429 retries
│   │   ├── http_client.py      # proxy-safe httpx wrapper (see note below)
│   │   ├── retrieval.py        # hybrid keyword + vector retrieval
│   │   ├── review.py           # per-item grounded review + quote checks
│   │   ├── chat.py             # grounded streaming chat + source verification
│   │   ├── schemas.py          # response models
│   │   └── routers/            # contracts, reviews, chat, pipeline
│   └── tests/                  # 45 tests, no key/network needed
├── frontend/
│   ├── src/App.jsx             # dashboard, upload, contract detail + tabs
│   ├── src/components/         # ReviewView, ChatPanel, ContractViewer
│   └── src/api.js              # Bearer token on every call
├── samples/                    # two contracts + expected results + PDF builder
└── eval/eval.py                # accuracy eval (pipeline mode or --live)
```

Note on `http_client.py`: httpx reads proxy settings from the environment
and crashes parsing `NO_PROXY` values that contain bracketed IPv6 literals
(`[::1]`), which this sandbox sets. The wrapper reads the proxy URL itself
and passes it explicitly with `trust_env=False`, so outbound calls work in
proxied sandboxes and directly elsewhere.
