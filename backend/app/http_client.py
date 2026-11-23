"""HTTP helper for outbound calls (OpenRouter, Clerk JWKS).

Why this exists: httpx reads proxy settings from the environment by
default, but it crashes while parsing NO_PROXY values that contain
bracketed IPv6 literals such as "[::1]" — exactly what this sandbox
sets. We therefore read the proxy URL ourselves and pass it explicitly,
with trust_env=False so httpx never parses NO_PROXY. Every call we make
goes to a public host (openrouter.ai, Clerk), so ignoring NO_PROXY bypass
rules is safe here; in environments without a proxy, proxy=None means a
direct connection, as usual.
"""
import os

import httpx


def _proxy():
    return os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")


def _verify():
    """TLS verification bundle.

    httpx with trust_env=False ignores SSL_CERT_FILE, but sandboxes with a
    TLS-intercepting egress proxy put the proxy CA there (curl honours it,
    which is why curl works and httpx does not — the Clerk JWKS fetch failed
    with CERTIFICATE_VERIFY_FAILED until this was set). Read it explicitly
    so verification still happens, against the bundle the environment
    provides. Falls back to httpx's default verification when unset.
    Verified: with this, both the Clerk JWKS and Groq return 200.
    """
    cafile = os.environ.get("SSL_CERT_FILE")
    if cafile and os.path.exists(cafile):
        return cafile
    return True


def get(url, **kwargs):
    return httpx.get(url, proxy=_proxy(), trust_env=False, verify=_verify(), **kwargs)


def post(url, **kwargs):
    return httpx.post(url, proxy=_proxy(), trust_env=False, verify=_verify(), **kwargs)


def stream(method, url, **kwargs):
    return httpx.stream(method, url, proxy=_proxy(), trust_env=False, verify=_verify(), **kwargs)
