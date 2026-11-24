"""Review pipeline end-to-end on the sample contracts, using the
deterministic rule-based stand-in (no live key). Statuses must match
expected-results.json and every 'found' quote must verify."""
import json
import os

from app.models import Contract
from app.routers.pipeline import create_contract, process_contract

SAMPLES = os.path.join(os.path.dirname(__file__), "..", "..", "samples")


def _run_sample(db, filename: str) -> Contract:
    with open(os.path.join(SAMPLES, filename), "rb") as fh:
        data = fh.read()
    contract = create_contract(db, "user-a", filename, len(data), "text/plain")
    process_contract(contract.id, data, filename)
    db.expire_all()
    return db.query(Contract).filter(Contract.id == contract.id).first()


def test_complete_contract_all_found(db):
    with open(os.path.join(SAMPLES, "expected-results.json")) as fh:
        expected = json.load(fh)["sample-contract-complete.txt"]
    contract = _run_sample(db, "sample-contract-complete.txt")
    assert contract.status == "reviewed"
    got = {it.key: it for it in contract.review_items}
    assert len(got) == 8
    for key, want in expected.items():
        item = got[key]
        assert item.status == want["status"], f"{key}: got {item.status}"
        if want["status"] == "found":
            assert item.quote and want["quote_must_contain"] in item.quote, key
            assert item.quote_verified, key


def test_missing_items_contract(db):
    with open(os.path.join(SAMPLES, "expected-results.json")) as fh:
        expected = json.load(fh)["sample-contract-missing-items.txt"]
    contract = _run_sample(db, "sample-contract-missing-items.txt")
    assert contract.status == "reviewed"
    got = {it.key: it for it in contract.review_items}
    for key, want in expected.items():
        item = got[key]
        assert item.status == want["status"], f"{key}: got {item.status}"
        if want["status"] == "not_found":
            assert not item.quote, key
        else:
            assert want["quote_must_contain"] in (item.quote or ""), key
            assert item.quote_verified, key


def test_invented_quote_becomes_unclear(db):
    """A model quote that is not in the contract must flip the item to unclear."""
    from app.llm import RuleBasedLLM
    from app.review import run_review

    class LyingLLM(RuleBasedLLM):
        def complete_json(self, messages):
            out = super().complete_json(messages)
            for it in out["items"]:
                if it["status"] == "found":
                    it["quote"] = "The parties agree to pay one billion dollars in gold."
            return out

    with open(os.path.join(SAMPLES, "sample-contract-complete.txt"), "rb") as fh:
        data = fh.read()
    contract = create_contract(db, "user-a", "c.txt", len(data), "text/plain")
    process_contract(contract.id, data, "c.txt")
    # Re-run with the lying model over the stored chunks.
    run_review(db, contract, llm=LyingLLM())
    got = {it.key: it for it in contract.review_items}
    assert got["parties"].status == "unclear"
    assert got["parties"].quote_verified is False


def test_empty_quote_found_becomes_unclear(db):
    """A 'found' verdict with no quote must not stand — it is unverified."""
    from app.llm import RuleBasedLLM
    from app.review import run_review

    class EmptyQuoteLLM(RuleBasedLLM):
        def complete_json(self, messages):
            out = super().complete_json(messages)
            for it in out["items"]:
                if it["status"] == "found":
                    it["quote"] = ""
            return out

    with open(os.path.join(SAMPLES, "sample-contract-complete.txt"), "rb") as fh:
        data = fh.read()
    contract = create_contract(db, "user-a", "c.txt", len(data), "text/plain")
    process_contract(contract.id, data, "c.txt")
    run_review(db, contract, llm=EmptyQuoteLLM())
    got = {it.key: it for it in contract.review_items}
    # Every item the model called "found" must now be unclear, with no
    # verified quote — never a green Found with no evidence.
    assert got["parties"].status == "unclear"
    assert got["parties"].quote_verified is False


def test_retry_review_with_no_chunks_fails(db):
    """Retry on a contract whose text never parsed must fail, not
    fabricate 8 'Not found' verdicts and a 'reviewed' status."""
    from app.routers.pipeline import retry_review

    contract = create_contract(db, "user-a", "bad.pdf", 10, "application/pdf")
    # No chunks stored (parse never succeeded).
    result = retry_review(contract.id)
    assert result is not None
    assert result.status == "failed"
    assert "re-upload" in (result.error or "")
