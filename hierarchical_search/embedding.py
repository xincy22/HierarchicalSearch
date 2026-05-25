"""Hash-based embedding for local dev. No external dependencies."""

from __future__ import annotations

from hashlib import blake2b
import math
import re


class HashingEmbedder:
    def __init__(self, dim: int = 384):
        self.dim = dim

    def _tokenize(self, text: str) -> list[str]:
        ascii_tokens = re.findall(r"[A-Za-z0-9_]+", text.lower())
        cjk_tokens = re.findall(r"[\u4e00-\u9fff]{1,6}", text)
        return ascii_tokens + cjk_tokens

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for token in self._tokenize(text):
            digest = blake2b(token.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest, byteorder="little") % self.dim
            vec[bucket] += 1.0
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0:
            return vec
        return [v / norm for v in vec]

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]
