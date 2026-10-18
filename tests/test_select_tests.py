"""tools/select_tests.py — コミットのときに回すテストの選び方。

選び方を間違えると、変わったのに重いテストを飛ばす (守っていない) か、
毎回全部回す (遅い) かのどちらか。
ここでは、変わったファイルごとに選ばれる重いテストを固定する。
"""

from __future__ import annotations

import subprocess
import sys
from typing import Any

import pytest
from conftest import ROOT

sys.path.insert(0, str(ROOT / "tools"))
import select_tests


def heavy(changed: list[str]) -> list[str]:
    chosen = select_tests.select(changed)
    return [p for p in chosen if select_tests.SELECTIVE.match(p.split("/")[-1])]


def test_documents_alone_run_no_heavy_test() -> None:
    """★文書だけの変更では重いテストを回さない (軽いテストは回す)。"""
    chosen = select_tests.select(["README.md", "docs/levers.md", ".claude/rules/experiments.md"])
    assert chosen != ["tests"]
    assert heavy(["README.md", "docs/levers.md"]) == []
    assert "tests/test_recorded_impls_frozen.py" in chosen
    assert "tests/test_select_tests.py" in chosen


def test_an_impl_change_runs_its_own_tests() -> None:
    """★実装を変えたら、その名前を本文に持つテストと, impl/ を丸ごと走査するテストを回す。"""
    got = heavy(["impl/38_precheck/animal_shogi.c"])
    assert "tests/test_impl_38_precheck.py" in got
    assert "tests/test_hot_layout_padding.py" in got
    assert "tests/test_impl_35_bitboard.py" not in got


def test_a_shared_helper_change_runs_every_importer() -> None:
    """★ほかのテストが import している道具のファイルを変えたら、
    それを (たどって) import するテストを全部回す。"""
    got = heavy(["tests/test_impl_34_unmove.py"])
    for n in ("34_unmove", "35_bitboard", "36_bb_unmove", "37_mirror1", "38_precheck"):
        assert f"tests/test_impl_{n}.py" in got
    assert "tests/test_impl_33_hot_layout.py" not in got
    assert "tests/test_hot_layout_padding.py" in got  # PAD_SIZES と padded を借りている


def test_an_experiment_change_runs_the_tests_that_name_it() -> None:
    """★実験のファイル (記録の実装が当てたパッチなど) を変えたら、それを名指しするテストを回す。"""
    assert heavy(["experiments/f1_select_catch/patches/precheck.patch"]) == [
        "tests/test_impl_38_precheck.py"
    ]


def test_a_tool_change_runs_the_tests_that_name_it() -> None:
    got = heavy(["tools/verify_log.py"])
    assert got and all("test_impl_" in p for p in got)


@pytest.mark.parametrize(
    "path",
    [
        "tests/conftest.py",
        "pyproject.toml",
        "uv.lock",
        "tools/select_tests.py",
        "baseline/animal_shogi.py",
        "oracle/totals.tsv",
        "src/new.c",
    ],
)
def test_the_foundations_or_unknown_places_run_everything(path: str) -> None:
    """★テストの土台・依存・選び方そのもの・答えを固定しているもの・分類できない場所が変わったら
    全部回す (安全側)。"""
    assert select_tests.select([path]) == ["tests"]


def test_a_changed_heavy_test_runs_itself() -> None:
    assert heavy(["tests/test_impl_10_setdiff.py"]) == ["tests/test_impl_10_setdiff.py"]


def test_every_heavy_test_is_reachable_from_a_change_of_itself() -> None:
    """★どの重いテストも, 自分のファイルが変われば選ばれる (選び方の形から外れたファイルが無い)。"""
    for p in sorted((ROOT / "tests").glob("test_*.py")):
        if select_tests.SELECTIVE.match(p.name):
            assert f"tests/{p.name}" in select_tests.select([f"tests/{p.name}"]), p.name


def test_the_light_set_is_small() -> None:
    """重くないテスト (毎回回す) が, 重いテストより少ないこと (選び方の形が崩れて全部が軽い側に
    落ちていないこと)。"""
    files = sorted(p.name for p in (ROOT / "tests").glob("test_*.py"))
    light = [f for f in files if not select_tests.SELECTIVE.match(f)]
    assert 0 < len(light) < len(files) - len(light)


def test_main_prints_the_selection(capsys: pytest.CaptureFixture[str]) -> None:
    assert select_tests.main(["README.md"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out == select_tests.select(["README.md"])


def test_main_staged_and_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """--staged は git の差分から選び, --run はそれで pytest を起動する (起動は差し替えて見る)。"""
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        if cmd[:2] == ["git", "diff"]:
            return subprocess.CompletedProcess(cmd, 0, "README.md\nimpl/38_precheck/Makefile\n", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert select_tests.main(["--staged", "--run", "--", "-q"]) == 0
    assert calls[0][:2] == ["git", "diff"]
    run = calls[1]
    assert run[1:4] == ["-m", "pytest", "-q"]
    assert "tests/test_impl_38_precheck.py" in run
    calls.clear()

    def fake_run_full(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        if cmd[:2] == ["git", "diff"]:
            return subprocess.CompletedProcess(cmd, 0, "uv.lock\n", "")
        return subprocess.CompletedProcess(cmd, 3, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run_full)
    assert select_tests.main(["--staged", "--run"]) == 3
    assert calls[1][-1] == "tests"


def test_staged_reads_git(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[list[str]] = []

    def fake_run(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "a.md\n\nb.md\n", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert select_tests.staged() == ["a.md", "b.md"]
    assert "--no-renames" in seen[0]
