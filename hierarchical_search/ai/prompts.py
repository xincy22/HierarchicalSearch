from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class PromptCatalog:
    def __init__(self, path: str | None = None):
        self.path = Path(path) if path else Path(__file__).with_name("prompts.yaml")
        self._data: dict[str, Any] = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}

    def get(self, *keys: str) -> str:
        node: Any = self._data
        for key in keys:
            node = node[key]
        return node

    def render(self, *keys: str, **kwargs: Any) -> str:
        return self.get(*keys).format(**kwargs)
