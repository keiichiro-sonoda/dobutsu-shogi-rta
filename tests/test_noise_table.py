"""揺れの表が門番のログと合っていること。

記録 #15 のレビューで出た4件はどれも `docs/measurement-noise.md` の表まわりで、
うち2件は「手で計算し直した値がずれた」だった。計算は機械に渡せるので渡す。

⚠️ 残る2件（無い記述を引用した・下書きの状態を指した）は文章の誤りで、
ここでは捕まえられない。**このテストが緑でも文章の正しさは保証しない。**

実際、この検査を入れた回にも「ログが git 管理外で再計算できない」と書いた理由が
事実と違っていた（P1 の3本は commit 済みで、違うのはレイアウトだった）。
機械が見ているのは数字の導出だけ。
"""

from __future__ import annotations

import pathlib
import re
import statistics
from collections.abc import Callable

import noise_table
import pytest
from conftest import ROOT

# 「sd 2.52 / 0.86%」という書き方。表の行と一致していなければならない
INLINE_SPREAD = re.compile(r"sd ([\d.]+) / ([\d.]+)%")


def _in_root(root: pathlib.Path, fn: Callable[[], object]) -> object:
    """noise_table の ROOT を差し替えて呼ぶ。"""
    old = noise_table.ROOT
    noise_table.ROOT = root
    try:
        return fn()
    finally:
        noise_table.ROOT = old


def _with_doc(doc: pathlib.Path, fn: Callable[[], object]) -> object:
    """noise_table の書き出し先を差し替えて呼ぶ。"""
    old = noise_table.DOC
    noise_table.DOC = doc
    try:
        return fn()
    finally:
        noise_table.DOC = old


def markdown_files() -> list[pathlib.Path]:
    out = [p for p in ROOT.glob("*.md")]
    for d in ("docs", "experiments", "tests", "tools", "results"):
        out.extend(sorted((ROOT / d).rglob("*.md")))
    return out


def test_the_table_matches_the_gate_logs() -> None:
    """★表は生成物。手で書いた行が残っていたら落ちる。"""
    assert noise_table.main([]) == 0, (
        "docs/measurement-noise.md の表が門番のログと違う。"
        "python3 tools/noise_table.py --write で組み直すこと"
    )


def test_every_row_has_at_least_three_runs() -> None:
    """★2本では sd を出しても意味が無い。"""
    for row in noise_table.ROWS:
        v = noise_table.samples(row)
        assert len(v) >= 3, f"{row.name} が {len(v)} 本しかない"


def test_the_residual_keeps_two_decimals() -> None:
    """★174段＋残差は秒未満を持っている。丸めて載せると sd が変わる。

    ⚠️ これがこの表でいちばん踏みやすい罠。1桁に丸めた標本から計算すると
    2.52 が 2.50 になる（記録 #15 のレビューで実際に踏んだ）。
    """
    row = next(r for r in noise_table.ROWS if r.phase == noise_table.RESIDUAL)
    raw = noise_table.samples(row)
    assert any(v != int(v) for v in raw), "残差が整数だけになっている (丸められた?)"
    rounded = [round(v, 1) for v in raw]
    assert round(statistics.stdev(raw), 2) != round(statistics.stdev(rounded), 2), (
        "丸めても sd が変わらない標本なので、この検査は空振りしている"
    )


def test_the_measured_phases_are_whole_seconds() -> None:
    """★P0〜P4 は s2hms() が秒未満を切り捨てた表示値。整数がそのまま生値。"""
    for row in noise_table.ROWS:
        if row.phase == noise_table.RESIDUAL:
            continue
        v = noise_table.samples(row)
        assert all(x == int(x) for x in v), f"{row.name} に秒未満がある: {v}"


@pytest.mark.parametrize("path", markdown_files(), ids=lambda p: str(p))
def test_inline_spreads_match_the_table(path: pathlib.Path) -> None:
    """★「sd X / Y%」と書いた箇所が、表の行と食い違っていないこと。

    記録 #15 のレビューで、表を直したときにこの書き方をした2か所が取り残された。

    ⚠️ **走査先に `docs/records/` と `results/` が入っている。** そこは凍結物に
    準じるので本文を直せない。つまり `noise_table.ROWS` から行を外すと、
    直せない文書のせいでこの検査が赤になりうる。**行は消さずに足す**運用で避ける。
    どうしても外すなら、外す前にその行を引用している箇所を grep すること。
    """
    known = noise_table.spreads()
    for sd, cv in INLINE_SPREAD.findall(path.read_text(encoding="utf-8")):
        assert (float(sd), float(cv)) in known, (
            f"{path.relative_to(ROOT)} の「sd {sd} / {cv}%」が表のどの行とも合わない。"
            f"表にあるのは {known}"
        )


# --------------------------------------------------------------------------
# 道具そのものの検査。⚠️ 鳴ることを確かめる (docs/review-checklist.md)
# --------------------------------------------------------------------------


def test_a_broken_clock_is_refused() -> None:
    with pytest.raises(ValueError, match="時刻の書式"):
        noise_table.hms_to_seconds("P0 読み込み：ちょっと")


def test_a_missing_gate_is_refused() -> None:
    with pytest.raises(FileNotFoundError, match="門番のログが無い"):
        noise_table.logs_dir("gate_99_nonexistent")


def test_a_prefix_that_matches_nothing_is_refused() -> None:
    with pytest.raises(FileNotFoundError, match=re.escape("で始まる main.log が無い")):
        noise_table.labels("gate_15_c_successors", "middle")


def test_a_missing_phase_line_is_refused(tmp_path: pathlib.Path) -> None:
    logs = tmp_path / "experiments" / "gate_fake" / "logs"
    logs.mkdir(parents=True)
    (logs / "old1_main.log").write_text("読み込んだ局面：1\n", encoding="utf-8")
    (logs / "console.log").write_text("=== 開始 old1 (impl/x) ===\n", encoding="utf-8")
    with pytest.raises(ValueError, match="P2 後続生成 の行が無い"):
        _in_root(tmp_path, lambda: noise_table.phase_seconds("gate_fake", "old1", "P2"))


def test_a_console_without_timings_is_refused(tmp_path: pathlib.Path) -> None:
    logs = tmp_path / "experiments" / "gate_fake" / "logs"
    logs.mkdir(parents=True)
    (logs / "console.log").write_text("=== 開始 old1 (impl/x) ===\n", encoding="utf-8")
    with pytest.raises(ValueError, match="所要時間を拾えない"):
        _in_root(tmp_path, lambda: noise_table.retreat_totals("gate_fake"))


def test_a_run_missing_from_the_console_is_refused(tmp_path: pathlib.Path) -> None:
    """★main.log はあるのに console.log に所要時間が無い本。残差を出せない。"""
    logs = tmp_path / "experiments" / "gate_fake" / "logs"
    logs.mkdir(parents=True)
    for label in ("old1", "old2"):
        (logs / f"{label}_main.log").write_text(
            "".join(f"{h}：00時間00分01秒\n" for h in noise_table.PHASE_LINES.values()),
            encoding="utf-8",
        )
    (logs / "console.log").write_text(
        "=== 開始 old1 (impl/x) ===\n後退解析の所要時間：10.00 秒\n", encoding="utf-8"
    )
    row = noise_table.Row("x", noise_table.RESIDUAL, "gate_fake", "old", "2本")
    with pytest.raises(ValueError, match="old2 の所要時間が無い"):
        _in_root(tmp_path, lambda: noise_table.samples(row))


def test_a_document_without_markers_is_refused(tmp_path: pathlib.Path) -> None:
    doc = tmp_path / "noise.md"
    doc.write_text("# 表が無い\n", encoding="utf-8")
    with pytest.raises(ValueError, match="noise-table:start"):
        _with_doc(doc, lambda: noise_table.split_doc())


def test_write_then_check_round_trips(tmp_path: pathlib.Path) -> None:
    """★--write で組み直したものが、そのまま検査を通ること。"""
    doc = tmp_path / "noise.md"
    doc.write_text(
        f"前\n\n{noise_table.START}\n| 手で書いた古い表 |\n{noise_table.END}\n\n後\n",
        encoding="utf-8",
    )
    assert _with_doc(doc, lambda: noise_table.main([])) == 1, "食い違いを見逃した"
    assert _with_doc(doc, lambda: noise_table.main(["--write"])) == 0
    assert _with_doc(doc, lambda: noise_table.main([])) == 0, "組み直した表が通らない"
    text = doc.read_text(encoding="utf-8")
    assert text.startswith("前\n") and text.endswith("後\n"), "マーカーの外を書き換えた"
    assert "手で書いた古い表" not in text


def test_a_pattern_that_matches_nothing_is_refused() -> None:
    with pytest.raises(FileNotFoundError, match=re.escape("に合う main.log が無い")):
        noise_table.labels("numa_bind", "n", r"n\d[xy]")


def test_the_pattern_splits_the_arms_without_overlap_or_gap() -> None:
    """★numa_bind の2行が、16本を重複なく取りこぼしなく2つに割っていること。

    腕は接尾辞 (a/d が plain、b/c が numa) で分かれていて接頭辞では割れない。
    ⚠️ 片方のパターンを間違えると、同じ本が両方の行に入るか、どこにも入らない。
    どちらも表の見た目には出ないので、ここで見る。
    """
    plain = noise_table.labels("numa_bind", "n", r"n\d[ad]")
    numa = noise_table.labels("numa_bind", "n", r"n\d[bc]")
    assert len(plain) == 8 and len(numa) == 8
    assert not set(plain) & set(numa), "同じ本が両方の行に入っている"
    assert set(plain) | set(numa) == set(noise_table.labels("numa_bind", "n"))
