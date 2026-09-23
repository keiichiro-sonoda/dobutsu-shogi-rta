"""impl/21_hugepages — 索引と発見済み表を巨大ページにし、ユーザー時間とカーネル時間を計装する。

C の変数は1つ。C 側で確保している2つの表に、2 MiB ページを頼む。

| 表 | 大きさ | 使う段 |
|---|---|---|
| 索引 `g_index` | 2^29 × 16 B ＝ 8 GiB | P1 (作る)・P2 (引く) |
| 発見済み表 `g_seen` | 最終 2^29 × 8 B ＝ 4 GiB (倍々に作り直す) | F1 |

コードは `experiments/lever_scan/patches/huge.patch` の3か所のまま。`#include <sys/mman.h>` だけを
ファイルの先頭へ移し、コメントを記録の実装として書き直した。

同じ回に、`getrusage` の `ru_utime` / `ru_stime` を拾う計装を入れた (出力を変えないので
変数に数えない。#10 の F0〜F6、#19 の後退解析の計装と同じ扱い)。巨大ページの効き目が
表を作る段の fault (カーネル) から出るのか、表を引く段の番地の翻訳 (ユーザー) から出るのかを分ける。

⚠️ **巨大ページは頼んでも付くとは限らない。** 付かなくても 4 KiB ページのまま正しく動き、
答えは変わらず遅いだけ。ここでは小さいフィクスチャで impl/20 と成果物がバイト一致することと、
付いたかどうかを読む行 (`AnonHugePages`) が要約ファイルに出ることまで見る。
"""

from __future__ import annotations

import ast
import pathlib
import re
import shutil
import subprocess
import types

import pytest
from conftest import ROOT, chdir, impl_library, load_impl, run_forward, run_retreat

IMPL_DIR = ROOT / "impl" / "21_hugepages"
PREV_DIR = ROOT / "impl" / "20_prefetch"
PATCH = ROOT / "experiments" / "lever_scan" / "patches" / "huge.patch"
SOURCE = IMPL_DIR / "animal_shogi.py"
PREV_SOURCE = PREV_DIR / "animal_shogi.py"
MMAN = "#include <sys/mman.h>"

# 計装を入れた関数と、足した補助関数。これ以外は impl/20 から1バイトも動かさない
CHANGED = {"_profMark", "_retreatWriteSummary", "searchAll", "retreatAnalysis"}
ADDED = {"_smapsHuge"}

SMALL_BOARD_NUM_MAX = 2000
FORWARD_ROUNDS = 7


def c_code(text: str) -> str:
    """C からコメントを落とす。規約を説明した文が、その規約の語を含むため。"""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return "\n".join(ln.split("//", 1)[0] for ln in text.splitlines())


def code_only(text: str) -> list[str]:
    """コメントを落とし、空行と行末の空白を除いた行の並び。コメントの書き直しを無視して比べる。"""
    return [ln.rstrip() for ln in c_code(text).splitlines() if ln.strip()]


def function_body(csrc: str, signature: str) -> str:
    """関数の定義から、行頭の `}` (関数の終わり) までを返す。"""
    start = csrc.index(signature)
    end = csrc.index("\n}\n", start)
    return csrc[start : end + 2]


def top_level(path: pathlib.Path, kind: type) -> dict[str, str]:
    """モジュール直下の関数 (または代入) を、名前 → ソースそのもの で返す。"""
    text = path.read_text(encoding="utf-8")
    out: dict[str, str] = {}
    for node in ast.parse(text).body:
        if not isinstance(node, kind):
            continue
        names = (
            [node.name]
            if isinstance(node, ast.FunctionDef)
            else [t.id for t in getattr(node, "targets", []) if isinstance(t, ast.Name)]
        )
        segment = ast.get_source_segment(text, node)
        assert segment is not None
        for name in names:
            out[name] = segment
    return out


# --------------------------------------------------------------------------
# 構造
# --------------------------------------------------------------------------


def test_the_header_and_the_build_are_byte_identical_to_impl_20() -> None:
    """★`.h` と `Makefile` は impl/20 とバイト同一 (`-O2` のまま。フラグは混ぜない)。"""
    for name in ("animal_shogi.h", "Makefile"):
        assert (IMPL_DIR / name).read_bytes() == (PREV_DIR / name).read_bytes(), (
            f"{name} が impl/20 と違う"
        )


def test_no_impl_env_needed() -> None:
    assert not (IMPL_DIR / "impl.env").exists(), "既定のビルド・実行コマンドで走るはず"


def test_the_c_is_impl_20_plus_the_hugepage_patch(tmp_path: pathlib.Path) -> None:
    """★C のコードが「impl/20 ＋ `huge.patch`」と一致すること。

    `#include <sys/mman.h>` だけは、パッチがファイルの途中に置いていたのを先頭へ移したので、
    両方から除いて比べ、別に「先頭の include 群に1回だけある」ことを確かめる。
    """
    if shutil.which("patch") is None:
        pytest.skip("patch が無い")
    work = tmp_path / "ref"
    work.mkdir()
    for name in ("animal_shogi.c", "animal_shogi.h"):
        shutil.copy(PREV_DIR / name, work / name)
    with PATCH.open("rb") as f:
        done = subprocess.run(
            ["patch", "--forward", "--fuzz=0", "--no-backup-if-mismatch", "-p1", "-d", str(work)],
            stdin=f,
            capture_output=True,
            check=False,
        )
    assert done.returncode == 0, f"huge.patch が impl/20 に当たらない:\n{done.stdout!r}"
    ref = [ln for ln in code_only((work / "animal_shogi.c").read_text("utf-8")) if ln != MMAN]
    cur_text = (IMPL_DIR / "animal_shogi.c").read_text(encoding="utf-8")
    cur = [ln for ln in code_only(cur_text) if ln != MMAN]
    assert cur == ref, "巨大ページの3か所以外のコードが動いている"
    head = cur_text.splitlines()[:5]
    assert head.count(MMAN) == 1 and cur_text.count(MMAN) == 1, (
        "#include <sys/mman.h> が先頭の include 群に1回だけ、になっていない"
    )


def test_hugepages_are_requested_before_the_tables_are_touched() -> None:
    """★3か所とも `hugeAlloc` が `memset` より前。触ったあとに頼んでも、その場では付かない。"""
    csrc = c_code((IMPL_DIR / "animal_shogi.c").read_text(encoding="utf-8"))
    for sig in ("int indexBuild(", "int seenInit(", "static int seenGrow("):
        body = function_body(csrc, sig)
        assert "hugeAlloc(" in body, f"{sig} が巨大ページを頼んでいない"
        assert body.index("hugeAlloc(") < body.index("memset("), (
            f"{sig} で memset のあとに頼んでいる"
        )
    helper = function_body(csrc, "static void *hugeAlloc(")
    assert helper.index("aligned_alloc(HUGE_ALIGN") < helper.index("madvise("), (
        "hugeAlloc が確保より前に madvise している"
    )
    assert "MADV_HUGEPAGE" in helper
    assert csrc.count("hugeAlloc(") == 4, "hugeAlloc の定義と3か所の呼び出し以外がある"


def test_only_the_instrumentation_changed_in_python() -> None:
    """★`.py` で変わったのは計装の関数だけ。`forward.tsv` の列と後退解析の区間は動かさない。"""
    prev = top_level(PREV_SOURCE, ast.FunctionDef)
    cur = top_level(SOURCE, ast.FunctionDef)
    changed = {n for n in prev if n in cur and cur[n] != prev[n]}
    assert changed == CHANGED, f"想定外の関数が変わっている: {changed ^ CHANGED}"
    assert set(cur) - set(prev) == ADDED, f"増えた関数が想定と違う: {set(cur) - set(prev)}"
    assert set(prev) - set(cur) == set()
    prev_a = top_level(PREV_SOURCE, ast.Assign)
    cur_a = top_level(SOURCE, ast.Assign)
    for name in (
        "PROFILE_MARKS",
        "PROFILE_COUNTS",
        "PROFILE_TIMES",
        "PROFILE_COLUMNS",
        "RETREAT_MARKS",
        "RETREAT_SPANS",
    ):
        assert cur_a[name] == prev_a[name], f"{name} が impl/20 から変わっている"


def test_the_update_uk_file_defect_is_carried_over() -> None:
    """★CLAUDE.md「次の実装で必ず直すもの」の `updateUKFile` の2分割は、直さずに持ち越す。

    直すとチャンクの切れ目が動いて2つ目の変数になる (1試行に1つ)。
    直したら、この固定と CLAUDE.md の項目を一緒に畳むこと。
    """
    body = top_level(SOURCE, ast.FunctionDef)["updateUKFile"]
    assert "ukl[BOARD_NUM_MAX:]" in body, "updateUKFile の「残り全部」が直っている"


def test_the_makefile_builds_without_warnings(tmp_path: pathlib.Path) -> None:
    """★`make animal_shogi.so` が通り、警告を1つも出さないこと。"""
    if shutil.which("gcc") is None or shutil.which("make") is None:
        pytest.skip("gcc か make が無い")
    work = tmp_path / "build"
    work.mkdir()
    for name in ("animal_shogi.c", "animal_shogi.h", "Makefile"):
        shutil.copy(IMPL_DIR / name, work / name)
    done = subprocess.run(
        ["make", "animal_shogi.so"], cwd=work, capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, f"make が失敗した:\n{done.stdout}\n{done.stderr}"
    assert "warning" not in done.stderr.lower(), f"警告が出ている:\n{done.stderr}"


# --------------------------------------------------------------------------
# 走らせて impl/20 と突き合わせる
# --------------------------------------------------------------------------


def limited_search_all(module: types.ModuleType, work: pathlib.Path, rounds: int) -> None:
    """`searchAll()` を rounds ラウンドで打ち切って走らせる。

    `forward_summary.tsv` は `searchAll()` の最後にしか書かれないので、`run_forward` では出ない。
    `searchNext` を包み、rounds 回目で「終わった」と返させる。
    """
    real = module.searchNext
    count = [0]

    def limited() -> bool:
        count[0] += 1
        return bool(real()) or count[0] >= rounds

    vars(module)["searchNext"] = limited
    vars(module)["BOARD_NUM_MAX"] = SMALL_BOARD_NUM_MAX
    with chdir(work):
        module.searchAll()


@pytest.fixture(scope="module")
def runs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, pathlib.Path]:
    """impl/20 と impl/21 を、同じ打ち切り `dat/` から後退解析まで回す。

    #21 は全探索も打ち切って別に回す (要約ファイルの行を見るため)。
    """
    if shutil.which("gcc") is None:
        pytest.skip("gcc が無い")
    src = tmp_path_factory.mktemp("fixture21")
    module = load_impl("20_prefetch", src, impl_library("20_prefetch"))
    run_forward(module, src, FORWARD_ROUNDS, SMALL_BOARD_NUM_MAX)

    out: dict[str, pathlib.Path] = {}
    for impl in ("20_prefetch", "21_hugepages"):
        work = tmp_path_factory.mktemp(impl)
        module = load_impl(impl, work, impl_library(impl))
        for path in sorted((src / "dat").iterdir()):
            shutil.copy(path, work / "dat" / path.name)
        vars(module)["BOARD_NUM_MAX"] = SMALL_BOARD_NUM_MAX
        run_retreat(module, work)
        out[impl] = work
    fwd = tmp_path_factory.mktemp("forward21")
    module = load_impl("21_hugepages", fwd, impl_library("21_hugepages"))
    limited_search_all(module, fwd, FORWARD_ROUNDS)
    out["forward21"] = fwd
    return out


def summary(path: pathlib.Path) -> dict[str, str]:
    return dict(ln.split("\t", 1) for ln in path.read_text(encoding="utf-8").splitlines())


def test_the_artifacts_are_byte_identical_to_impl_20(runs: dict[str, pathlib.Path]) -> None:
    """★成果物が impl/20 と**バイト一致**すること。巨大ページは値も順序も変えない。"""
    a, b = runs["20_prefetch"] / "dat", runs["21_hugepages"] / "dat"
    names = sorted(p.name for p in a.iterdir())
    assert names == sorted(p.name for p in b.iterdir()), "ファイルの顔ぶれが違う"
    assert len(names) > 3, f"成果物が少なすぎる (テストが空振り): {names}"
    differ = [n for n in names if (a / n).read_bytes() != (b / n).read_bytes()]
    assert differ == [], f"バイトが違うファイルがある: {differ[:5]}"


def test_the_retreat_summary_has_cpu_times_and_hugepages(runs: dict[str, pathlib.Path]) -> None:
    """★後退解析の要約に、境界ごとの utime / stime と、索引の AnonHugePages が出ること。"""
    rows = summary(runs["21_hugepages"] / "kaiseki_log" / "retreat_summary.tsv")
    marks = [k[len("t_") :] for k in rows if k.startswith("t_")]
    assert marks, "境界の行が無い (テストが空振り)"
    for kind in ("utime_", "stime_"):
        values = [float(rows[kind + m]) for m in marks]
        assert values == sorted(values), f"{kind} の累積値が境界の順に減っている: {values}"
    for key in ("rss_index_kB", "anonhuge_index_kB", "smaps_index_sec"):
        assert key in rows, f"{key} が出ていない"
    # 区間の行は最初の t_ 行より前だけ (gate_stats.py の spans モードがそこで読むのをやめる)
    keys = list(rows)
    assert keys.index("anonhuge_index_kB") > keys.index("t_" + marks[0])


def test_the_forward_summary_has_cpu_times_and_hugepages(runs: dict[str, pathlib.Path]) -> None:
    """★全探索の要約に、段ごとの utime / stime と、発見済み表の AnonHugePages が出ること。"""
    rows = summary(runs["forward21"] / "kaiseki_log" / "forward_summary.tsv")
    for kind in ("utime", "stime"):
        for k in ("F0", "F1", "F2", "F3", "F4", "F5", "F6", "release", "forward_total"):
            assert f"{kind}_{k}" in rows, f"{kind}_{k} が出ていない"
            assert float(rows[f"{kind}_{k}"]) >= 0.0
        stages = sum(float(rows[f"{kind}_{k}"]) for k in ("F0", "F1", "F2", "F3", "F4", "F5"))
        assert stages <= float(rows[f"{kind}_forward_total"]) + 1e-3, (
            f"{kind} の段の合計が全体を超えている"
        )
    for key in ("rss_seen_kB", "anonhuge_seen_kB", "smaps_seen_sec"):
        assert key in rows, f"{key} が出ていない"
    # 発見済み表 (小さく回しても 2^20 × 8 B ＝ 8 MiB) は巨大ページを頼んでいる
    assert int(rows["anonhuge_seen_kB"]) >= 0
