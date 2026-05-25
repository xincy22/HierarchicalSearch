from hierarchical_search.parsing.markdown import parse_markdown


def test_generates_stable_section_ids():
    text = """摘要
这是文档摘要。

# 1 概述
概述正文。

## 1.1 背景
背景正文。

# 2 方法
方法正文。

## 2.1 实验设置
实验设置正文。
"""
    sections = parse_markdown(text)
    ids = [s.section_id for s in sections]
    assert ids == ["0.1", "1", "1.1", "2", "2.1"]

    sec = {s.section_id: s for s in sections}
    assert "摘要" in sec["0.1"].title_text
    assert "概述正文" in sec["1"].body_text
    assert "实验设置正文" in sec["2.1"].body_text


def test_atx_chapter0_abstract_recognized():
    text = """# 摘要
这是文档摘要。

# 1 概述
概述正文。

# 2 方法
方法正文。
"""
    sections = parse_markdown(text)
    sec = {s.section_id: s for s in sections}
    assert "0.1" in sec
    assert "这是文档摘要" in sec["0.1"].body_text
    # 摘要不应该被当成"无编号文档标题"丢弃
    assert [s.section_id for s in sections] == ["0.1", "1", "2"]


def test_atx_chapter0_english():
    text = """# Abstract
We propose a method.

# Introduction
Background here.

# 1 Method
Details.
"""
    sections = parse_markdown(text)
    ids = [s.section_id for s in sections]
    assert "0.1" in ids
    assert "0.3" in ids
    assert "1" in ids


def test_unnumbered_doc_title_still_skipped():
    # 回归：无编号 H1 + 后续编号 H1 时，文档标题应被跳过
    text = """# 我的论文

# 1 引言
引言正文

# 2 方法
方法正文
"""
    sections = parse_markdown(text)
    ids = [s.section_id for s in sections]
    assert ids == ["1", "2"]
