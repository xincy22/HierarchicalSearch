from pathlib import Path

from hierarchical_search.app.config import Settings


def test_settings_loads_from_env_file(monkeypatch, tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "HS_LLM_BACKEND=openai",
                "HS_OPENAI_CHAT_MODEL=GLM-4.7-Flash",
                "HS_OPENAI_BASE_URL=https://open.bigmodel.cn/api/paas/v4/",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("HS_ENV_FILE", env_file.as_posix())
    monkeypatch.delenv("HS_LLM_BACKEND", raising=False)
    monkeypatch.delenv("HS_OPENAI_CHAT_MODEL", raising=False)
    monkeypatch.delenv("HS_OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    settings = Settings.from_env()
    assert settings.llm_backend == "openai"
    assert settings.openai_chat_model == "GLM-4.7-Flash"
    assert settings.openai_base_url == "https://open.bigmodel.cn/api/paas/v4/"


def test_settings_env_vars_override_env_file(monkeypatch, tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text("HS_LLM_BACKEND=openai\n", encoding="utf-8")

    monkeypatch.setenv("HS_ENV_FILE", env_file.as_posix())
    monkeypatch.setenv("HS_LLM_BACKEND", "rule")

    settings = Settings.from_env()
    assert settings.llm_backend == "rule"
