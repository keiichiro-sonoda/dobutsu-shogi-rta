"""impl/10_setdiff — 差集合の書き方を変え、全探索の計装を常設した版。

計装 (experiments/forward_profile/) で、全探索 2,352 秒のうち F4 重複排除が
841.96 秒 (35.8%) と最大だった。その中身は

    new_unexp_boards -= seen_boards      # ← 標的
    seen_boards |= new_unexp_boards      # ここは変えない

で、`a -= b` は「`b` を1件ずつ見て `a` から消す」のが標準の経路。CPython 3.9+ には
「`b` が `a` の8倍を超えたら先に交差を作る」最適化があるが、13〜29 ラウンド目は
seen/new が 0.4〜6.3 倍でそこに届かず、seen を全走査していた (その区間の F4 は 384.92 秒)。
`= -` なら舐めるのは new 側だけになる。

同時に、全探索の計装 (F0〜F6) を記録実装に常設する。後退解析には P0〜P4 のタイマーが
入っているのに全探索に無いのは、後退解析を先に計装した歴史の産物でしかない。

⚠️ `= -` は新しい集合を作るので**反復順が変わる**。チャンクの分かれ方が変わり、
途中で切った時点の盤面集合は impl/09 と一致しない (完走すれば同じ答えになる)。
そのため記録 #9 のようなバイト比較は使えず、照合は指紋に戻る。
"""

from __future__ import annotations

import ast
import pathlib

from conftest import ROOT, families, load_impl, run_forward

IMPL_DIR = ROOT / "impl" / "10_setdiff"
PREV_DIR = ROOT / "impl" / "09_no_reslice"
SOURCE = IMPL_DIR / "animal_shogi.py"
PREV_SOURCE = PREV_DIR / "animal_shogi.py"

CHANGED = {"searchNext", "searchAll", "flushTerminalBoards"}
ADDED = {"_rssBytes", "_hwmBytes", "_profMark", "_profWriteHeader", "_profWriteRow"}

# 分割が起きない範囲。ここまでは反復順が変わっても同じ盤面集合になる
ROUNDS_BEFORE_SPLIT = 9


def top_level_functions(path: pathlib.Path) -> dict[str, str]:
    """モジュール直下の関数を、名前 → ソースそのもの で返す。"""
    text = path.read_text(encoding="utf-8")
    out: dict[str, str] = {}
    for node in ast.parse(text).body:
        if isinstance(node, ast.FunctionDef):
            segment = ast.get_source_segment(text, node)
            assert segment is not None, f"{path} の {node.name} のソースを取れない"
            out[node.name] = segment
    return out


def code_lines(body: str) -> list[str]:
    """コメント行を除いたコードの行。罠を警告するコメントに引っかからないため。"""
    return [ln for ln in body.splitlines() if not ln.lstrip().startswith("#")]


def hot_loop(body: str) -> str:
    """searchNext() の展開ループ本体 (while から後続を積むところまで)。"""
    start = body.index("    while unexp_boards:")
    end = body.index("new_unexp_boards += nbl", start) + len("new_unexp_boards += nbl")
    return body[start:end]


def test_c_and_build_are_untouched() -> None:
    """C・ヘッダ・Makefile は impl/09 とバイト単位で同一 (-O0 のまま)。"""
    for name in ("animal_shogi.c", "animal_shogi.h", "Makefile"):
        assert (IMPL_DIR / name).read_bytes() == (PREV_DIR / name).read_bytes(), (
            f"impl/10_setdiff/{name} が impl/09 と違う。この試行で変えるのは Python だけ"
        )


def test_only_the_three_functions_changed() -> None:
    """変わるのは searchNext / searchAll / flushTerminalBoards と、計装の追加だけ。"""
    prev = top_level_functions(PREV_SOURCE)
    cur = top_level_functions(SOURCE)
    changed = {n for n in prev if n in cur and cur[n] != prev[n]}
    assert changed == CHANGED, f"想定外の関数が変わっている: {changed ^ CHANGED}"
    added = set(cur) - set(prev)
    assert added == ADDED, f"想定外の関数が増えている: {added ^ ADDED}"
    assert set(prev) - set(cur) == set(), f"関数が消えている: {set(prev) - set(cur)}"


def test_the_difference_builds_a_new_set() -> None:
    """★今回の1行。`-=` が残っていないこと、`|=` は触っていないこと。"""
    body = top_level_functions(SOURCE)["searchNext"]
    code = "\n".join(code_lines(body))
    assert "new_unexp_boards = new_unexp_boards - seen_boards" in code, "差集合を作り直していない"
    assert "new_unexp_boards -= seen_boards" not in code, "`-=` が残っている (seen を全走査する)"
    assert "seen_boards |= new_unexp_boards" in code, "合併まで変えている (1試行1変数)"


def test_the_clock_is_not_inside_the_hot_loop() -> None:
    """★展開ループの本体は impl/09 とバイト同一。

    ここに時計を置くと 246,803,167 回ぶんの歪みが乗る。
    """
    cur = hot_loop(top_level_functions(SOURCE)["searchNext"])
    prev = hot_loop(top_level_functions(PREV_SOURCE)["searchNext"])
    assert cur == prev, "展開ループの中身が impl/09 から変わっている"
    assert "_profMark" not in cur, "ホットループの内側に時計がある"


def test_the_instrumentation_keeps_sub_second_precision() -> None:
    """★秒未満を切り捨てない。TSV へは float のまま出す。

    main.log の行は既存の P0〜P4 と書式を揃えて s2hms を通すので、そちらは下限。
    """
    text = SOURCE.read_text(encoding="utf-8")
    assert '"%.6f" % row[c]' in text, "TSV に小数で書いていない"
    assert 'f.write("%s\\t%.4f\\n"' in text, "まとめに小数で書いていない"
    row = top_level_functions(SOURCE)["searchAll"]
    assert "s2hms" not in row.split("printLogMain")[0], "行を組み立てる前に s2hms を通している"


def test_the_instrumentation_writes_its_own_files() -> None:
    """計装はサブログにもメインログの既存行にも混ざらない。

    ⚠️ サブログに足すと tests/test_forward_search_equivalence.py の比較が壊れる。
    """
    text = SOURCE.read_text(encoding="utf-8")
    assert 'PROFILE_PATH = "./kaiseki_log/forward.tsv"' in text
    assert 'PROFILE_SUMMARY_PATH = "./kaiseki_log/forward_summary.tsv"' in text
    for name in ("_profWriteHeader", "_profWriteRow"):
        body = top_level_functions(SOURCE)[name]
        assert "printLogSub" not in body, f"{name} がサブログに書いている"
    assert "printLogSub" not in top_level_functions(SOURCE)["searchAll"].split("for _ in range")[0]


def test_the_unique_count_is_recorded_outside_the_timed_section() -> None:
    """★F3 直後の一意数を残す。計装の宿題だった値で、F4 の見積もりの分母になる。

    ⚠️ len() は F4 の境界の外で取る (中で取ると F4 に混ざる)。
    """
    body = top_level_functions(SOURCE)["searchNext"]
    code = "\n".join(code_lines(body))
    assert '_prof["n_new_uniq"] = len(new_unexp_boards)' in code, "一意数を記録していない"
    assert code.index('_prof["n_new_uniq"]') < code.index('_profMark("F4_begin")'), (
        "一意数の len() が F4 の計測区間の中にある"
    )
    assert '_profMark("F4_mid")' in code, "F4 を差集合と合併に分けていない"


def test_no_impl_env_needed() -> None:
    """構成がベースラインと同じなので、ハーネスの既定値でそのまま走る。"""
    assert not (IMPL_DIR / "impl.env").exists()


def test_the_artifacts_match_impl_09_before_any_split(
    shared_library: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """★分割が起きない範囲では、盤面集合もサブログも impl/09 と一致する。

    ⚠️ バイト一致は要求しない。`= -` で反復順が変わるので、同じ集合でも
    pickle の並びが変わる (記録 #9 で通したバイト比較は今回は使えない)。
    """
    works: dict[str, pathlib.Path] = {}
    for impl in ("09_no_reslice", "10_setdiff"):
        work = tmp_path / impl
        module = load_impl(impl, work, shared_library)
        run_forward(module, work, ROUNDS_BEFORE_SPLIT)
        works[impl] = work

    fam_a = families(works["09_no_reslice"] / "dat")
    fam_b = families(works["10_setdiff"] / "dat")
    assert sum(len(v) for v in fam_a.values()) > 100_000, "探索が進んでいない (テストが空振り)"
    for key in fam_a:
        assert fam_a[key] == fam_b[key], f"{key} の盤面集合が impl/09 と違う"

    def sublog(work: pathlib.Path) -> str:
        return (work / "kaiseki_log" / "kaiseki_log7.txt").read_text(encoding="utf-8")

    assert sublog(works["09_no_reslice"]) == sublog(works["10_setdiff"])


def test_the_iteration_order_really_changed(
    shared_library: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """★反復順が変わったことを確かめる。バイト比較を使わない理由そのもの。

    同じ盤面集合でも pickle の中身の並びが変わる。ここが変わらないなら、
    記録 #9 と同じバイト比較を門番に使えるはずで、そちらのほうが強い検査になる。
    """
    dats: list[pathlib.Path] = []
    for impl in ("09_no_reslice", "10_setdiff"):
        work = tmp_path / impl
        module = load_impl(impl, work, shared_library)
        run_forward(module, work, ROUNDS_BEFORE_SPLIT)
        dats.append(work / "dat")

    prev = {p.name: p.read_bytes() for p in dats[0].iterdir() if p.is_file()}
    cur = {p.name: p.read_bytes() for p in dats[1].iterdir() if p.is_file()}
    assert set(prev) == set(cur), f"ファイルの顔ぶれが違う: {set(prev) ^ set(cur)}"
    assert any(prev[name] != cur[name] for name in prev), (
        "バイト列まで同じだった。反復順が変わっていないなら、門番にバイト比較を使える"
    )
