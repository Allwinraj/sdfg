from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_ROOT.parent
CONFIG_DIR = BACKEND_ROOT / "config"

LLMProviderName = Literal["gemini", "sap_ai_core"]
ModelRole = Literal["extraction", "reasoning", "general", "reconciliation"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    llm_provider: LLMProviderName = "gemini"
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"
    data_dir: Path = BACKEND_ROOT / "data"

    gemini_api_key: str = ""
    gemini_model: str = "gemini-flash-lite-latest"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    gemini_extraction_model: str = ""
    gemini_reasoning_model: str = ""
    gemini_general_model: str = ""
    gemini_reconciliation_model: str = ""

    xsuaa_url: str = ""
    xsuaa_client_id: str = ""
    xsuaa_client_secret: str = ""
    aicore_api_url: str = ""
    aicore_resource_group: str = "default"
    aicore_openai_api_version: str = "2024-12-01-preview"
    aicore_gpt40_mini_deployment_id: str = ""
    aicore_gpt55_deployment_id: str = ""
    aicore_gpt41_deployment_id: str = ""
    aicore_gpt40_deployment_id: str = ""

    llm_max_retries: int = 3
    llm_retry_base_seconds: float = 0.5
    llm_json_repair_attempts: int = 2
    ai_models_path: Path = CONFIG_DIR / "ai_models.yaml"

    @field_validator("data_dir", mode="before")
    @classmethod
    def _resolve_data_dir(cls, value: Path | str) -> Path:
        path = Path(value)
        if not path.is_absolute():
            path = (REPO_ROOT / path).resolve()
        return path

    def gemini_model_for(self, role: ModelRole) -> str:
        overrides = {
            "extraction": self.gemini_extraction_model,
            "reasoning": self.gemini_reasoning_model,
            "general": self.gemini_general_model,
            "reconciliation": self.gemini_reconciliation_model,
        }
        return overrides[role] or self.gemini_model

    def sap_deployment_for(self, role: ModelRole) -> str:
        mapping = {
            "extraction": self.aicore_gpt40_mini_deployment_id,
            "reasoning": self.aicore_gpt55_deployment_id,
            "general": self.aicore_gpt41_deployment_id,
            "reconciliation": self.aicore_gpt40_deployment_id,
        }
        return mapping[role] or mapping["general"] or mapping["extraction"] or mapping["reconciliation"]


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return settings
