"""Eval: run the review pipeline on the two sample contracts and score it.

Usage:
  # No key needed — uses the deterministic rule-based stand-in + hash
  # embeddings, so this measures the PIPELINE (chunking, retrieval, quote
  # verification, statuses), not the LLM's judgement:
  python3 eval/eval.py

  # With a live OpenRouter key, measure the real review quality:
  OPENROUTER_API_KEY=... python3 eval/eval.py --live

Scores each checklist item: status must match expected-results.json, and a
"found" item's quote must contain the expected phrase and be verified
against the contract text. Also asks one follow-up question per contract
and checks the answer carries a verified quote (or says it is not found).
"""
import argparse
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "backend"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true",
                        help="Use the live OpenRouter key instead of the rule-based stand-in.")
    args = parser.parse_args()

    tmp = tempfile.mkdtemp(prefix="contract-eval-")
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/eval.db"
    if args.live:
        if not os.environ.get("OPENROUTER_API_KEY"):
            print("ERROR: --live needs OPENROUTER_API_KEY in the environment.")
            return 2
        os.environ.pop("REVIEW_FALLBACK", None)
    else:
        # Blank the keys (do NOT just pop them): pydantic-settings reads
        # the .env file when the variable is absent, so a real key in .env
        # would leak in and the "no-key" run would call the live APIs.
        os.environ["OPENROUTER_API_KEY"] = ""
        os.environ["GROQ_API_KEY"] = ""
        os.environ["REVIEW_FALLBACK"] = "rule_based"

    from app import db as dbmod
    from app.chat import answer_stream
    from app.models import Contract
    from app.routers.pipeline import create_contract, process_contract

    engine = dbmod.init_db()
    session_factory = dbmod.sessionmaker(bind=engine)

    with open(os.path.join(ROOT, "samples", "expected-results.json")) as fh:
        expected = json.load(fh)

    questions = {
        "sample-contract-complete.txt": "What is the cap on liability?",
        "sample-contract-missing-items.txt": "Does the contract auto-renew?",
    }

    total = correct = 0
    rows = []
    for filename, wanted in expected.items():
        path = os.path.join(ROOT, "samples", filename)
        with open(path, "rb") as fh:
            data = fh.read()
        db = session_factory()
        contract = create_contract(db, "eval-user", filename, len(data), "text/plain")
        db.close()
        process_contract(contract.id, data, filename)

        db = session_factory()
        contract = db.query(Contract).filter(Contract.id == contract.id).first()
        got = {it.key: it for it in contract.review_items}
        line = [f"\n== {filename} (status: {contract.status}) =="]
        for key, want in wanted.items():
            total += 1
            item = got.get(key)
            ok = item is not None and item.status == want["status"]
            detail = ""
            if ok and want["status"] == "found":
                phrase = want["quote_must_contain"]
                if not item.quote or phrase not in item.quote:
                    ok = False
                    detail = f"quote missing phrase {phrase!r}"
                elif not item.quote_verified:
                    ok = False
                    detail = "quote failed verification"
            elif not ok:
                detail = f"got {item.status if item else 'no item'}, want {want['status']}"
            correct += 1 if ok else 0
            line.append(f"  [{'PASS' if ok else 'FAIL'}] {key}: {detail or 'ok'}")
        # One follow-up question per contract (single pass: collect tokens
        # and the final "done" event together, so history is stored once).
        q = questions[filename]
        answer_parts: list[str] = []
        done_sources: list[dict] = []
        for ev in answer_stream(db, contract, q):
            if ev["type"] == "token":
                answer_parts.append(ev.get("text", ""))
            elif ev["type"] == "done":
                done_sources = ev.get("sources", [])
        answer = "".join(answer_parts)
        verified = any(s.get("verified") for s in done_sources)
        low = answer.lower()
        chat_ok = verified or "not found" in low or "could not find" in low or "does not" in low
        line.append(f"  [{'PASS' if chat_ok else 'FAIL'}] chat: {q!r} -> "
                    f"{answer[:120]!r} (verified quote: {verified})")
        if contract.review_note:
            line.append(f"  note: {contract.review_note}")
        total += 1
        correct += 1 if chat_ok else 0
        rows.extend(line)
        db.close()

    print("\n".join(rows))
    print(f"\nAccuracy: {correct}/{total} = {correct / total:.0%}")
    print("Mode:", "live OpenRouter" if args.live else "rule-based stand-in (pipeline only)")
    return 0 if correct == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
