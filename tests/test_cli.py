"""CLI 集成测试：ingest 和 query 应能跨进程边界（以子进程模拟）使用，demo 同进程。"""

from __future__ import annotations

import json

from hierarchical_search.cli import main


def _run_main(argv):
    return main(argv)


def test_demo_command_same_process(tmp_path, capsys):
    sample = tmp_path / "sample.md"
    sample.write_text(
        "# 1 相关工作\n相关工作\n\n# 2 方法\n方法\n\n## 2.1 实验设置\n实验设置正文\n",
        encoding="utf-8",
    )
    db = tmp_path / "demo.db"
    rc = _run_main(["--db", str(db), "demo", str(sample), "sample 2.1 讲了什么"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["found"] is True
    assert out["section_id"] == "2.1"


def test_ingest_then_query_separate_invocations(tmp_path, capsys):
    sample = tmp_path / "sample.md"
    sample.write_text(
        "# 1 相关工作\n相关工作\n\n# 2 方法\n方法\n\n## 2.1 实验设置\n实验设置正文\n",
        encoding="utf-8",
    )
    db = tmp_path / "hs.db"

    rc = _run_main(["--db", str(db), "ingest", str(sample)])
    assert rc == 0
    capsys.readouterr()  # drain

    # 关键：模拟"另一次 main 调用"，向量必须从 SQLite 恢复
    rc = _run_main(["--db", str(db), "query", "sample 2.1 讲了什么"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["found"] is True
    assert out["section_id"] == "2.1"
    assert out["section_method"] == "anchor_exact"


def test_query_on_empty_db_does_not_crash(tmp_path, capsys):
    db = tmp_path / "empty.db"
    rc = _run_main(["--db", str(db), "init-db"])
    assert rc == 0
    capsys.readouterr()
    rc = _run_main(["--db", str(db), "query", "随便问点什么"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["found"] is False
    assert out["reject_reason"] == "no_doc_vectors"
