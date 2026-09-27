"""impl/25_huge_retreat — 後退解析の配列を 2 MiB ページで確保する (＋計装と受け皿の片付け)。

変数は1つ。`experiments/lever_scan_2/patches/hugeR.patch` を入れた。
`pred` / `pred_off` / `cnt` / `dtm` を Python の `array` / `bytearray` ではなく、
C の `hugeAlloc()` (索引と同じ) で確保する (`hugeFill()`)。

同じ回に、変数に数えないものを2つ入れた (門番では両腕に入れる):

- 計装 (`experiments/lever_scan_2/patches/instr.patch`): 後退解析の配列に付いた巨大ページ
  (`anonhuge_loop_kB` など。`retreat_summary.tsv` の末尾) と、全探索の段ごとの minor fault
  (`minflt_*`。`forward_summary.tsv` の末尾)。既存の行の並びと意味は変えない
- 受け皿の片付け (`experiments/gate_25_huge_retreat/patches/release.patch`): #24 の受け皿を
  全探索の解放の区間で手放す

⚠️ 門番の `old` 腕は「impl/24 ＋ instr ＋ release」で、impl/25 はそれに hugeR を足したもの
(コメントを除く)。ここで固定しておくと、門番の2腕の差が hugeR だけだと言える。
コメントは記録の実装として書き直した。`.h` と `Makefile` は impl/24 とバイト同一。
"""

from __future__ import annotations

import ast
import pathlib
import re
import shutil
import subprocess
from typing import Any

import pytest
from conftest import ROOT, impl_library, load_impl
from test_impl_22_in_memory import limited_run, top_level
from test_impl_23_loop_prefetch import code_only, function_body
from test_impl_24_reuse_buffers import py_code

IMPL = "25_huge_retreat"
PREV = "24_reuse_buffers"
IMPL_DIR = ROOT / "impl" / IMPL
PREV_DIR = ROOT / "impl" / PREV
SOURCE = IMPL_DIR / "animal_shogi.py"
PREV_SOURCE = PREV_DIR / "animal_shogi.py"
SCAN = ROOT / "experiments" / "lever_scan_2" / "patches"
GATE = ROOT / "experiments" / "gate_25_huge_retreat"
# 門番の old 腕 (build_arm.sh と同じ順)。impl/25 はこれに hugeR を足したもの
OLD_PATCHES = (SCAN / "instr.patch", GATE / "patches" / "release.patch")
HUGE_PATCH = SCAN / "hugeR.patch"

CHANGED = {
    "searchAll", "_retreatWriteSummary", "buildSuccessors", "buildPredecessors", "retreatAnalysis",
}  # fmt: skip
NEW_FORWARD_KEYS = [
    "minflt_F0", "minflt_F1", "minflt_F2", "minflt_F3", "minflt_F4", "minflt_F5",
    "minflt_F6", "minflt_release", "minflt_forward_total",
]  # fmt: skip
NEW_RETREAT_KEYS = ["rss_loop_kB", "anonhuge_loop_kB", "smaps_loop_sec"]


def patched(tmp: pathlib.Path, patches: tuple[pathlib.Path, ...]) -> pathlib.Path:
    """impl/24 の `.py` と `.c` に patches を順に当てた写しを作る (fuzz なし)。"""
    if shutil.which("patch") is None:
        pytest.skip("patch が無い")
    tmp.mkdir(parents=True, exist_ok=True)
    for name in ("animal_shogi.py", "animal_shogi.c"):
        shutil.copy(PREV_DIR / name, tmp / name)
    for patch in patches:
        with patch.open("rb") as f:
            done = subprocess.run(
                [
                    "patch",
                    "--forward",
                    "--fuzz=0",
                    "--no-backup-if-mismatch",
                    "-p1",
                    "-d",
                    str(tmp),
                ],
                stdin=f,
                capture_output=True,
                check=False,
            )
        assert done.returncode == 0, f"{patch.name} が当たらない:\n{done.stdout!r}"
    return tmp


# --------------------------------------------------------------------------
# 構造
# --------------------------------------------------------------------------


def test_the_header_and_the_build_are_byte_identical_to_impl_24() -> None:
    for name in ("animal_shogi.h", "Makefile"):
        assert (IMPL_DIR / name).read_bytes() == (PREV_DIR / name).read_bytes(), name


def test_no_impl_env_needed() -> None:
    assert not (IMPL_DIR / "impl.env").exists(), "既定のビルド・実行コマンドで走るはず"


def test_impl_25_is_the_old_arm_plus_huge_r(tmp_path: pathlib.Path) -> None:
    """★コード (コメントを除く) が「impl/24 ＋ instr ＋ release ＋ hugeR」と一致する。

    門番の old 腕は hugeR を当てる前のもの。2腕の差が hugeR だけであることの根拠。
    """
    done = patched(tmp_path / "new", (*OLD_PATCHES, HUGE_PATCH))
    assert py_code(SOURCE.read_text(encoding="utf-8")) == py_code(
        (done / "animal_shogi.py").read_text(encoding="utf-8")
    )
    assert code_only((IMPL_DIR / "animal_shogi.c").read_text(encoding="utf-8")) == code_only(
        (done / "animal_shogi.c").read_text(encoding="utf-8")
    )


def test_the_old_arm_leaves_the_c_untouched(tmp_path: pathlib.Path) -> None:
    """★門番の old 腕の C は impl/24 とバイト同一 (計装と片付けは Python だけ)。"""
    old = patched(tmp_path / "old", OLD_PATCHES)
    assert (old / "animal_shogi.c").read_bytes() == (PREV_DIR / "animal_shogi.c").read_bytes()


def test_only_huge_fill_was_added_to_the_c() -> None:
    """★C で足したのは `hugeFill()` だけ。ほかの関数はコメントまでバイト同一。"""
    new = (IMPL_DIR / "animal_shogi.c").read_text(encoding="utf-8")
    old = (PREV_DIR / "animal_shogi.c").read_text(encoding="utf-8")
    body = function_body(new, "void *hugeFill(")
    start = new.index("// ---- 後退解析の配列を 2 MiB ページで確保する (記録 #25)")
    # 足したのは「見出しのコメント → hugeFill() → 空行」のひとかたまり
    added = new[start : new.index(body) + len(body) + 2]
    assert added.endswith("}\n\n")
    assert new.replace(added, "", 1) == old
    # madvise (hugeAlloc の中) を頼んでから memset する
    lines = code_only(body)
    assert any("hugeAlloc(bytes)" in ln for ln in lines)
    assert [i for i, ln in enumerate(lines) if "hugeAlloc(" in ln] < [
        i for i, ln in enumerate(lines) if "memset(" in ln
    ]


def test_only_the_planned_python_changed() -> None:
    """★変わった関数は決めた集合だけ。足したのは `hugeArray()` と `hugeFill` の口だけ。"""
    old, new = top_level(PREV_SOURCE, ast.FunctionDef), top_level(SOURCE, ast.FunctionDef)
    assert set(new) - set(old) == {"hugeArray"}
    assert set(old) - set(new) == set()
    assert {n for n in old if old[n] != new[n]} == CHANGED
    old_a, new_a = top_level(PREV_SOURCE, ast.Assign), top_level(SOURCE, ast.Assign)
    assert set(new_a) - set(old_a) == {"hugeFill"}
    assert all(new_a[n] == old_a[n] for n in old_a), "既存の代入が変わっている"


def test_the_four_retreat_arrays_come_from_huge_fill() -> None:
    """★`pred` / `pred_off` / `cnt` / `dtm` の4つだけを `hugeArray()` で確保する。

    ほかの配列 (`succ`・`succ_off`・`packed` など) には広げない。
    """
    code = "\n".join(ln.split("#", 1)[0] for ln in SOURCE.read_text(encoding="utf-8").splitlines())
    calls = re.findall(r"^\s*(\w+) = hugeArray\(", code, flags=re.M)
    assert sorted(calls) == ["cnt", "dtm", "pred", "pred_off"]
    assert "bytearray(n_uk)" not in code
    assert 'bytearray(b"\\xff") * n_all' not in code


# --------------------------------------------------------------------------
# 走らせて impl/24 と突き合わせる
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def runs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, dict[str, Any]]:
    """impl/24 と impl/25 を、同じ上限・同じラウンド数で打ち切って後退解析まで回す。"""
    if shutil.which("gcc") is None:
        pytest.skip("gcc が無い")
    out: dict[str, dict[str, Any]] = {}
    for impl in (PREV, IMPL):
        work = tmp_path_factory.mktemp(impl)
        out[impl] = limited_run(load_impl(impl, work, impl_library(impl)), work)
    return out


def summary_keys(work: pathlib.Path, name: str) -> list[str]:
    text = (work / "kaiseki_log" / name).read_text(encoding="utf-8")
    return [ln.split("\t", 1)[0] for ln in text.splitlines()]


def summary(work: pathlib.Path, name: str) -> dict[str, str]:
    text = (work / "kaiseki_log" / name).read_text(encoding="utf-8")
    return dict(ln.split("\t", 1) for ln in text.splitlines())


def test_the_rounds_and_p0_agree_with_impl_24(runs: dict[str, dict[str, Any]]) -> None:
    """★ラウンドごとの件数と、P0 に渡る中身・P0 が詰めたバイト列が impl/24 と一致する。"""
    a, b = runs[PREV], runs[IMPL]
    assert len(a["counts"]) > 10
    for key in ("counts", "queue", "uk_all", "catch_wins", "try_loses", "tbn", "packed", "n"):
        assert a[key] == b[key], key


def test_the_artifacts_are_byte_identical_to_impl_24(runs: dict[str, dict[str, Any]]) -> None:
    """★後退解析まで回した成果物が impl/24 とバイト一致する (確保の仕方だけが違う)。"""
    da, db = runs[PREV]["work"] / "dat", runs[IMPL]["work"] / "dat"
    names = sorted(p.name for p in da.iterdir())
    assert names == sorted(p.name for p in db.iterdir()), "ファイルの顔ぶれが違う"
    assert len(names) > 3, f"成果物が少なすぎる (テストが空振り): {names}"
    differ = [n for n in names if (da / n).read_bytes() != (db / n).read_bytes()]
    assert differ == [], f"バイトが違うファイルがある: {differ[:5]}"


def test_the_retreat_totals_agree_with_impl_24(runs: dict[str, dict[str, Any]]) -> None:
    def totals(work: pathlib.Path) -> list[str]:
        text = (work / "kaiseki_log" / "kaizenkaiseki1.txt").read_text(encoding="utf-8")
        return [ln for ln in text.splitlines() if "盤面総数" in ln]

    a = totals(runs[PREV]["work"])
    assert len(a) > 2, f"深さが進んでいない: {a}"
    assert a == totals(runs[IMPL]["work"])


@pytest.mark.parametrize(
    ("name", "added"),
    [("forward_summary.tsv", NEW_FORWARD_KEYS), ("retreat_summary.tsv", NEW_RETREAT_KEYS)],
)
def test_the_new_rows_are_appended_at_the_end(
    runs: dict[str, dict[str, Any]], name: str, added: list[str]
) -> None:
    """★計装の行は末尾に足すだけ。既存の行の並びは変えない (gate_stats.py などが今のまま読める)。"""
    old = summary_keys(runs[PREV]["work"], name)
    new = summary_keys(runs[IMPL]["work"], name)
    assert new == old + added


def test_the_forward_minor_faults_add_up(runs: dict[str, dict[str, Any]]) -> None:
    """★段ごとの minor fault は0以上の整数で、合計は F0〜F6 と解放の和以上 (残差の区間もある)。"""
    s = summary(runs[IMPL]["work"], "forward_summary.tsv")
    parts = [int(s[k]) for k in NEW_FORWARD_KEYS[:-1]]
    assert all(v >= 0 for v in parts)
    assert int(s["minflt_forward_total"]) >= sum(parts)
    # ⚠️ 値が正であることは見ない。テストを同じプロセスで続けて回すとヒープが温まっていて、
    #    小さい走行の F1 では新しいページのフォルトが1回も起きないことがある
    r = summary(runs[IMPL]["work"], "retreat_summary.tsv")
    assert int(r["anonhuge_loop_kB"]) >= 0 and float(r["smaps_loop_sec"]) >= 0


def test_the_receivers_are_released_after_the_forward_search(
    runs: dict[str, dict[str, Any]],
) -> None:
    """★#24 の受け皿は全探索の解放の区間で手放している (impl/24 は持ち続ける)。"""
    assert runs[IMPL]["module"]._exp_bufs is None
    assert runs[PREV]["module"]._exp_bufs is not None
