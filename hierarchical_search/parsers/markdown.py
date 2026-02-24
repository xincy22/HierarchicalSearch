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
class ParsedSection:
    section_id: str
    level: int
    title_text: str
    body_text: str
    heading_raw: str | None
    heading_prefix_raw: str | None
    start_pos: int | None
    end_pos: int | None
    l1_title: str
    l2_title: str
    l3_title: str


@dataclass(slots=True)
class _Heading:
    line_no: int
    level: int
    heading_raw: str
    heading_prefix_raw: str | None
    title_text: str


def _chapter0_id_from_marker(marker: str) -> str | None:
    m = marker.lower()
    if m in {"摘要", "abstract"}:
        return "0.1"
    if m in {"前言", "序言", "preface"}:
        return "0.2"
    if m in {"引言", "导言", "introduction"}:
        return "0.3"
    return None


def _split_heading_prefix(text: str, allow_atx_single_dot: bool = False) -> tuple[str | None, str]:
    stripped = text.strip()
    m = _ATX_NUMERIC_PREFIX.match(stripped) if allow_atx_single_dot else _NUMERIC_PREFIX.match(
        stripped
    )
    if m:
        prefix = m.group("prefix")
        title = m.group("title").strip()
        return prefix, title
    m = _CHAPTER_PREFIX.match(stripped)
    if m:
        prefix = m.group("prefix")
        title = m.group("title").strip() or prefix
        return prefix, title
    return None, stripped


def _extract_explicit_section_id(prefix: str | None) -> str | None:
    if not prefix:
        return None
    normalized = normalize_section_id(prefix)
    if normalized:
        return normalized
    m = re.match(r"第([一二三四五六七八九十百零两\d]+)(章|篇|节)", prefix)
    if m:
        number = cn_to_int(m.group(1))
        if number is not None:
            return str(number)
    return None


def _make_unique(section_id: str, used_ids: set[str]) -> str:
    if section_id not in used_ids:
        return section_id
    parts = [int(p) for p in section_id.split(".")]
    while True:
        parts[-1] += 1
        candidate = ".".join(str(p) for p in parts)
        if candidate not in used_ids:
            return candidate


def _collect_headings(lines: list[str]) -> list[_Heading]:
    headings: list[_Heading] = []
    for idx, line in enumerate(lines):
        atx = _ATX_HEADING.match(line)
        if atx:
            raw = atx.group(2).strip()
            prefix, title = _split_heading_prefix(raw, allow_atx_single_dot=True)
            headings.append(
                _Heading(
                    line_no=idx,
                    level=min(len(atx.group(1)), 3),
                    heading_raw=raw,
                    heading_prefix_raw=prefix,
                    title_text=title,
                )
            )
            continue

        stripped = line.strip()
        if not stripped:
            continue
        if len(stripped) > 80:
            continue
        if re.search(r"[。！？?!]", stripped):
            continue
        prefix, title = _split_heading_prefix(stripped)
        if prefix is None:
            continue
        if re.match(r"^\d+[)\.]\s+", stripped):
            if title.strip().startswith(("**", "`", "[")):
                continue

        level = 1
        maybe_path = normalize_section_id(prefix)
        if maybe_path:
            level = min(maybe_path.count(".") + 1, 3)
        headings.append(
            _Heading(
                line_no=idx,
                level=level,
                heading_raw=stripped,
                heading_prefix_raw=prefix,
                title_text=title,
            )
        )
    return headings


def _parse_chapter0(lines: list[str], first_heading_line: int | None) -> list[ParsedSection]:
    end = first_heading_line if first_heading_line is not None else len(lines)
    if end <= 0:
        return []
    window = lines[:end]
    if not any(line.strip() for line in window):
        return []

    marker_positions: list[tuple[int, str]] = []
    for idx, line in enumerate(window):
        m = _MARKER_LINE.match(line)
        if m:
            marker_positions.append((idx, m.group("marker")))

    sections: list[ParsedSection] = []
    if marker_positions:
        for pos_i, (start_idx, marker) in enumerate(marker_positions):
            stop_idx = marker_positions[pos_i + 1][0] if pos_i + 1 < len(marker_positions) else end
            section_id = _chapter0_id_from_marker(marker)
            if not section_id:
                continue
            body_lines = lines[start_idx + 1 : stop_idx]
            body = "\n".join(body_lines).strip()
            sections.append(
                ParsedSection(
                    section_id=section_id,
                    level=2,
                    title_text=marker,
                    body_text=body,
                    heading_raw=marker,
                    heading_prefix_raw=None,
                    start_pos=start_idx + 1,
                    end_pos=stop_idx,
                    l1_title="Chapter 0",
                    l2_title=marker,
                    l3_title="",
                )
            )
        return sections

    whole_text = "\n".join(window).strip()
    if not whole_text:
        return []

    lowered = whole_text.lower()
    if "abstract" in lowered or "摘要" in whole_text:
        sid, title = "0.1", "摘要"
    elif any(k in whole_text for k in ("前言", "序言")) or "preface" in lowered:
        sid, title = "0.2", "前言"
    elif any(k in whole_text for k in ("引言", "导言")) or "introduction" in lowered:
        sid, title = "0.3", "引言"
    else:
        return []

    return [
        ParsedSection(
            section_id=sid,
            level=2,
            title_text=title,
            body_text=whole_text,
            heading_raw=title,
            heading_prefix_raw=None,
            start_pos=1,
            end_pos=end,
            l1_title="Chapter 0",
            l2_title=title,
            l3_title="",
        )
    ]


class MarkdownSectionParser:
    def parse(self, markdown: str) -> list[ParsedSection]:
        lines = markdown.splitlines()
        headings = _collect_headings(lines)
        if (
            headings
            and headings[0].line_no <= 2
            and headings[0].level == 1
            and headings[0].heading_prefix_raw is None
            and any(_extract_explicit_section_id(h.heading_prefix_raw) for h in headings[1:])
        ):
            # Treat leading unnumbered H1 as document title, not retrievable section.
            headings = headings[1:]
        first_heading_line = headings[0].line_no if headings else None

        chapter0_sections = _parse_chapter0(lines, first_heading_line)

        parsed: list[ParsedSection] = []
        if not headings:
            return chapter0_sections

        used_ids = {s.section_id for s in chapter0_sections}
        counters = [0, 0, 0, 0, 0, 0]
        title_stack: dict[int, str] = {}

        assigned_ids: list[str] = []
        levels: list[int] = []
        for heading in headings:
            explicit = _extract_explicit_section_id(heading.heading_prefix_raw)
            if explicit:
                candidate = explicit
                level = candidate.count(".") + 1
                parts = [int(p) for p in candidate.split(".")]
                for idx, value in enumerate(parts):
                    counters[idx] = value
                for idx in range(len(parts), len(counters)):
                    counters[idx] = 0
            else:
                level = max(1, min(heading.level, 3))
                parent_idx = level - 2
                if parent_idx >= 0 and counters[parent_idx] == 0:
                    counters[parent_idx] = 1
                counters[level - 1] += 1
                for idx in range(level, len(counters)):
                    counters[idx] = 0
                parts = counters[:level]
                candidate = ".".join(str(v) for v in parts)

            candidate = _make_unique(candidate, used_ids)
            used_ids.add(candidate)
            assigned_ids.append(candidate)
            levels.append(level)

        for i, heading in enumerate(headings):
            section_id = assigned_ids[i]
            level = levels[i]

            title_stack[level] = heading.title_text
            for deep in list(title_stack.keys()):
                if deep > level:
                    title_stack.pop(deep)

            start_line = heading.line_no + 1
            end_line = (
                headings[i + 1].line_no if i + 1 < len(headings) else len(lines)
            )
            body = "\n".join(lines[start_line:end_line]).strip()

            parsed.append(
                ParsedSection(
                    section_id=section_id,
                    level=level,
                    title_text=heading.title_text,
                    body_text=body,
                    heading_raw=heading.heading_raw,
                    heading_prefix_raw=heading.heading_prefix_raw,
                    start_pos=start_line + 1,
                    end_pos=end_line,
                    l1_title=title_stack.get(1, heading.title_text if level == 1 else ""),
                    l2_title=title_stack.get(2, heading.title_text if level == 2 else ""),
                    l3_title=title_stack.get(3, heading.title_text if level == 3 else ""),
                )
            )

        return chapter0_sections + parsed
