from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import re
from typing import Protocol

from ..parsers.anchor import INSUFFICIENT, parse_anchor_to_section_id
from .prompts import PromptCatalog


class LLMClient(Protocol):
    def extract_topic(self, text: str, filename: str) -> str: ...
    def generate_aliases(
        self, filename: str, file_topic: str, doc_title: str | None, max_aliases: int = 8
    ) -> list[str]: ...
    def resolve_section_id(self, query: str) -> str: ...
    def rerank_doc_candidates(
        self, query: str, candidates: list["DocCandidate"]
    ) -> list["DocCandidate"]: ...
    def rerank_section_candidates(
        self, query: str, candidates: list["SectionCandidate"]
    ) -> list["SectionCandidate"]: ...


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
            tokens.add(chunk)
            for i in range(len(chunk) - 1):
                tokens.add(chunk[i : i + 2])
        return {x for x in tokens if x}

    def _lexical_overlap(self, query: str, candidate_text: str) -> int:
        return len(self._tokenize(query) & self._tokenize(candidate_text))

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
        tokens: list[str] = []
        for text in (filename, file_topic, doc_title or ""):
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
        from openai import OpenAI  # type: ignore

        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self.client = OpenAI(**kwargs)
        self.model = model
        self.prompts = PromptCatalog(prompt_file)

    def _ask(self, system_prompt: str, user_prompt: str) -> str:
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0,
        )
        return (resp.choices[0].message.content or "").strip()

    def extract_topic(self, text: str, filename: str) -> str:
        prompt = self.prompts.render(
            "openai", "extract_topic", "user_template",
            filename=filename, content=text[:4000],
        )
        return self._ask(self.prompts.get("openai", "extract_topic", "system"), prompt)[:120]

    def generate_aliases(
        self, filename: str, file_topic: str, doc_title: str | None, max_aliases: int = 8
    ) -> list[str]:
        prompt = self.prompts.render(
            "openai", "generate_aliases", "user_template",
            max_aliases=max_aliases, filename=filename,
            doc_title=doc_title or "", file_topic=file_topic,
        )
        out = self._ask(self.prompts.get("openai", "generate_aliases", "system"), prompt)
        aliases = json.loads(out)
        return [str(x).strip() for x in aliases if str(x).strip()][:max_aliases]

    def resolve_section_id(self, query: str) -> str:
        parsed = parse_anchor_to_section_id(query).section_id
        if parsed != INSUFFICIENT:
            return parsed
        prompt = self.prompts.render(
            "openai", "resolve_section_id", "user_template", query=query
        )
        out = self._ask(
            self.prompts.get("openai", "resolve_section_id", "system"), prompt
        )
        section_id = str(json.loads(out).get("section_id", INSUFFICIENT))
        if section_id != INSUFFICIENT and re.fullmatch(r"\d+(?:\.\d+)*", section_id):
            return section_id
        return INSUFFICIENT

    def rerank_doc_candidates(
        self, query: str, candidates: list[DocCandidate]
    ) -> list[DocCandidate]:
        if not candidates:
            return candidates
        payload = {
            "query": query,
            "candidates": [asdict(c) for c in candidates],
            "instruction": self.prompts.get(
                "openai", "rerank_doc_candidates", "instruction"
            ),
        }
        out = self._ask(
            self.prompts.get("openai", "rerank_doc_candidates", "system"),
            json.dumps(payload, ensure_ascii=False),
        )
        order = json.loads(out)
        idx = {c.doc_id: c for c in candidates}
        ranked = [idx[i] for i in order if i in idx]
        seen = {c.doc_id for c in ranked}
        ranked.extend(c for c in candidates if c.doc_id not in seen)
        return ranked

    def rerank_section_candidates(
        self, query: str, candidates: list[SectionCandidate]
    ) -> list[SectionCandidate]:
        if not candidates:
            return candidates
        payload = {
            "query": query,
            "candidates": [asdict(c) for c in candidates],
            "instruction": self.prompts.get(
                "openai", "rerank_section_candidates", "instruction"
            ),
        }
        out = self._ask(
            self.prompts.get("openai", "rerank_section_candidates", "system"),
            json.dumps(payload, ensure_ascii=False),
        )
        order = json.loads(out)
        idx = {c.section_id: c for c in candidates}
        ranked = [idx[i] for i in order if i in idx]
        seen = {c.section_id for c in ranked}
        ranked.extend(c for c in candidates if c.section_id not in seen)
        return ranked
