# Demo video script — IntelliBooks contract review assistant (≤ 5 min)

Target: Akshay Naidu, IntelliBooks. Due Tue 24 Nov 2026, 08:00 IST.
Record AFTER Clerk keys are in `.env` (publishable + secret + JWKS URL + issuer) and the app is running locally (backend SQLite dev mode + `npm run dev` frontend) — no Docker in this VM. Two Clerk test accounts needed (User A + User B).

## Shot list (with narration cues)

### 0:00–0:30 — Sign in + empty state
- Open the app (http://localhost:5173). Sign in as User A via Clerk (show the Clerk sign-in screen briefly).
- Dashboard empty state: "No contracts yet" + Upload button. (Narration: "Signed in as User A. Nothing uploaded yet.")

### 0:30–1:00 — Upload
- Upload `samples/sample-contract-missing-items.pdf` (Consulting Agreement, 3 items missing).
- Show status `processing`, then poll to `reviewed`. (Narration: "Upload starts a background review — the file never blocks the request.")

### 1:00–2:30 — Checklist walkthrough (incl. one "not found")
- Open the review. Walk the 8 items quickly; linger on two:
  - A FOUND item (e.g. parties or payment terms): show the one-line summary + verbatim quote + page/section, then CLICK the quote to jump to the full clause in the contract text.
  - A NOT FOUND item (limitation of liability): show the honest "not found in the contract" verdict + empty quote. (Narration: "Nothing is guessed — if the contract doesn't cover it, the app says so.")
- Point at the risk flags (no liability cap, no governing law, no auto-renewal).

### 2:30–3:30 — Follow-up chat (2 questions, one unanswerable)
- Q1 (answerable): "What are the payment terms?" — show the streamed answer + verified `Sources:` with quotes.
- Q2 (unanswerable): "What is the cap on liability under this contract?" — show the app answering that the contract does not state a liability cap (not found), not inventing one. (Narration: "The chat only answers from the contract, with quotes.")

### 3:30–4:15 — Second user / isolation
- Sign out, sign in as User B (second Clerk account). Dashboard shows NO contracts — User A's contract is invisible.
- (If time) Show a direct API call with User A's contract id as User B → 404. (Narration: "Another user's contract is unreachable, even by direct API call with its id.")

### 4:15–5:00 — Short code walkthrough
- `backend/app/chunking.py` — clauses, not fixed slices; `[[PAGE n]]` markers.
- `backend/app/retrieval.py` — keyword first, vector second (pgvector cosine).
- `backend/app/quotes.py` — every quote verified as a normalised substring of the contract text; unverified → `unclear`.
- `backend/app/auth.py` + `isolation.py` — Clerk JWT verified RS256 against JWKS; every query filtered by user id; other user's id → 404, never 403.
- Mention: OpenRouter free models + Groq fallback (50/day quota), 45 tests, eval 18/18.

## Notes
- Keep narration in Sasi's own words — he walks the code in the follow-up call, so the video's walkthrough should match what he will say there.
- Do NOT show any API key value on screen. The `.env` file must never appear in a recording.
- If the OpenRouter quota is still exhausted at record time, the UI shows the Groq-fallback `review_note` — mention it in one line, don't hide it.
- Upload the finished video to Drive (or as required) and submit repo + README + video to akshay@intellibooks.io (or WhatsApp +91 88399 23672) before 08:00 IST Tue 24 Nov.
