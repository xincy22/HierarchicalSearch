from pathlib import Path

from hierarchical_search.ai.prompts import PromptCatalog


def test_prompt_catalog_loads_default_file():
    catalog = PromptCatalog()
    text = catalog.get("openai", "extract_topic", "system")
    assert "主题抽取器" in text


def test_prompt_catalog_render_with_custom_file(tmp_path: Path):
    prompt_file = tmp_path / "prompts.yaml"
    prompt_file.write_text(
        "openai:\n  resolve_section_id:\n    user_template: \"query={query}\"\n",
        encoding="utf-8",
    )
    catalog = PromptCatalog(str(prompt_file))
    rendered = catalog.render("openai", "resolve_section_id", "user_template", query="2.1")
    assert rendered == "query=2.1"
