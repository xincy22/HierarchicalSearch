from hierarchical_search.parsers.anchor import INSUFFICIENT, parse_anchor_to_section_id


def test_explicit_numeric_path():
    result = parse_anchor_to_section_id("请问 2-1 讲了什么？")
    assert result.section_id == "2.1"


def test_chapter_chain():
    result = parse_anchor_to_section_id("第 3 章 第 2 节 第 1 小节讲了什么")
    assert result.section_id == "3.2.1"


def test_chapter0_keywords():
    assert parse_anchor_to_section_id("摘要主要讲什么").section_id == "0.1"
    assert parse_anchor_to_section_id("前言写了什么").section_id == "0.2"
    assert parse_anchor_to_section_id("引言部分内容").section_id == "0.3"


def test_ambiguous_cases_are_insufficient():
    assert parse_anchor_to_section_id("（一）实验设置讲了什么").section_id == INSUFFICIENT
    assert parse_anchor_to_section_id("第一节讲了什么").section_id == INSUFFICIENT
