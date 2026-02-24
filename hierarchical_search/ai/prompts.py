from __future__ import annotations

from pathlib import Path
from typing import Any


class PromptCatalog:
    def __init__(self, path: str | None = None):
        default_path = Path(__file__).with_name("prompts.yaml")
        self.path = Path(path) if path else default_path
        self._data = self._load_yaml(self.path)

    @staticmethod
    def _load_yaml(path: Path) -> dict[str, Any]:
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "PyYAML is required for YAML prompt loading. Install with `pip install pyyaml`."
            ) from exc

        if not path.exists():
            raise RuntimeError(f"Prompt file not found: {path}")
        raw = path.read_text(encoding="utf-8")
        loaded = yaml.safe_load(raw)
        if loaded is None:
            return {}
        if not isinstance(loaded, dict):
            raise RuntimeError(f"Prompt file root must be a mapping: {path}")
        return loaded

    def get(self, *keys: str) -> str:
        node: Any = self._data
        visited = []
        for key in keys:
            visited.append(key)
            if not isinstance(node, dict) or key not in node:
                joined = ".".join(visited)
                raise RuntimeError(
                    f"Prompt key not found: {joined} (from {self.path.as_posix()})"
                )
            node = node[key]
        if not isinstance(node, str):
            joined = ".".join(keys)
            raise RuntimeError(
                f"Prompt value must be string: {joined} (from {self.path.as_posix()})"
            )
        return node

    def render(self, *keys: str, **kwargs: Any) -> str:
        template = self.get(*keys)
        try:
            return template.format(**kwargs)
        except KeyError as exc:
            raise RuntimeError(
                f"Missing template variable {exc!s} for prompt key {'.'.join(keys)}"
            ) from exc
