"""Markdown 章节解析：切分标题 + 固化 section_id。"""

from __future__ import annotations

from dataclasses import dataclass
import re

from .anchor import cn_to_int, normalize_section_id

_ATX_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*$")
_NUMERIC_PREFIX = re.compile(
    r"^\s*(?P<prefix>\d+(?:[.\-]\d+)*)\s*(?:[)\]、:：\-]|\s)\s*(?P<title>.+)$"
)
_ATX_NUMERIC_PREFIX = re.compile(
    r"^\s*(?P<prefix>\d+(?:[.\-]\d+)*)(?:\.)?\s*(?:[)\]、:：\-]|\s)\s*(?P<title>.+)$"
)
_CHAPTER_PREFIX = re.compile(
    r"^\s*(?P<prefix>第[一二三四五六七八九十百零两\d]+(?:章|节|篇))\s*(?P<title>.*)$"
)
_MARKER_LINE = re.compile(
    r"^\s*(?P<marker>摘要|abstract|前言|序言|preface|引言|导言|introduction)\s*$",
    re.IGNORECASE,
)


@dataclass(slots=True)
class Section:
    section_id: str
    level: int
    title_text: str
    body_text: str
    l1_title: str
    l2_title: str
    l3_title: str


# --- internal helpers ---


@dataclass(slots=True)
class _Heading:
    line_no: int
    level: int
    raw: str
    prefix: str | None
    title: str


def _split_prefix(text: str, atx: bool = False) -> tuple[str | None, str]:
    stripped = text.strip()
    pattern = _ATX_NUMERIC_PREFIX if atx else _NUMERIC_PREFIX
    m = pattern.match(stripped)
    if m:
        return m.group("prefix"), m.group("title").strip()
    m = _CHAPTER_PREFIX.match(stripped)
    if m:
        return m.group("prefix"), m.group("title").strip() or m.group("prefix")
    return None, stripped


def _prefix_to_section_id(prefix: str | None) -> str | None:
    if not prefix:
        return None
    normalized = normalize_section_id(prefix)
    if normalized:
        return normalized
    m = re.match(r"第([一二三四五六七八九十百零两\d]+)(章|篇|节)", prefix)
    if m:
        num = cn_to_int(m.group(1))
        if num is not None:
            return str(num)
    return None


def _make_unique(section_id: str, used: set[str]) -> str:
    if section_id not in used:
        return section_id
    parts = [int(p) for p in section_id.split(".")]
    while True:
        parts[-1] += 1
        candidate = ".".join(str(p) for p in parts)
        if candidate not in used:
            return candidate


def _collect_headings(lines: list[str]) -> list[_Heading]:
    headings: list[_Heading] = []
    for idx, line in enumerate(lines):
        atx = _ATX_HEADING.match(line)
        if atx:
            raw = atx.group(2).strip()
            prefix, title = _split_prefix(raw, atx=True)
            headings.append(_Heading(idx, min(len(atx.group(1)), 3), raw, prefix, title))
            continue
        stripped = line.strip()
        if not stripped or len(stripped) > 80 or re.search(r"[。！？?!]", stripped):
            continue
        prefix, title = _split_prefix(stripped)
        if prefix is None:
            continue
        level = 1
        maybe_path = normalize_section_id(prefix)
        if maybe_path:
            level = min(maybe_path.count(".") + 1, 3)
        headings.append(_Heading(idx, level, stripped, prefix, title))
    return headings


def _chapter0_id(marker: str) -> str | None:
    m = marker.lower()
    if m in {"摘要", "abstract"}:
        return "0.1"
    if m in {"前言", "序言", "preface"}:
        return "0.2"
    if m in {"引言", "导言", "introduction"}:
        return "0.3"
    return None


def _parse_chapter0(lines: list[str], first_heading_line: int | None) -> list[Section]:
    end = first_heading_line if first_heading_line is not None else len(lines)
    if end <= 0:
        return []
    window = lines[:end]
    if not any(line.strip() for line in window):
        return []

    # 按 marker 行切分
    markers: list[tuple[int, str]] = []
    for idx, line in enumerate(window):
        m = _MARKER_LINE.match(line)
        if m:
            markers.append((idx, m.group("marker")))

    sections: list[Section] = []
    if markers:
        for i, (start, marker) in enumerate(markers):
            stop = markers[i + 1][0] if i + 1 < len(markers) else end
            sid = _chapter0_id(marker)
            if not sid:
                continue
            body = "\n".join(lines[start + 1 : stop]).strip()
            sections.append(Section(sid, 2, marker, body, "Chapter 0", marker, ""))
        return sections

    # 整块识别
    whole = "\n".join(window).strip()
    if not whole:
        return []
    low = whole.lower()
    if "abstract" in low or "摘要" in whole:
        return [Section("0.1", 2, "摘要", whole, "Chapter 0", "摘要", "")]
    if any(k in whole for k in ("前言", "序言")) or "preface" in low:
        return [Section("0.2", 2, "前言", whole, "Chapter 0", "前言", "")]
    if any(k in whole for k in ("引言", "导言")) or "introduction" in low:
        return [Section("0.3", 2, "引言", whole, "Chapter 0", "引言", "")]
    return []


# --- public API ---


def parse_markdown(markdown: str) -> list[Section]:
    """解析 markdown 为 Section 列表，固化 section_id。"""
    lines = markdown.splitlines()
    headings = _collect_headings(lines)

    # ATX 风格 Chapter 0：开头连续的无编号 marker heading（# 摘要 / # Abstract / ...）
    # 直接识别为 0.x，避免被后续"丢弃文档标题"的启发式吞掉。
    atx_chapter0: list[Section] = []
    while headings:
        h = headings[0]
        if h.prefix is not None:
            break
        sid = _chapter0_id(h.title)
        if not sid:
            break
        start = h.line_no + 1
        end = headings[1].line_no if len(headings) > 1 else len(lines)
        body = "\n".join(lines[start:end]).strip()
        atx_chapter0.append(
            Section(sid, 2, h.title, body, "Chapter 0", h.title, "")
        )
        headings = headings[1:]

    # 如果第一个 H1 是无编号的文档标题，跳过它（line_no 不再要求 <=2，
    # 因为 ATX Chapter 0 抽取后剩余 heading 的行号可能很靠后）
    if (
        headings
        and headings[0].level == 1
        and headings[0].prefix is None
        and any(_prefix_to_section_id(h.prefix) for h in headings[1:])
    ):
        headings = headings[1:]

    # 纯文本 Chapter 0 仅在 ATX 路径未识别时走（避免重复）
    first_line = headings[0].line_no if headings else None
    chapter0 = atx_chapter0 if atx_chapter0 else _parse_chapter0(lines, first_line)

    if not headings:
        return chapter0

    # 分配 section_id
    used = {s.section_id for s in chapter0}
    counters = [0, 0, 0, 0, 0, 0]
    assigned: list[tuple[str, int]] = []

    for h in headings:
        explicit = _prefix_to_section_id(h.prefix)
        if explicit:
            level = explicit.count(".") + 1
            parts = [int(p) for p in explicit.split(".")]
            for i, v in enumerate(parts):
                counters[i] = v
            for i in range(len(parts), len(counters)):
                counters[i] = 0
            candidate = explicit
        else:
            level = max(1, min(h.level, 3))
            if level >= 2 and counters[level - 2] == 0:
                counters[level - 2] = 1
            counters[level - 1] += 1
            for i in range(level, len(counters)):
                counters[i] = 0
            candidate = ".".join(str(v) for v in counters[:level])

        candidate = _make_unique(candidate, used)
        used.add(candidate)
        assigned.append((candidate, level))

    # 构建 Section 列表
    title_stack: dict[int, str] = {}
    sections: list[Section] = []

    for i, h in enumerate(headings):
        sid, level = assigned[i]
        title_stack[level] = h.title
        for deep in list(title_stack):
            if deep > level:
                del title_stack[deep]

        start = h.line_no + 1
        end = headings[i + 1].line_no if i + 1 < len(headings) else len(lines)
        body = "\n".join(lines[start:end]).strip()

        sections.append(Section(
            section_id=sid,
            level=level,
            title_text=h.title,
            body_text=body,
            l1_title=title_stack.get(1, h.title if level == 1 else ""),
            l2_title=title_stack.get(2, h.title if level == 2 else ""),
            l3_title=title_stack.get(3, h.title if level == 3 else ""),
        ))

    return chapter0 + sections
