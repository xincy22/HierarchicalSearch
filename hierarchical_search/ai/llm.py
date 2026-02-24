from __future__ import annotations

from dataclasses import dataclass
from dataclasses import asdict
import json
import re
from typing import Protocol

from ..parsers.anchor import INSUFFICIENT, parse_anchor_to_section_id
from .prompts import PromptCatalog


class LLMClient(Protocol):
    def extract_topic(self, text: str, filename: str) -> str:
        ...

    def generate_aliases(
        self, filename: str, file_topic: str, doc_title: str | None, max_aliases: int = 8
    ) -> list[str]:
        ...

    def resolve_section_id(self, query: str) -> str:
        ...

    def rerank_doc_candidates(
        self, query: str, candidates: list["DocCandidate"]
    ) -> list["DocCandidate"]:
        ...

    def rerank_section_candidates(
        self, query: str, candidates: list["SectionCandidate"]
    ) -> list["SectionCandidate"]:
        ...


@dataclass(slots=True)
class DocCandidate:
    doc_id: int
    score: float
    notes: str = ""


@dataclass(slots=True)
class SectionCandidate:
    section_id: str
    score: float
    notes: str = ""


class RuleBasedLLMClient:
    @staticmethod
    def _tokenize(text: str) -> set[str]:
        tokens: set[str] = set(re.findall(r"[A-Za-z0-9_]+", text.lower()))
        for chunk in re.findall(r"[\u4e00-\u9fff]+", text):
            if not chunk:
                continue
            tokens.add(chunk)
            if len(chunk) == 1:
                tokens.add(chunk)
                continue
            for i in range(len(chunk)):
                tokens.add(chunk[i])
            for i in range(len(chunk) - 1):
                tokens.add(chunk[i : i + 2])
        return {x for x in tokens if x}

    def _lexical_overlap(self, query: str, candidate_text: str) -> int:
        q_tokens = self._tokenize(query)
        c_tokens = self._tokenize(candidate_text)
        if not q_tokens or not c_tokens:
            return 0
        return len(q_tokens & c_tokens)

    def extract_topic(self, text: str, filename: str) -> str:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return filename
        first_heading = next((line for line in lines if line.startswith("#")), None)
        if first_heading:
            return first_heading.lstrip("#").strip()[:120]
        return lines[0][:120]

    def generate_aliases(
        self, filename: str, file_topic: str, doc_title: str | None, max_aliases: int = 8
    ) -> list[str]:
        base = [filename, file_topic, doc_title or ""]
        tokens: list[str] = []
        for text in base:
            for token in re.split(r"[\s_\-./|，,：:]+", text):
                token = token.strip()
                if len(token) >= 2:
                    tokens.append(token)
        dedup: list[str] = []
        seen: set[str] = set()
        for token in tokens:
            low = token.lower()
            if low in seen:
                continue
            seen.add(low)
            dedup.append(token)
            if len(dedup) >= max_aliases:
                break
        return dedup

    def resolve_section_id(self, query: str) -> str:
        return parse_anchor_to_section_id(query).section_id

    def rerank_doc_candidates(
        self, query: str, candidates: list[DocCandidate]
    ) -> list[DocCandidate]:
        return sorted(
            candidates,
            key=lambda x: (self._lexical_overlap(query, x.notes), x.score),
            reverse=True,
        )

    def rerank_section_candidates(
        self, query: str, candidates: list[SectionCandidate]
    ) -> list[SectionCandidate]:
        return sorted(
            candidates,
            key=lambda x: (self._lexical_overlap(query, x.notes), x.score),
            reverse=True,
        )


class OpenAILLMClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str | None = None,
        prompt_file: str | None = None,
    ):
        try:
            from openai import OpenAI  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "openai package is required for OpenAI LLM backend. Install with `pip install openai`."
            ) from exc

        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self.client = OpenAI(**kwargs)
        self.model = model
        self.prompts = PromptCatalog(prompt_file)
        self._fallback = RuleBasedLLMClient()
        self._prefer_chat = "bigmodel.cn" in (base_url or "").lower()
        self._remote_available = True
        self.stats: dict[str, int] = {
            "ask_total": 0,
            "responses_calls": 0,
            "chat_calls": 0,
            "responses_failures": 0,
            "chat_failures": 0,
            "remote_short_circuit": 0,
        }

    @staticmethod
    def _is_transport_unsupported(exc: Exception) -> bool:
        name = exc.__class__.__name__.lower()
        msg = str(exc).lower()
        if "notfound" in name:
            return True
        if "404" in msg and "not found" in msg:
            return True
        if "/responses" in msg and "404" in msg:
            return True
        return False

    @staticmethod
    def _is_rate_limited(exc: Exception) -> bool:
        name = exc.__class__.__name__.lower()
        msg = str(exc).lower()
        if "ratelimit" in name:
            return True
        if "rate limit" in msg or "速率限制" in msg:
            return True
        return False

    @staticmethod
    def _extract_chat_text(content: object) -> str:
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    if item.strip():
                        parts.append(item.strip())
                    continue
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str) and text.strip():
                        parts.append(text.strip())
                        continue
                    body = item.get("content")
                    if isinstance(body, str) and body.strip():
                        parts.append(body.strip())
                        continue
                text = getattr(item, "text", None)
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
            return "\n".join(parts).strip()
        return str(content).strip()

    def _ask_via_responses(self, system_prompt: str, user_prompt: str) -> str:
        self.stats["responses_calls"] += 1
        resp = self.client.responses.create(
            model=self.model,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0,
        )
        text = getattr(resp, "output_text", "")
        if isinstance(text, str):
            return text.strip()
        return str(text).strip()

    def _ask_via_chat(self, system_prompt: str, user_prompt: str) -> str:
        self.stats["chat_calls"] += 1
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0,
        )
        if not resp.choices:
            return ""
        return self._extract_chat_text(resp.choices[0].message.content)

    def _ask(self, system_prompt: str, user_prompt: str) -> str:
        if not self._remote_available:
            self.stats["remote_short_circuit"] += 1
            raise RuntimeError("remote_llm_disabled_after_rate_limit")
        self.stats["ask_total"] += 1
        primary_name = "chat" if self._prefer_chat else "responses"
        secondary_name = "responses" if self._prefer_chat else "chat"
        primary = self._ask_via_chat if primary_name == "chat" else self._ask_via_responses
        secondary = self._ask_via_chat if secondary_name == "chat" else self._ask_via_responses
        try:
            return primary(system_prompt, user_prompt)
        except Exception as first_exc:
            if primary_name == "responses":
                self.stats["responses_failures"] += 1
            else:
                self.stats["chat_failures"] += 1
            if self._is_rate_limited(first_exc):
                self._remote_available = False
                raise
            if not self._is_transport_unsupported(first_exc):
                raise
            try:
                text = secondary(system_prompt, user_prompt)
                # Lock the working transport to avoid repeating failed calls.
                self._prefer_chat = secondary_name == "chat"
                return text
            except Exception as second_exc:
                if secondary_name == "responses":
                    self.stats["responses_failures"] += 1
                else:
                    self.stats["chat_failures"] += 1
                if self._is_rate_limited(second_exc):
                    self._remote_available = False
                raise first_exc

    def extract_topic(self, text: str, filename: str) -> str:
        prompt = self.prompts.render(
            "openai",
            "extract_topic",
            "user_template",
            filename=filename,
            content=text[:4000],
        )
        try:
            out = self._ask(self.prompts.get("openai", "extract_topic", "system"), prompt)
            return out[:120] if out else self._fallback.extract_topic(text, filename)
        except Exception:
            return self._fallback.extract_topic(text, filename)

    def generate_aliases(
        self, filename: str, file_topic: str, doc_title: str | None, max_aliases: int = 8
    ) -> list[str]:
        prompt = self.prompts.render(
            "openai",
            "generate_aliases",
            "user_template",
            max_aliases=max_aliases,
            filename=filename,
            doc_title=doc_title or "",
            file_topic=file_topic,
        )
        try:
            out = self._ask(self.prompts.get("openai", "generate_aliases", "system"), prompt)
            aliases = json.loads(out)
            if isinstance(aliases, list):
                cleaned = [str(x).strip() for x in aliases if str(x).strip()]
                return cleaned[:max_aliases]
        except Exception:
            pass
        return self._fallback.generate_aliases(filename, file_topic, doc_title, max_aliases)

    def resolve_section_id(self, query: str) -> str:
        # Fast path: deterministic anchor parser covers explicit section patterns.
        parsed = self._fallback.resolve_section_id(query)
        if parsed != INSUFFICIENT:
            return parsed
        prompt = self.prompts.render(
            "openai", "resolve_section_id", "user_template", query=query
        )
        try:
            out = self._ask(self.prompts.get("openai", "resolve_section_id", "system"), prompt)
            data = json.loads(out)
            section_id = str(data.get("section_id", INSUFFICIENT))
            if section_id == INSUFFICIENT:
                return INSUFFICIENT
            if re.fullmatch(r"\d+(?:\.\d+)*", section_id):
                return section_id
        except Exception:
            pass
        return self._fallback.resolve_section_id(query)

    def rerank_doc_candidates(
        self, query: str, candidates: list[DocCandidate]
    ) -> list[DocCandidate]:
        if not candidates:
            return candidates
        prompt = {
            "query": query,
            "candidates": [asdict(c) for c in candidates],
            "instruction": self.prompts.get(
                "openai", "rerank_doc_candidates", "instruction"
            ),
        }
        try:
            out = self._ask(
                self.prompts.get("openai", "rerank_doc_candidates", "system"),
                json.dumps(prompt, ensure_ascii=False),
            )
            order = json.loads(out)
            if isinstance(order, list):
                idx = {c.doc_id: c for c in candidates}
                ranked = [idx[i] for i in order if i in idx]
                seen = {c.doc_id for c in ranked}
                ranked.extend(c for c in candidates if c.doc_id not in seen)
                return ranked
        except Exception:
            pass
        return self._fallback.rerank_doc_candidates(query, candidates)

    def rerank_section_candidates(
        self, query: str, candidates: list[SectionCandidate]
    ) -> list[SectionCandidate]:
        if not candidates:
            return candidates
        prompt = {
            "query": query,
            "candidates": [asdict(c) for c in candidates],
            "instruction": self.prompts.get(
                "openai", "rerank_section_candidates", "instruction"
            ),
        }
        try:
            out = self._ask(
                self.prompts.get("openai", "rerank_section_candidates", "system"),
                json.dumps(prompt, ensure_ascii=False),
            )
            order = json.loads(out)
            if isinstance(order, list):
                idx = {c.section_id: c for c in candidates}
                ranked = [idx[i] for i in order if i in idx]
                seen = {c.section_id for c in ranked}
                ranked.extend(c for c in candidates if c.section_id not in seen)
                return ranked
        except Exception:
            pass
        return self._fallback.rerank_section_candidates(query, candidates)
