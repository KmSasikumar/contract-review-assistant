"""Clerk token verification with a throwaway RSA key (no live Clerk)."""
import pytest

from app import auth
from app.config import settings
from conftest import make_jwks, make_rsa_key, make_token


@pytest.fixture()
def keypair():
    key, priv_pem = make_rsa_key()
    return key, priv_pem


def test_valid_token_returns_sub(keypair):
    key, priv_pem = keypair
    jwks = make_jwks(key.public_key())
    token = make_token(priv_pem)
    assert auth.verify_token(token, jwks=jwks) == "user-123"


def test_expired_token_rejected(keypair):
    key, priv_pem = keypair
    jwks = make_jwks(key.public_key())
    token = make_token(priv_pem, exp_offset=-60)
    with pytest.raises(Exception):
        auth.verify_token(token, jwks=jwks)


def test_wrong_key_rejected(keypair):
    key, priv_pem = keypair
    other_key, _ = make_rsa_key()
    jwks = make_jwks(other_key.public_key())
    token = make_token(priv_pem)
    with pytest.raises(Exception):
        auth.verify_token(token, jwks=jwks)


def test_wrong_issuer_rejected(keypair, monkeypatch):
    key, priv_pem = keypair
    jwks = make_jwks(key.public_key())
    monkeypatch.setattr(settings, "clerk_issuer", "https://expected.clerk.dev")
    token = make_token(priv_pem, iss="https://evil.example.com")
    with pytest.raises(Exception):
        auth.verify_token(token, jwks=jwks)


def test_token_rejected_when_issuer_unset(keypair, monkeypatch):
    """Fail closed: with CLERK_ISSUER unset, no token is accepted, even
    one whose signature verifies against the supplied JWKS."""
    key, priv_pem = keypair
    jwks = make_jwks(key.public_key())
    monkeypatch.setattr(settings, "clerk_issuer", "")
    token = make_token(priv_pem, iss="https://test.clerk.dev")
    with pytest.raises(Exception):
        auth.verify_token(token, jwks=jwks)


def test_unknown_kid_rejected(keypair):
    key, priv_pem = keypair
    jwks = make_jwks(key.public_key(), kid="other-key")
    token = make_token(priv_pem, kid="test-key")
    with pytest.raises(Exception):
        auth.verify_token(token, jwks=jwks)
