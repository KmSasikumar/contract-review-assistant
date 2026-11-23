"""Chat completions via OpenRouter (free models), with Groq as a backup
when OpenRouter is rate-limited, plus a deterministic rule-based stand-in
used by tests and the eval script when no key is set.

Live models (from the brief):
  - nvidia/nemotron-3-ultra-550b-a55b:free (default)
  - google/gemma-4-31b-it:free (set OPENROUTER_CHAT_MODEL to switch)

Streaming: OpenRouter returns server-sent events; we yield each delta's
content as it arrives so the frontend can stream the answer.

The rule-based client is NOT an AI: it answers from the retrieved chunks by
keyword matching, quoting the matching sentence. It exists so the review and
chat pipelines can be tested end-to-end without a key, and so the eval
script can measure pipeline accuracy (chunking, retrieval, quote checks)
separately from LLM quality.
"""
import json
import logging
import re
import time

from . import http_client
from .config import settings
from .embeddings import AIError, RateLimitError
from .retrieval import content_words

logger = logging.getLogger(__name__)

# Waits (seconds) between retries when a provider rate-limits us. Free
# tiers recover within a minute; a longer wait would stall the review.
_RETRY_WAITS = (15, 30, 60)
_MAX_ATTEMPTS = 4  # initial try + 3 retries


def _retry_wait(resp, attempt: int) -> float:
    """Seconds to wait after a 429: honour Retry-After when the provider
    sends one, otherwise the backoff ladder above."""
    try:
        after = float(resp.headers.get("retry-after") or 0)
    except (TypeError, ValueError):
        after = 0
    if after > 0:
        return min(after, 60)
    return _RETRY_WAITS[min(attempt, len(_RETRY_WAITS) - 1)]


class _ChatLLM:
    """One OpenAI-compatible chat endpoint (OpenRouter or Groq).

    Both providers speak the same chat-completions API, including JSON
    mode (response_format) and SSE streaming, so one client serves both.
    """

    def __init__(self, url: str, api_key: str, model: str, provider: str,
                 max_attempts: int = _MAX_ATTEMPTS):
        self.url = url
        self.api_key = api_key
        self.model = model
        self.provider = provider
        # How many tries a 429 gets. A provider that is only a fallback's
        # primary is created with max_attempts=1: retrying it is pointless
        # when the backup is the retry (see get_llm).
        self.max_attempts = max_attempts

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def complete_json(self, messages: list[dict]) -> dict:
        """One chat completion, parsed as JSON (response_format json_object).

        A 429 is retried a few times with backoff — free tiers recover
        within a minute — and only then reported as a rate limit.
        """
        last_error: RateLimitError | None = None
        for attempt in range(self.max_attempts):
            resp = http_client.post(
                self.url,
                headers=self._headers(),
                json={
                    "model": self.model,
                    "messages": messages,
                    "response_format": {"type": "json_object"},
                    "temperature": 0,
                },
                timeout=180,
            )
            if resp.status_code == 429:
                wait = _retry_wait(resp, attempt)
                last_error = RateLimitError(
                    f"{self.provider} rate limit reached. Please wait a minute and retry."
                )
                if attempt + 1 < self.max_attempts:
                    logger.warning(
                        "%s rate limit (attempt %d/%d); retrying in %ss",
                        self.provider, attempt + 1, self.max_attempts, wait,
                    )
                    time.sleep(wait)
                    continue
                raise last_error
            if resp.status_code >= 400:
                raise AIError(f"Chat request failed ({resp.status_code}): {resp.text[:300]}")
            content = resp.json()["choices"][0]["message"]["content"]
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                # Try to salvage a JSON object from the raw text.
                m = re.search(r"\{.*\}", content, re.DOTALL)
                if m:
                    return json.loads(m.group(0))
                raise AIError("The model did not return valid JSON.")
        raise last_error  # pragma: no cover - the loop always raises or returns

    def stream(self, messages: list[dict]):
        """Yield content deltas as they arrive (SSE from the provider).

        A 429 before the first token is retried like complete_json; once
        tokens have started flowing the error is reported, not restarted.
        """
        for attempt in range(self.max_attempts):
            yielded = False
            retry = False
            try:
                with http_client.stream(
                    "POST",
                    self.url,
                    headers=self._headers(),
                    json={"model": self.model, "messages": messages, "stream": True, "temperature": 0},
                    timeout=180,
                ) as resp:
                    if resp.status_code == 429:
                        if attempt + 1 < self.max_attempts:
                            wait = _retry_wait(resp, attempt)
                            logger.warning(
                                "%s rate limit on stream (attempt %d/%d); retrying in %ss",
                                self.provider, attempt + 1, self.max_attempts, wait,
                            )
                            time.sleep(wait)
                            retry = True
                        else:
                            raise RateLimitError(
                                f"{self.provider} rate limit reached. Please wait a minute and retry."
                            )
                    elif resp.status_code >= 400:
                        raise AIError(f"Chat request failed ({resp.status_code})")
                    else:
                        for line in resp.iter_lines():
                            if not line.startswith("data:"):
                                continue
                            payload = line[5:].strip()
                            if payload == "[DONE]":
                                break
                            try:
                                chunk = json.loads(payload)
                            except json.JSONDecodeError:
                                continue
                            delta = chunk["choices"][0].get("delta", {})
                            if delta.get("content"):
                                yielded = True
                                yield delta["content"]
                if retry:
                    continue
                return
            except RateLimitError:
                if yielded:
                    raise
                if attempt + 1 >= self.max_attempts:
                    raise
                continue


class OpenRouterLLM(_ChatLLM):
    def __init__(self, api_key: str | None = None, model: str | None = None,
                 max_attempts: int = _MAX_ATTEMPTS):
        api_key = api_key or settings.openrouter_api_key
        if not api_key:
            raise AIError(
                "OPENROUTER_API_KEY is not set. Add it to .env (see README) "
                "or run with REVIEW_FALLBACK=rule_based for the eval script."
            )
        super().__init__(
            "https://openrouter.ai/api/v1/chat/completions",
            api_key,
            model or settings.openrouter_chat_model,
            "OpenRouter",
            max_attempts,
        )


class GroqLLM(_ChatLLM):
    """Backup chat provider (Groq, OpenAI-compatible API).

    Groq has no embeddings API, so it only ever backs up the chat calls;
    retrieval falls back to keywords (see pipeline.py). Free tier is
    generous (tens of requests/min), so it covers an exhausted OpenRouter
    free daily quota (50 free-model requests/day).
    """

    def __init__(self, api_key: str | None = None, model: str | None = None,
                 max_attempts: int = _MAX_ATTEMPTS):
        api_key = api_key or settings.groq_api_key
        if not api_key:
            raise AIError("GROQ_API_KEY is not set. Add it to .env (see README).")
        super().__init__(
            "https://api.groq.com/openai/v1/chat/completions",
            api_key,
            model or settings.groq_chat_model,
            "Groq",
            max_attempts,
        )


class FallbackLLM:
    """Try the primary LLM; on a rate limit, use the backup for that call.

    ``fallback_used`` records that the backup answered, so the caller can
    tell the user (see Contract.review_note). Streaming only switches
    before the first token: once an answer has started, a mid-stream
    rate limit is reported, not silently restarted.
    """

    def __init__(self, primary, backup):
        self.primary = primary
        self.backup = backup
        self.fallback_used = False

    def complete_json(self, messages: list[dict]) -> dict:
        try:
            return self.primary.complete_json(messages)
        except RateLimitError:
            self.fallback_used = True
            return self.backup.complete_json(messages)

    def stream(self, messages: list[dict]):
        yielded = False
        try:
            for token in self.primary.stream(messages):
                yielded = True
                yield token
        except RateLimitError:
            if yielded:
                raise
            self.fallback_used = True
            yield from self.backup.stream(messages)


class RuleBasedLLM:
    """Deterministic keyword extractor (tests/eval only, no key needed).

    complete_json: expects the prompt to contain excerpts labelled
    [chunk <id> | page <n> | <section>] and a final "ITEMS:" JSON list of
    {key, question, keywords}. For each item it searches the excerpts for
    any keyword; on a hit it returns status found with the whole matching
    excerpt (the clause) as the quote, otherwise not_found.
    """

    _CHUNK_RE = re.compile(
        r"\[chunk ([0-9a-f\-]+) \| page (\d+|-) \| ([^\]]*)\]\n(.*?)(?=\n\[chunk |\nITEMS:|\nQuestion:|\Z)",
        re.DOTALL,
    )

    def _excerpts(self, prompt: str):
        return [
            {"id": m.group(1), "page": m.group(2), "section": m.group(3), "text": m.group(4)}
            for m in self._CHUNK_RE.finditer(prompt)
        ]

    def complete_json(self, messages: list[dict]) -> dict:
        prompt = messages[-1]["content"]
        excerpts = self._excerpts(prompt)
        items_match = re.search(r"ITEMS:\s*(\[.*\])", prompt, re.DOTALL)
        items = json.loads(items_match.group(1)) if items_match else []
        results = []
        for item in items:
            found = None
            for ex in excerpts:
                low = ex["text"].lower()
                if any(kw.lower() in low for kw in item["keywords"]):
                    # The whole excerpt is the clause; quote it in full.
                    found = (ex, ex["text"].strip())
                    break
            if found:
                ex, text = found
                first_sentence = re.split(r"(?<=[.!?])\s+", text)[0]
                results.append(
                    {
                        "key": item["key"],
                        "status": "found",
                        "summary": first_sentence[:160],
                        "quote": text,
                        "chunk_id": ex["id"],
                    }
                )
            else:
                results.append(
                    {
                        "key": item["key"],
                        "status": "not_found",
                        "summary": "Not found in the contract.",
                        "quote": "",
                        "chunk_id": None,
                    }
                )
        return {"items": results}

    def stream(self, messages: list[dict]):
        """Yield an answer built from the excerpts, token by token.

        Same grounding rules as the live path: the answer quotes the
        matching sentence and ends with a Sources section, so the backend
        can verify the quote exactly as it does for the live model.
        """
        prompt = messages[-1]["content"]
        excerpts = self._excerpts(prompt)
        q_match = re.search(r"Question:\s*(.*)$", prompt, re.DOTALL)
        question = q_match.group(1).strip() if q_match else ""
        keywords = content_words(question)
        hit = None
        for ex in excerpts:
            for sent in re.split(r"(?<=[.!?])\s+", ex["text"].strip()):
                if any(kw in sent.lower() for kw in keywords):
                    hit = (ex, sent.strip())
                    break
            if hit:
                break
        if hit:
            ex, sent = hit
            page = ex["page"]
            answer = (
                f"{sent}\n\nSources:\n"
                f'- [chunk {ex["id"]} | page {page}] "{sent}"'
            )
        else:
            answer = "I could not find that in the contract."
        words = answer.split(" ")
        for i in range(0, len(words), 8):
            yield " ".join(words[i:i + 8]) + (" " if i + 8 < len(words) else "")


def get_llm():
    """Primary LLM (OpenRouter), with the Groq backup when both keys are
    set; Groq alone when only its key is set. The rule-based stand-in
    applies only when REVIEW_FALLBACK=rule_based is set (tests/eval)."""
    if settings.openrouter_api_key:
        # The backup IS the retry for the primary: a rate-limited primary
        # fails fast (1 attempt) instead of burning minutes on retries.
        primary = OpenRouterLLM(max_attempts=1)
        if settings.groq_api_key:
            return FallbackLLM(primary, GroqLLM())
        return OpenRouterLLM()
    if settings.groq_api_key:
        return GroqLLM()
    if settings.review_fallback == "rule_based":
        return RuleBasedLLM()
    raise AIError(
        "OPENROUTER_API_KEY is not set. Add it to .env (see README) "
        "or run with REVIEW_FALLBACK=rule_based for the eval script."
    )
