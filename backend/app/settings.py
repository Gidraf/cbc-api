from __future__ import annotations

import os


class Settings:
    database_url: str = os.getenv("DATABASE_URL", "")
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    queue_name: str = os.getenv("QUEUE_NAME", "generation_jobs")
    regeneration_queue_name: str = os.getenv("REGENERATION_QUEUE_NAME", "regeneration_jobs")
    result_ttl_seconds: int = int(os.getenv("RESULT_TTL_SECONDS", "86400"))

    # MinIO
    minio_endpoint: str = os.getenv("MINIO_ENDPOINT", "localhost:9000")
    minio_access_key: str = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
    minio_secret_key: str = os.getenv("MINIO_SECRET_KEY", "minioadmin")
    minio_secure: bool = os.getenv("MINIO_SECURE", "false").lower() == "true"
    minio_bucket: str = os.getenv("MINIO_BUCKET", "cbc-assets")
    minio_public_base_url: str = os.getenv("MINIO_PUBLIC_BASE_URL", "http://localhost:9000")

    # Playwright
    playwright_cdp_url: str = os.getenv("PLAYWRIGHT_CDP_URL", "http://localhost:3000")

    # Security & JWT
    jwt_secret: str = os.getenv("JWT_SECRET", "change-me-jwt-secret")
    jwt_exp_minutes: int = int(os.getenv("JWT_EXP_MINUTES", "480"))
    refresh_token_exp_days: int = int(os.getenv("REFRESH_TOKEN_EXP_DAYS", "7"))
    developer_api_key: str | None = os.getenv("DEVELOPER_API_KEY")

    # LLM Provider Keys
    openai_api_key: str | None = os.getenv("OPENAI_API_KEY")
    anthropic_api_key: str | None = os.getenv("ANTHROPIC_API_KEY")
    gemini_api_key: str | None = os.getenv("GEMINI_API_KEY")
    ollama_base_url: str | None = os.getenv("OLLAMA_BASE_URL")
    # Read a design with the agent where the patterns come up short. One model
    # call per document that needed it, and none for the ones that parsed.
    design_agent_enabled: bool = os.getenv("DESIGN_AGENT", "1") not in ("0", "false", "False")

    # Langfuse Integration
    langfuse_host: str = os.getenv("LANGFUSE_HOST", "http://localhost:3001")
    langfuse_public_key: str = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    langfuse_secret_key: str = os.getenv("LANGFUSE_SECRET_KEY", "")
    langfuse_env: str = os.getenv("LANGFUSE_ENV", "prod")
    langfuse_cache_ttl_seconds: int = int(os.getenv("LANGFUSE_CACHE_TTL", "300"))

    # SMTP Mail Server
    smtp_host: str = os.getenv("SMTP_HOST", "")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_user: str = os.getenv("SMTP_USER", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    smtp_from: str = os.getenv("SMTP_FROM", "notifications@cbc-api.local")
    smtp_secure: bool = os.getenv("SMTP_SECURE", "false").lower() == "true"
    email_recipients: list[str] = [
        email.strip() for email in os.getenv("EMAIL_RECIPIENTS", "admin@cbc-platform.ke").split(",") if email.strip()
    ]

    user_accounts = {
        "admin": {
            "password": os.getenv("ADMIN_PASSWORD", "admin123"),
            "role": "admin",
        },
        "operator": {
            "password": os.getenv("OPERATOR_PASSWORD", "operator123"),
            "role": "operator",
        },
        "reviewer": {
            "password": os.getenv("REVIEWER_PASSWORD", "reviewer123"),
            "role": "reviewer",
        },
        "developer": {
            "password": os.getenv("DEVELOPER_PASSWORD", "developer123"),
            "role": "developer",
        },
    }


settings = Settings()
