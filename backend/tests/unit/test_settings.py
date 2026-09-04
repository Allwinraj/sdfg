from pathlib import Path

from app.core.settings import Settings


def test_settings_from_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "sap_ai_core")
    monkeypatch.setenv("GEMINI_API_KEY", "g-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-flash-lite-latest")
    monkeypatch.setenv("AICORE_GPT40_MINI_DEPLOYMENT_ID", "dep-extract")
    monkeypatch.setenv("AICORE_GPT55_DEPLOYMENT_ID", "dep-reason")
    monkeypatch.setenv("AICORE_GPT41_DEPLOYMENT_ID", "dep-general")
    monkeypatch.setenv("AICORE_GPT40_DEPLOYMENT_ID", "dep-recon")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))

    settings = Settings(_env_file=None)
    assert settings.llm_provider == "sap_ai_core"
    assert settings.gemini_model_for("extraction") == "gemini-flash-lite-latest"
    assert settings.sap_deployment_for("extraction") == "dep-extract"
    assert settings.sap_deployment_for("reasoning") == "dep-reason"
    assert settings.sap_deployment_for("general") == "dep-general"
    assert settings.sap_deployment_for("reconciliation") == "dep-recon"
    assert settings.data_dir == tmp_path / "data"


def test_cors_origins_from_env(monkeypatch) -> None:
    monkeypatch.setenv(
        "CORS_ORIGINS",
        "https://nexus-ui.cfapps.example.hana.ondemand.com, http://localhost:5173",
    )
    settings = Settings(_env_file=None)
    assert settings.cors_origin_list() == [
        "https://nexus-ui.cfapps.example.hana.ondemand.com",
        "http://localhost:5173",
    ]


def test_gemini_per_role_override(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_MODEL", "gemini-flash-lite-latest")
    monkeypatch.setenv("GEMINI_REASONING_MODEL", "gemini-pro")
    settings = Settings(_env_file=None)
    assert settings.gemini_model_for("general") == "gemini-flash-lite-latest"
    assert settings.gemini_model_for("reasoning") == "gemini-pro"
