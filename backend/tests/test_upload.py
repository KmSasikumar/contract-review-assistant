"""Upload validation: file types, size limit, empty files."""
import io

from app.config import settings


def test_upload_rejects_wrong_type(client):
    files = {"file": ("evil.exe", io.BytesIO(b"MZ..."), "application/octet-stream")}
    resp = client.post("/api/contracts", files=files)
    assert resp.status_code == 400
    assert "PDF, DOCX or TXT" in resp.json()["detail"]


def test_upload_rejects_oversize(client, monkeypatch):
    monkeypatch.setattr(settings, "max_upload_mb", 0)  # any non-empty file is over
    # The router reads MAX_BYTES at import time, so patch that too.
    import app.routers.contracts as contracts_router

    monkeypatch.setattr(contracts_router, "MAX_BYTES", 0)
    files = {"file": ("a.txt", io.BytesIO(b"hello"), "text/plain")}
    resp = client.post("/api/contracts", files=files)
    assert resp.status_code == 413


def test_upload_rejects_empty_text(client):
    files = {"file": ("a.txt", io.BytesIO(b"   "), "text/plain")}
    resp = client.post("/api/contracts", files=files)
    assert resp.status_code == 201  # upload accepted; parse fails in background
    cid = resp.json()["id"]
    # The background task marks it failed; poll until it lands.
    import time

    for _ in range(20):
        got = client.get(f"/api/contracts/{cid}").json()
        if got["status"] != "processing":
            break
        time.sleep(0.25)
    assert got["status"] == "failed"
    assert "No readable text" in (got["error"] or "")


def test_upload_requires_auth():
    from fastapi.testclient import TestClient

    from app.main import app

    app.dependency_overrides.clear()
    with TestClient(app) as c:
        files = {"file": ("a.txt", io.BytesIO(b"hello"), "text/plain")}
        assert c.post("/api/contracts", files=files).status_code == 401
