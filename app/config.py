from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    ENV: Literal["local", "development", "staging", "production", "test"] = "local"

    LOG_LEVEL: str = "INFO"

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://aegis:aegis@localhost:5432/aegis"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Meilisearch
    MEILI_URL: str = "http://localhost:7700"
    MEILI_MASTER_KEY: str = "change-me"

    # JWT
    JWT_PRIVATE_KEY_PATH: str = "secrets/jwt_private.pem"
    JWT_PUBLIC_KEY_PATH: str = "secrets/jwt_public.pem"
    JWT_ACCESS_TTL_SECONDS: int = 900
    JWT_REFRESH_TTL_SECONDS: int = 604800
    JWT_ISSUER: str = "aegis-backend"

    # AI
    GEMINI_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    AI_CACHE_TTL_SECONDS: int = 86400
    AI_RATE_LIMIT_TRAINEE: int = 60
    AI_RATE_LIMIT_INSTRUCTOR: int = 200
    AI_GLOBAL_RATE_LIMIT: int = 2000
    AI_PROVIDER_TIMEOUT_SECONDS: int = 15

    # ─── RAG ────────────────────────────────────────────────────────────────
    # Embedding
    EMBEDDING_DIM: int = 1536
    EMBEDDING_MODEL_HINT: str = "text-embedding-3-small"

    # Chunking
    RAG_CHUNK_TOKENS_MAX: int = 800
    RAG_CHUNK_OVERLAP_TOKENS: int = 100
    RAG_CHUNK_TOKENS_MIN_MERGE: int = 100

    # Retrieval / grounding
    RAG_TOP_K: int = 10
    RAG_MAX_CHUNKS: int = 5
    RAG_INCLUDE_THRESHOLD: float = 0.65
    RAG_SOFT_INCLUDE_THRESHOLD: float = 0.60
    RAG_SUGGEST_THRESHOLD: float = 0.50
    RAG_MMR_LAMBDA: float = 0.5
    RAG_USE_RERANKER: bool = False

    # Query rewriter
    RAG_REWRITER_MODEL: str = "gemini-1.5-flash"
    RAG_REWRITER_TIMEOUT_S: int = 5
    RAG_REWRITER_MAX_TOKENS: int = 100
    RAG_REWRITER_HISTORY_WINDOW: int = 6
    RAG_REWRITER_CACHE_TTL_S: int = 3600

    # Chat session
    CHAT_SESSION_AUTO_CLOSE_DAYS: int = 30

    # MinIO
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = ""
    MINIO_SECRET_KEY: str = ""
    MINIO_BUCKET_ASSETS: str = "aegis-assets"
    MINIO_BUCKET_CONTENT: str = "aegis-content"
    MINIO_SECURE: bool = False

    # CORS
    CORS_ALLOWED_ORIGINS: str = "http://localhost:3000"

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # ─── Content lifecycle (R73) ────────────────────────────────────────────
    CONTENT_REVIEW_CADENCE_DAYS_DEFAULT: int = 90
    CONTENT_REVIEW_CADENCE_DAYS_FCOM: int = 180
    CONTENT_REVIEW_CADENCE_DAYS_QRH: int = 90
    CONTENT_REVIEW_CADENCE_DAYS_AMM: int = 180
    CONTENT_REVIEW_CADENCE_DAYS_SOP: int = 90
    CONTENT_REVIEW_CADENCE_DAYS_SYLLABUS: int = 60
    CONTENT_EXPIRING_SOON_WINDOW_DAYS: int = 14

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        if v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql+asyncpg://", 1)
        if v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v

    @field_validator("CORS_ALLOWED_ORIGINS", mode="before")
    @classmethod
    def parse_cors(cls, v: str) -> str:
        return v

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ALLOWED_ORIGINS.split(",")]

    @property
    def is_production(self) -> bool:
        return self.ENV == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
