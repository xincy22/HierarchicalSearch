"""锚点解析：从 query 中提取 section_id 或返回 INSUFFICIENT。

策略：宁可 INSUFFICIENT 也不硬猜。
"""

from __future__ import annotations

import re

INSUFFICIENT = "INSUFFICIENT"

_CN_DIGITS = {
    "零": 0, "〇": 0, "一": 1, "二": 2, "两": 2,
    "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000}


def _normalize_text(text: str) -> str:
    out = text
    out = out.replace("．", ".").replace("。", ".").replace("·", ".")
    out = out.replace("－", "-").replace("—", "-").replace("–", "-")
    out = out.replace("：", ":").replace("，", ",")
    out = out.replace("（", "(").replace("）", ")")
    return re.sub(r"\s+", " ", out).strip()


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
        elif ch in _CN_UNITS:
            unit = _CN_UNITS[ch]
            if current == 0:
                current = 1
            total += current * unit
            current = 0
            last_unit = unit
        else:
            return None

    total += current
    if total == 0 and "十" in value:
        return 10
    if total < 10 and "十" in value and last_unit == 10:
        return total + 10
    return total if total > 0 else None


def normalize_section_id(candidate: str) -> str | None:
    """归一化为 '1.2.3' 格式，失败返回 None。"""
    if not candidate:
        return None
    text = _normalize_text(candidate).replace("-", ".")
    text = re.sub(r"\.+", ".", text).strip(".")
    if re.fullmatch(r"\d+(?:\.\d+)*", text):
        return text
    return None


def parse_anchor(query: str) -> str:
    """从 query 解析 section_id，无法确定时返回 INSUFFICIENT。"""
    raw = _normalize_text(query)

    # Chapter 0 关键词。英文统一在小写串里匹配，避免大小写不一致。
    # 注意：单字 "序" 容易误伤"顺序/序列/程序"等，故只接受双字关键词。
    q = raw.lower()
    if "abstract" in q or "摘要" in raw:
        return "0.1"
    if "preface" in q or any(w in raw for w in ("前言", "序言")):
        return "0.2"
    if "introduction" in q or any(w in raw for w in ("引言", "导言")):
        return "0.3"

    # 显式数字路径：2.1, 3.2.1
    hit = re.search(r"(?<!\d)(\d+(?:[.\-]\d+)+)(?!\d)", raw)
    if hit:
        result = normalize_section_id(hit.group(1))
        if result:
            return result

    # 第X章第Y节第Z小节
    chapter_m = re.search(r"第\s*([一二三四五六七八九十百零两\d]+)\s*章", raw)
    section_m = re.search(r"第\s*([一二三四五六七八九十百零两\d]+)\s*节", raw)
    subsection_m = re.search(r"第\s*([一二三四五六七八九十百零两\d]+)\s*小节", raw)

    chapter = cn_to_int(chapter_m.group(1)) if chapter_m else None
    section = cn_to_int(section_m.group(1)) if section_m else None
    subsection = cn_to_int(subsection_m.group(1)) if subsection_m else None

    if chapter is not None:
        if section is None:
            return str(chapter)
        if subsection is None:
            return f"{chapter}.{section}"
        return f"{chapter}.{section}.{subsection}"

    # 第X章/篇（无"节"）
    hit = re.search(r"第\s*([一二三四五六七八九十百零两\d]+)\s*(章|篇)", raw)
    if hit:
        num = cn_to_int(hit.group(1))
        if num is not None:
            return str(num)

    # 歧义情况 → INSUFFICIENT
    return INSUFFICIENT
