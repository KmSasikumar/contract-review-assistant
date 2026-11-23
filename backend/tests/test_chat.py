"""Chat: streaming answers, verified sources, history persists."""
import json

from app.chat import answer_stream, get_history
from app.models import Contract
from app.routers.pipeline import create_contract, process_contract

TEXT = (
    "CONSULTING AGREEMENT\n\n"
    "This Agreement is between BrightPath Consulting LLP and Kite Foods Private Limited.\n\n"
    "1. Term\n\nThis Agreement starts on 1 March 2026 and continues for six (6) months.\n\n"
    "2. Termination\n\nEither Party may end this Agreement by giving thirty (30) days' written notice.\n"
)


def _contract(db):
    data = TEXT.encode()
    contract = create_contract(db, "user-a", "c.txt", len(data), "text/plain")
    process_contract(contract.id, data, "c.txt")
    db.expire_all()
    return db.query(Contract).filter(Contract.id == contract.id).first()


def test_chat_answer_quotes_verified_clause(db):
    contract = _contract(db)
    events = list(answer_stream(db, contract, "How can either side end this agreement?"))
    tokens = "".join(ev.get("text", "") for ev in events if ev["type"] == "token")
    assert "thirty (30) days" in tokens
    done = [ev for ev in events if ev["type"] == "done"]
    assert done and done[0]["sources"]
    assert done[0]["sources"][0]["verified"] is True


def test_chat_history_persists(db):
    contract = _contract(db)
    list(answer_stream(db, contract, "When does it start?"))
    list(answer_stream(db, contract, "How can it end?"))
    history = get_history(db, "user-a", contract.id)
    assert [m.role for m in history] == ["user", "assistant", "user", "assistant"]
    assert "When does it start?" in history[0].content


def test_chat_unknown_question_says_so(db):
    contract = _contract(db)
    events = list(answer_stream(db, contract, "What is the weather on Mars?"))
    tokens = "".join(ev.get("text", "") for ev in events if ev["type"] == "token")
    assert "could not find" in tokens.lower()


def test_chat_endpoint_streams_and_stores(client):
    import io

    files = {"file": ("c.txt", io.BytesIO(TEXT.encode()), "text/plain")}
    cid = client.post("/api/contracts", files=files).json()["id"]
    resp = client.post(f"/api/contracts/{cid}/chat", json={"question": "How can it end?"})
    assert resp.status_code == 200
    body = resp.text
    assert '"type": "token"' in body or '"type": "done"' in body
    history = client.get(f"/api/contracts/{cid}/chat").json()
    assert len(history) == 2
    assert history[0]["role"] == "user" and history[1]["role"] == "assistant"
