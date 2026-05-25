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


def test_english_keywords_case_insensitive():
    # preface / introduction 之前只在 lower 串里匹配 abstract，导致这些大小写漏掉
    assert parse_anchor("Preface section explains") == "0.2"
    assert parse_anchor("INTRODUCTION mentions") == "0.3"


def test_single_char_xu_does_not_trigger_preface():
    # "序" 单字太宽，会误伤"顺序/序列/程序"等
    assert parse_anchor("讲讲顺序问题") == INSUFFICIENT
    assert parse_anchor("时间序列怎么处理") == INSUFFICIENT
    assert parse_anchor("程序入口在哪里") == INSUFFICIENT
