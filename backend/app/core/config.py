from pathlib import Path
import re
from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    database_url: str
    jwt_secret_key: SecretStr
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    cors_origins: str = "http://localhost:5173"
    coordinator_invite_code: SecretStr | None = None
    llm_provider: str = "disabled"
    llm_api_key: SecretStr | None = None
    llm_endpoint: str | None = None
    llm_timeout_seconds: float = 30.0
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-3.5-flash-lite"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from_email: str | None = None
    smtp_starttls: bool = True
    smtp_timeout_seconds: float = 8.0
    model_dir: Path = PROJECT_ROOT / "ml" / "saved_models"
    application_enrollment_registry_path: Path = (
        PROJECT_ROOT / "data" / "processed" / "application_enrollment_registry.json"
    )

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("jwt_secret_key")
    @classmethod
    def validate_jwt_secret(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError("JWT_SECRET_KEY must contain at least 32 characters")
        return value

    @field_validator("access_token_expire_minutes")
    @classmethod
    def validate_expiry(cls, value: int) -> int:
        if value < 1 or value > 1440:
            raise ValueError("ACCESS_TOKEN_EXPIRE_MINUTES must be between 1 and 1440")
        return value

    @field_validator("jwt_algorithm")
    @classmethod
    def only_hmac_sha256(cls, value: str) -> str:
        if value != "HS256":
            raise ValueError("JWT_ALGORITHM must be HS256")
        return value

    @field_validator("llm_timeout_seconds")
    @classmethod
    def validate_llm_timeout(cls, value: float) -> float:
        if not 1 <= value <= 120:
            raise ValueError("LLM_TIMEOUT_SECONDS must be between 1 and 120")
        return value

    @field_validator("llm_provider")
    @classmethod
    def validate_provider(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("LLM_PROVIDER cannot be empty")
        return value.strip().lower()

    @field_validator("gemini_model")
    @classmethod
    def validate_gemini_model(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", value):
            raise ValueError("GEMINI_MODEL must be a model identifier")
        return value

    @field_validator("smtp_port")
    @classmethod
    def validate_smtp_port(cls, value: int) -> int:
        if not 1 <= value <= 65535:
            raise ValueError("SMTP_PORT must be between 1 and 65535")
        return value

    @field_validator("smtp_timeout_seconds")
    @classmethod
    def validate_smtp_timeout(cls, value: float) -> float:
        if not 1 <= value <= 30:
            raise ValueError("SMTP_TIMEOUT_SECONDS must be between 1 and 30")
        return value

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]
