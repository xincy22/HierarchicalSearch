from hierarchical_search.parsing.anchor import INSUFFICIENT, parse_anchor


def test_explicit_numeric_path():
    assert parse_anchor("请问 2-1 讲了什么？") == "2.1"


def test_chapter_chain():
    assert parse_anchor("第 3 章 第 2 节 第 1 小节讲了什么") == "3.2.1"


def test_chapter0_keywords():
    assert parse_anchor("摘要主要讲什么") == "0.1"
    assert parse_anchor("前言写了什么") == "0.2"
    assert parse_anchor("引言部分内容") == "0.3"


def test_ambiguous_returns_insufficient():
    assert parse_anchor("实验设置这一节讲了什么") == INSUFFICIENT
    assert parse_anchor("第一节讲了什么") == INSUFFICIENT
