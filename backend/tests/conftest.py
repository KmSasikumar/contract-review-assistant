"""Shared test fixtures: temp SQLite DB, API client with mocked auth,
throwaway RSA key for Clerk-token tests."""
import os
import sys

import pytest

# Env must be set BEFORE the app modules are imported (settings reads it).
_TMP = os.path.join(os.path.dirname(__file__), ".test-tmp")
os.makedirs(_TMP, exist_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["REVIEW_FALLBACK"] = "rule_based"
# Blank the keys (do NOT just pop them): pydantic-settings reads the .env
# file when the variable is absent, so a real key in .env would leak into
# tests and the suite would call the live APIs instead of the stand-ins.
os.environ["OPENROUTER_API_KEY"] = ""
os.environ["GROQ_API_KEY"] = ""
os.environ["GEMINI_API_KEY"] = ""

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import db as dbmod  # noqa: E402
from app.auth import CurrentUser, get_current_user  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _init_test_db():
    dbmod.init_db()
    yield
    try:
        os.remove(os.path.join(_TMP, "test.db"))
    except OSError:
        pass


@pytest.fixture()
def db():
    """A fresh database session; tables are emptied after each test."""
    from app.models import Base

    Base.metadata.drop_all(bind=dbmod.engine)
    Base.metadata.create_all(bind=dbmod.engine)
    session = dbmod.SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def user_a():
    return CurrentUser("user-a")


@pytest.fixture()
def user_b():
    return CurrentUser("user-b")


@pytest.fixture()
def client(user_a):
    """TestClient with auth mocked to user-a (override per test as needed)."""
    app.dependency_overrides[get_current_user] = lambda: user_a
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def auth_as(client_user: CurrentUser):
    app.dependency_overrides[get_current_user] = lambda: client_user


# --- RSA helpers for auth tests ---

def make_rsa_key():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return key, priv_pem


def make_jwks(public_key, kid="test-key"):
    import jwt

    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(public_key, as_dict=True)
    jwk["kid"] = kid
    jwk["alg"] = "RS256"
    jwk["use"] = "sig"
    return {"keys": [jwk]}


def make_token(priv_pem, kid="test-key", sub="user-123", iss="https://test.clerk.dev", exp_offset=3600):
    import time

    import jwt

    now = int(time.time())
    return jwt.encode(
        {"sub": sub, "iss": iss, "iat": now, "exp": now + exp_offset, "sid": "sess_1"},
        priv_pem,
        algorithm="RS256",
        headers={"kid": kid},
    )
