from hierarchical_search.parsers.markdown import MarkdownSectionParser


def test_markdown_parser_generates_stable_section_ids():
    parser = MarkdownSectionParser()
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
    sections = parser.parse(text)
    ids = [s.section_id for s in sections]
    assert ids == ["0.1", "1", "1.1", "2", "2.1"]

    sec = {s.section_id: s for s in sections}
    assert "摘要" in sec["0.1"].title_text
    assert "概述正文" in sec["1"].body_text
    assert "实验设置正文" in sec["2.1"].body_text
