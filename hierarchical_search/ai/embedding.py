from __future__ import annotations

from hashlib import blake2b
import math
import re
from typing import Protocol


class Embedder(Protocol):
    dim: int

    def embed_text(self, text: str) -> list[float]:
        ...

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        ...


class HashingEmbedder:
    def __init__(self, dim: int = 384):
        self.dim = dim

    def _tokenize(self, text: str) -> list[str]:
        ascii_tokens = re.findall(r"[A-Za-z0-9_]+", text.lower())
        cjk_tokens = re.findall(r"[\u4e00-\u9fff]{1,6}", text)
        return ascii_tokens + cjk_tokens

    def embed_text(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        tokens = self._tokenize(text)
        if not tokens:
            return vec
        for token in tokens:
            digest = blake2b(token.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest, byteorder="little") % self.dim
            vec[bucket] += 1.0
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0:
            return vec
        return [v / norm for v in vec]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_text(text) for text in texts]


class OpenAIEmbedder:
    def __init__(
        self,
        api_key: str,
        model: str,
        dim: int = 1536,
        base_url: str | None = None,
    ):
        try:
            from openai import OpenAI  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "openai package is required for OpenAI embeddings. Install with `pip install openai`."
            ) from exc
        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self.client = OpenAI(**kwargs)
        self.model = model
        self.dim = dim

    def embed_text(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        resp = self.client.embeddings.create(model=self.model, input=texts)
        data = list(getattr(resp, "data", []) or [])
        # Preserve input order if the API provides explicit indices.
        try:
            data.sort(key=lambda item: int(getattr(item, "index", 0)))
        except Exception:
            pass
        embeddings: list[list[float]] = []
        for item in data:
            vec = getattr(item, "embedding", None)
            embeddings.append([float(x) for x in (vec or [])])
        return embeddings
