from __future__ import annotations

from dataclasses import dataclass
import re

INSUFFICIENT = "INSUFFICIENT"

_CN_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000}


def _normalize_text(text: str) -> str:
    out = text
    out = out.replace("．", ".").replace("。", ".").replace("·", ".")
    out = out.replace("－", "-").replace("—", "-").replace("–", "-")
    out = out.replace("：", ":").replace("，", ",")
    out = out.replace("（", "(").replace("）", ")")
    out = re.sub(r"\s+", " ", out).strip()
    return out


def cn_to_int(value: str) -> int | None:
    value = value.strip()
    if not value:
        return None
    if value.isdigit():
        return int(value)
    if value in _CN_DIGITS:
        return _CN_DIGITS[value]

    total = 0
    current = 0
    last_unit = 1
    for ch in value:
        if ch in _CN_DIGITS:
            current = _CN_DIGITS[ch]
            continue
        if ch in _CN_UNITS:
            unit = _CN_UNITS[ch]
            if current == 0:
                current = 1
            total += current * unit
            current = 0
            last_unit = unit
            continue
        return None

    # Handle trailing digit.
    total += current

    # "十二" -> 12, "十" -> 10 logic when no leading numeral.
    if total == 0 and "十" in value:
        return 10
    if total < 10 and "十" in value and last_unit == 10:
        return total + 10
    return total if total > 0 else None


def normalize_section_id(candidate: str) -> str | None:
    if not candidate:
        return None
    text = _normalize_text(candidate).replace("-", ".")
    text = re.sub(r"\.+", ".", text).strip(".")
    if re.fullmatch(r"\d+(?:\.\d+)*", text):
        return text
    return None


def _extract_numeric_path(query: str) -> str | None:
    # Multi-level path has highest priority.
    hit = re.search(r"(?<!\d)(\d+(?:[.\-]\d+)+)(?!\d)", query)
    if hit:
        return normalize_section_id(hit.group(1))
    return None


def _extract_chapter_chain(query: str) -> str | None:
    chapter_match = re.search(r"第\s*([一二三四五六七八九十百零两\d]+)\s*章", query)
    section_match = re.search(r"第\s*([一二三四五六七八九十百零两\d]+)\s*节", query)
    subsection_match = re.search(r"第\s*([一二三四五六七八九十百零两\d]+)\s*小节", query)

    chapter = cn_to_int(chapter_match.group(1)) if chapter_match else None
    section = cn_to_int(section_match.group(1)) if section_match else None
    subsection = cn_to_int(subsection_match.group(1)) if subsection_match else None

    if chapter is None and section is not None:
        # No dialog history, "第一节" alone is ambiguous.
        return None
    if chapter is None:
        return None
    if section is None:
        return str(chapter)
    if subsection is None:
        return f"{chapter}.{section}"
    return f"{chapter}.{section}.{subsection}"


def _extract_simple_chapter(query: str) -> str | None:
    hit = re.search(r"第\s*([一二三四五六七八九十百零两\d]+)\s*(章|篇)", query)
    if not hit:
        return None
    num = cn_to_int(hit.group(1))
    if num is None:
        return None
    return str(num)


def _chapter0_mapping(query: str) -> str | None:
    q = query.lower()
    if "abstract" in q or "摘要" in query:
        return "0.1"
    if any(word in query for word in ("前言", "序言", "preface", "序")):
        return "0.2"
    if any(word in query for word in ("引言", "导言", "introduction")):
        return "0.3"
    return None


@dataclass(slots=True)
class AnchorParseResult:
    section_id: str
    reason: str


def parse_anchor_to_section_id(query: str) -> AnchorParseResult:
    raw = _normalize_text(query)
    chapter0 = _chapter0_mapping(raw)
    if chapter0:
        return AnchorParseResult(section_id=chapter0, reason="chapter0_keyword")

    numeric_path = _extract_numeric_path(raw)
    if numeric_path:
        return AnchorParseResult(section_id=numeric_path, reason="explicit_numeric_path")

    chapter_chain = _extract_chapter_chain(raw)
    if chapter_chain:
        return AnchorParseResult(section_id=chapter_chain, reason="chapter_chain")

    simple_chapter = _extract_simple_chapter(raw)
    if simple_chapter:
        return AnchorParseResult(section_id=simple_chapter, reason="chapter_only")

    if re.search(r"[\(（][一二三四五六七八九十]+[\)）]", raw):
        return AnchorParseResult(section_id=INSUFFICIENT, reason="ambiguous_cn_prefix")

    if re.search(r"\b第\s*[一二三四五六七八九十百零两\d]+\s*节\b", raw):
        return AnchorParseResult(section_id=INSUFFICIENT, reason="section_without_chapter")

    return AnchorParseResult(section_id=INSUFFICIENT, reason="missing_anchor")
