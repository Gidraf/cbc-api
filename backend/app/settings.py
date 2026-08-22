from __future__ import annotations

import os


class Settings:
    database_url: str = os.getenv("DATABASE_URL", "")
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    queue_name: str = os.getenv("QUEUE_NAME", "generation_jobs")
    result_ttl_seconds: int = int(os.getenv("RESULT_TTL_SECONDS", "86400"))

    minio_endpoint: str = os.getenv("MINIO_ENDPOINT", "localhost:9000")
    minio_access_key: str = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
    minio_secret_key: str = os.getenv("MINIO_SECRET_KEY", "minioadmin")
    minio_secure: bool = os.getenv("MINIO_SECURE", "false").lower() == "true"
    minio_bucket: str = os.getenv("MINIO_BUCKET", "cbc-assets")
    minio_public_base_url: str = os.getenv("MINIO_PUBLIC_BASE_URL", "http://localhost:9000")

    playwright_cdp_url: str = os.getenv("PLAYWRIGHT_CDP_URL", "http://localhost:3000")

    jwt_secret: str = os.getenv("JWT_SECRET", "change-me-jwt-secret")
    jwt_exp_minutes: int = int(os.getenv("JWT_EXP_MINUTES", "480"))
    developer_api_key: str | None = os.getenv("DEVELOPER_API_KEY")

    openai_api_key: str | None = os.getenv("OPENAI_API_KEY")
    anthropic_api_key: str | None = os.getenv("ANTHROPIC_API_KEY")
    gemini_api_key: str | None = os.getenv("GEMINI_API_KEY")
    ollama_base_url: str | None = os.getenv("OLLAMA_BASE_URL")

    user_accounts = {
        "admin": {
            "password": os.getenv("ADMIN_PASSWORD", ""),
            "role": "admin",
        },
        "operator": {
            "password": os.getenv("OPERATOR_PASSWORD", ""),
            "role": "operator",
        },
        "reviewer": {
            "password": os.getenv("REVIEWER_PASSWORD", ""),
            "role": "reviewer",
        },
        "developer": {
            "password": os.getenv("DEVELOPER_PASSWORD", ""),
            "role": "developer",
        },
    }


settings = Settings()
