"""Data isolation at the API level: user B cannot read, review, chat with
or delete user A's contract — even by calling the API directly with the id.
Every such attempt must return 404, never the other user's data."""
import io

from app.auth import CurrentUser
from conftest import auth_as

CONTRACT_TEXT = (
    "MASTER SERVICES AGREEMENT\n\n"
    "This Agreement is between Northwind Labs Private Limited and Acme Retail Limited.\n\n"
    "1. Term\n\nThis Agreement starts on 1 January 2026 and continues for twelve (12) months.\n\n"
    "2. Fees and Payment\n\nAcme will pay Northwind INR 5,00,000 per quarter.\n"
)


def _upload(client, filename="c.txt"):
    files = {"file": (filename, io.BytesIO(CONTRACT_TEXT.encode()), "text/plain")}
    resp = client.post("/api/contracts", files=files)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_other_user_cannot_get_contract(client, user_b):
    cid = _upload(client)
    auth_as(user_b)
    assert client.get(f"/api/contracts/{cid}").status_code == 404


def test_other_user_cannot_list_others_contracts(client, user_b):
    _upload(client)
    auth_as(user_b)
    assert client.get("/api/contracts").json() == []


def test_other_user_cannot_read_text_review_or_chat(client, user_b):
    cid = _upload(client)
    auth_as(user_b)
    assert client.get(f"/api/contracts/{cid}/text").status_code == 404
    assert client.get(f"/api/contracts/{cid}/review").status_code == 404
    assert client.get(f"/api/contracts/{cid}/chat").status_code == 404
    assert client.post(f"/api/contracts/{cid}/chat", json={"question": "hi?"}).status_code == 404


def test_other_user_cannot_delete_contract(client, user_b):
    cid = _upload(client)
    auth_as(user_b)
    assert client.delete(f"/api/contracts/{cid}").status_code == 404
    # And it is still there for the owner.
    auth_as(CurrentUser("user-a"))
    assert client.get(f"/api/contracts/{cid}").status_code == 200


def test_owner_can_delete_own_contract(client):
    cid = _upload(client)
    assert client.delete(f"/api/contracts/{cid}").status_code == 204
    assert client.get(f"/api/contracts/{cid}").status_code == 404


def test_unknown_contract_id_is_404(client):
    assert client.get("/api/contracts/00000000-0000-0000-0000-000000000000").status_code == 404
    assert client.get("/api/contracts/not-a-uuid").status_code == 404
