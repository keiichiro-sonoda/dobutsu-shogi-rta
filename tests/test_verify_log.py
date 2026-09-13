"""tools/verify_log.py の検証ロジックをテストする。

verify_log.py は「高速化が答えを壊していないか」を判定する唯一の門番なので、
通すべきものを通し、落とすべきものを落とすことを両方確かめる。
"""

from __future__ import annotations

import pathlib
import sys

import pytest
import verify_log
from conftest import RESULTS_DIR, DistRow


def render_log(rows: list[DistRow]) -> str:
    """ベースライン実装が吐くメインログの形式で行を組み立てる。"""
    lines = []
    for depth, result, count in rows:
        jp = "勝ち" if result == "win" else "負け"
        # depth=1 の行だけ実装が注釈を付ける
        note = " (キャッチ除く)" if depth == 1 else ""
        lines.append(f"{depth:3d}手{jp}盤面総数{note}：{count}")
    return "\n".join(lines) + "\n"


def run_main(monkeypatch: pytest.MonkeyPatch, path: pathlib.Path) -> int:
    monkeypatch.setattr(sys, "argv", ["verify_log.py", str(path)])
    return verify_log.main()


def test_parse_log_reads_every_row(tmp_path: pathlib.Path, distribution: list[DistRow]) -> None:
    log = tmp_path / "main.log"
    log.write_text(render_log(distribution), encoding="utf-8")
    assert verify_log.parse_log(str(log)) == distribution


def test_catch_annotation_on_depth1_is_parsed(tmp_path: pathlib.Path) -> None:
    log = tmp_path / "main.log"
    log.write_text("  1手勝ち盤面総数 (キャッチ除く)：9118571\n", encoding="utf-8")
    assert verify_log.parse_log(str(log)) == [(1, "win", 9118571)]


def test_unrelated_lines_are_ignored(tmp_path: pathlib.Path) -> None:
    log = tmp_path / "main.log"
    log.write_text(
        "総未知盤面数：99485568, 総勝ち盤面数：140298614\n"
        "01時間42分56秒で全探索終了\n"
        "####################################################\n"
        "  2手負け盤面総数：9343557\n"
        "所要時間：00時間14分57秒\n",
        encoding="utf-8",
    )
    assert verify_log.parse_log(str(log)) == [(2, "lose", 9343557)]


def test_matching_log_passes(
    tmp_path: pathlib.Path, distribution: list[DistRow], monkeypatch: pytest.MonkeyPatch
) -> None:
    log = tmp_path / "main.log"
    log.write_text(render_log(distribution), encoding="utf-8")
    assert run_main(monkeypatch, log) == 0


def test_recorded_baseline_log_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    """記録済みの実測ログ (results/00_baseline/main.log) は今も PASS すること。

    verify_log.py をいじって実際のログ形式を読めなくする回帰を防ぐ。
    """
    log = RESULTS_DIR / "00_baseline" / "main.log"
    assert log.exists(), "記録済みログが無い"
    assert run_main(monkeypatch, log) == 0


def test_single_wrong_count_fails(
    tmp_path: pathlib.Path,
    distribution: list[DistRow],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    broken = list(distribution)
    depth, result, count = broken[41]
    broken[41] = (depth, result, count + 1)

    log = tmp_path / "main.log"
    log.write_text(render_log(broken), encoding="utf-8")

    assert run_main(monkeypatch, log) == 1
    out = capsys.readouterr().out
    assert "FAIL" in out
    assert f"depth={depth:3d}" in out


def test_truncated_log_fails(
    tmp_path: pathlib.Path,
    distribution: list[DistRow],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """完走していないログを PASS させない。"""
    log = tmp_path / "main.log"
    log.write_text(render_log(distribution[:-1]), encoding="utf-8")

    assert run_main(monkeypatch, log) == 1
    assert "行数が足りない" in capsys.readouterr().out


def test_empty_log_fails(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log = tmp_path / "main.log"
    log.write_text("", encoding="utf-8")
    assert run_main(monkeypatch, log) == 1


def test_appended_second_run_still_passes(
    tmp_path: pathlib.Path, distribution: list[DistRow], monkeypatch: pytest.MonkeyPatch
) -> None:
    """同じログに再走が追記されていても、先頭 174 行だけを見て判定する。"""
    log = tmp_path / "main.log"
    log.write_text(render_log(distribution) * 2, encoding="utf-8")
    assert run_main(monkeypatch, log) == 0


def test_wrong_argument_count_returns_2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["verify_log.py"])
    assert verify_log.main() == 2


def test_many_mismatches_are_truncated_in_the_report(
    tmp_path: pathlib.Path,
    distribution: list[DistRow],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """不一致が 20 行を超えたら、残り件数だけを出して打ち切る。"""
    broken = [(d, r, c + 1) for d, r, c in distribution]

    log = tmp_path / "main.log"
    log.write_text(render_log(broken), encoding="utf-8")

    assert run_main(monkeypatch, log) == 1
    out = capsys.readouterr().out
    assert f"FAIL: {len(distribution)} 行が不一致" in out
    assert f"... 他 {len(distribution) - 20} 行" in out
