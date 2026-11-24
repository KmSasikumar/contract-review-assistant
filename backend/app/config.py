"""Settings, read from environment (.env). No secrets are hard-coded here."""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite:///./contract_review.db"

    clerk_publishable_key: str = ""
    clerk_secret_key: str = ""
    clerk_jwks_url: str = ""
    clerk_issuer: str = ""

    openrouter_api_key: str = ""
    openrouter_chat_model: str = "nvidia/nemotron-3-ultra-550b-a55b:free"
    openrouter_embed_model: str = "nvidia/nemotron-3.5-embed-1b:free"

    # Backup chat provider. Used ONLY when OpenRouter is rate-limited
    # (its free tier is 50 free-model requests/day). Groq has no
    # embeddings API, so the embedding fallback is keyword retrieval.
    groq_api_key: str = ""
    groq_chat_model: str = "qwen/qwen3.8-27b"

    # Primary chat provider (Google Gemini, OpenAI-compatible endpoint).
    # Trusted over OpenRouter/Groq; those two remain as fallbacks.
    gemini_api_key: str = ""
    gemini_chat_model: str = "gemini-2.5-flash"

    # Dev/eval only: "rule_based" runs the review pipeline without an
    # OpenRouter key, using a deterministic keyword extractor. Never use in prod.
    review_fallback: str = ""

    max_upload_mb: int = 20
    embed_batch_size: int = 16
    retrieve_top_k: int = 6

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
