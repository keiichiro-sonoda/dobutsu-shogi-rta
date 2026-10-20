"""tools/run_tests.py — テスト一式を, `.so` を読み込むテストのファイルごとに別のプロセスで回す。"""

from __future__ import annotations

import pathlib
import subprocess
from typing import Any

import pytest
import run_tests
from conftest import ROOT

LIGHT = "def test_ok():\n    assert True\n"
# 「.so を読み込む」目印の語。このファイル自身が目印で重いほうに分けられないよう, 綴りを分けて書く
MARK = "c" + "types"
HEAVY = f"import {MARK}\n\n\ndef test_ok():\n    assert {MARK}\n"
FAILING = f"import {MARK}\n\n\ndef test_ng():\n    assert False\n"
SKIPPING = "import pytest\n\n\ndef test_skip():\n    pytest.skip('飛ばす')\n"


def tree(tmp_path: pathlib.Path, files: dict[str, str]) -> pathlib.Path:
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    for name, body in files.items():
        (tmp_path / "tests" / name).write_text(body, encoding="utf-8")
    return tmp_path


def test_the_real_heavy_tests_are_isolated() -> None:
    """★#34 以降の版のテストと test_dtm_ahead は, それぞれ自分だけのプロセスで回る。
    ロジックだけのテスト (このファイルや select_tests) はまとめた1つに入る。"""
    groups = run_tests.plan(["tests"], ROOT)
    alone = {g[0] for g in groups if len(g) == 1}
    for name in [
        f"test_impl_{n}" for n in ("34_unmove", "35_bitboard", "38_precheck", "39_rank_lean")
    ]:
        assert f"tests/{name}.py" in alone
    assert "tests/test_dtm_ahead.py" in alone
    light = groups[0]
    assert "tests/test_select_tests.py" in light and "tests/test_run_tests.py" in light
    # 全部のテストのファイルが, ちょうど1回ずつどこかのプロセスに入る
    every = sorted(str(p.relative_to(ROOT)) for p in (ROOT / "tests").glob("test_*.py"))
    assert sorted(p for g in groups for p in g) == every


def test_plan_groups_and_keeps_node_ids(tmp_path: pathlib.Path) -> None:
    root = tree(tmp_path, {"test_a.py": LIGHT, "test_b.py": HEAVY, "test_c.py": LIGHT})
    assert run_tests.plan(["tests"], root) == [
        ["tests/test_a.py", "tests/test_c.py"],
        ["tests/test_b.py"],
    ]
    assert run_tests.plan(["tests/test_b.py::test_ok", "tests/test_b.py"], root) == [
        ["tests/test_b.py::test_ok", "tests/test_b.py"]
    ]
    assert run_tests.plan([], root) == []


def test_counts_reads_junit(tmp_path: pathlib.Path) -> None:
    assert run_tests.counts(tmp_path / "missing.xml") == (0, 0, 0)
    one = tmp_path / "one.xml"
    one.write_text('<testsuite tests="5" failures="1" errors="1" skipped="2"/>', encoding="utf-8")
    assert run_tests.counts(one) == (5, 2, 2)
    many = tmp_path / "many.xml"
    many.write_text(
        '<testsuites><testsuite tests="3" failures="0" errors="0" skipped="0"/>'
        '<testsuite tests="4" failures="1" errors="0" skipped="1"/></testsuites>',
        encoding="utf-8",
    )
    assert run_tests.counts(many) == (7, 1, 1)


def test_run_separates_processes_and_counts(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """★軽いもの1本・重いもの1本ずつのプロセスで回り, テストの数を足し, ピークの RSS を出す。"""
    root = tree(tmp_path, {"test_a.py": LIGHT, "test_s.py": SKIPPING, "test_b.py": HEAVY})
    args = ["--no-cov", "-q", "-p", "no:cacheprovider"]
    assert run_tests.run(["tests"], args, cwd=root) == 0
    out = capsys.readouterr().out
    assert "プロセス 2 本 / テスト 3 個 (失敗とエラー 0, 飛ばした 1)" in out
    assert "ピークの RSS の最大" in out and "上限 8 GiB" in out


def test_run_fails_on_a_failing_process(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tree(tmp_path, {"test_a.py": LIGHT, "test_f.py": FAILING})
    assert run_tests.run(["tests"], ["--no-cov", "-q", "-p", "no:cacheprovider"], cwd=root) == 1
    captured = capsys.readouterr()
    assert "失敗とエラー 1" in captured.out
    assert "終了コード 1: tests/test_f.py" in captured.err


def test_run_fails_over_the_rss_limit(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """★どれかのプロセスのピークの RSS が上限を超えたら, テストが通っても落とす。"""
    root = tree(tmp_path, {"test_b.py": HEAVY})
    args = ["--no-cov", "-q", "-p", "no:cacheprovider"]
    assert run_tests.run(["tests"], args, max_rss_gib=0.001, cwd=root) == 1
    assert "が上限 0.001 GiB を超えた: tests/test_b.py" in capsys.readouterr().err


def test_run_with_coverage_appends_and_reports_once(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """カバレッジ付きでは, 最初に erase, 各プロセスに --cov-append, 最後に report を1回。
    report の終了コード (fail_under) が全体の終了コードになる。"""
    root = tree(tmp_path, {"test_a.py": LIGHT, "test_b.py": HEAVY})
    cov_calls: list[list[str]] = []
    one_calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        cov_calls.append(cmd[2:])
        return subprocess.CompletedProcess(cmd, 2 if cmd[-1] == "report" else 0)

    def fake_one(paths: list[str], extra: list[str], xml: pathlib.Path, cwd: pathlib.Path) -> Any:
        one_calls.append(extra)
        return run_tests.Result(paths, 0, 1024, 1)

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(run_tests, "run_one", fake_one)
    assert run_tests.run(["tests"], ["-q"], cwd=root) == 2
    assert cov_calls == [["coverage", "erase"], ["coverage", "report"]]
    assert one_calls == [[*run_tests.COV_ARGS, "-q"]] * 2


def test_main_splits_paths_and_pytest_args(monkeypatch: pytest.MonkeyPatch) -> None:
    got: list[Any] = []

    def fake(*a: Any) -> int:
        got.append(a)
        return 0

    monkeypatch.setattr(run_tests, "run", fake)
    assert run_tests.main(["--max-rss-gib", "4", "tests/x.py", "--", "-q", "-x"]) == 0
    assert run_tests.main([]) == 0
    assert got == [(["tests/x.py"], ["-q", "-x"], 4.0), (["tests"], [], 8.0)]


def test_run_with_no_test_files(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tree(tmp_path, {})
    assert run_tests.run(["tests"], ["--no-cov"], cwd=root) == 0
    assert "プロセス 0 本 / テスト 0 個" in capsys.readouterr().out
