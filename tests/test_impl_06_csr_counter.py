"""impl/06_csr_counter — 後退解析を「各辺1回」にした版。

#5 までの後退解析は未確定局面を174ラウンド舐め直し、そのたびに指し手を作り直していた。
延べ訪問 1,479,788,351 回に対し、実際に必要な辺は 938,671,869 本しかない。
連番を振って前任リスト (CSR) とカウンタを作れば、各辺をちょうど1回ずつ通るだけで済む。

⚠️ これまでの5本と違って**仕事の量そのものを変える**ので、同じ答えが出ることは自明でない。
ここで見るのは構造だけで、答えが合うかは tests/test_retreat_analysis_equivalence.py が
実際に走らせて確かめる。全規模の検算は門番 G1 (tools/rebuild_forward_fixture.py) で行う。

梯子5段目 (連番化) と6段目 (CSR＋カウンタ) は分けても記録に載る差が出ないので、
1試行にまとめてある。
"""

from __future__ import annotations

import ast
import pathlib

from conftest import BASELINE_DIR, ROOT

IMPL_DIR = ROOT / "impl" / "06_csr_counter"
SOURCE = IMPL_DIR / "animal_shogi.py"
PREV_SOURCE = ROOT / "impl" / "05_batch_wl_write" / "animal_shogi.py"

CHANGED = {"retreatAnalysis"}
ADDED = {
    "appendFamily",
    "loadForwardResult",
    "buildIndex",
    "buildSuccessors",
    "buildPredecessors",
}
REMOVED = {"loadAllWinBoards", "searchWinBoard", "searchLoseBoard"}

# 前向き探索は今回の対照群。1バイトも動かさない
UNTOUCHED_FORWARD = (
    "searchNext",
    "searchAll",
    "buildSeenBoards",
    "updateUKFile",
    "updateWLFile",
    "nextBoardInvNormalWrap",
    "writeAndBackup",
    "s2hms",
    "main",
)

# 後退解析側でも、#5 で書いたものはそのまま使い回す
REUSED_FROM_05 = ("writeWLFilesForDepth", "writeUnknownChunks", "loadAllUnknownBoards")


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


def test_c_and_build_are_untouched() -> None:
    """C・ヘッダ・Makefile はベースラインとバイト単位で同一 (＝ -O0 のまま)。

    指示書の「純Pythonで実装する」は、ここを触らないことでもある。
    """
    for name in ("animal_shogi.c", "animal_shogi.h", "Makefile"):
        assert (IMPL_DIR / name).read_bytes() == (BASELINE_DIR / name).read_bytes(), (
            f"impl/06_csr_counter/{name} がベースラインと違う。"
            f"アルゴリズムの効果と実装言語の効果が分離できなくなる"
        )


def test_only_the_retreat_analysis_changed() -> None:
    """全探索側が1バイトも動いていないこと。これが対照群の担保になる。"""
    prev = top_level_functions(PREV_SOURCE)
    cur = top_level_functions(SOURCE)
    changed = {n for n in prev if n in cur and cur[n] != prev[n]}
    assert changed == CHANGED, f"想定外の関数が変わっている: {changed ^ CHANGED}"
    assert set(cur) - set(prev) == ADDED, f"想定外の関数が増えている: {set(cur) - set(prev)}"
    assert set(prev) - set(cur) == REMOVED, f"想定外の関数が消えている: {set(prev) - set(cur)}"

    for name in UNTOUCHED_FORWARD:
        assert cur[name] == prev[name], f"{name} が impl/05 から変わっている"


def test_the_retreat_reuses_what_05_already_wrote() -> None:
    """成果物の形式を変えないために、書き出しは #5 のものをそのまま使う。"""
    prev = top_level_functions(PREV_SOURCE)
    cur = top_level_functions(SOURCE)
    for name in REUSED_FROM_05:
        assert cur[name] == prev[name], f"{name} を書き換えている"
    body = cur["retreatAnalysis"]
    assert "writeWLFilesForDepth(" in body, "深さごとの書き出しを使っていない"
    assert "writeUnknownChunks(" in body, "引き分けを書き戻していない"


def test_the_wrapper_is_not_optimised() -> None:
    """`nextBoardInvNormalWrap` は指示書の不可侵リスト。

    呼び出しごとに 48 要素を確保するのは 99,485,568 回ぶん効くが、
    ここを直すと「アルゴリズムが効いたのか」が濁る。次の試行に回す。
    """
    cur = top_level_functions(SOURCE)
    assert "c_uint64_array48()" in cur["nextBoardInvNormalWrap"]


def test_the_index_is_not_sorted() -> None:
    """連番は全単射でありさえすればよい。純Python で 2.4 億件をソートすると数分が飛ぶ。"""
    body = top_level_functions(SOURCE)["loadForwardResult"]
    assert "sort" not in body, "パック値をソートしている"


def test_the_three_families_are_laid_out_contiguously() -> None:
    """[未知][キャッチ][トライ負け] の順に詰める。

    こう並べておくと cnt[] と succ_off[] が未知のぶんだけで済み、
    深さ0と深さ1の初期フロンティアが range() になる。
    """
    body = top_level_functions(SOURCE)["loadForwardResult"]
    assert body.index("loadAllUnknownBoards()") < body.index("WIN_PATH_FORMAT")
    assert body.index("WIN_PATH_FORMAT") < body.index("LOSE_PATH_FORMAT")

    retreat = top_level_functions(SOURCE)["retreatAnalysis"]
    assert "catch_lo = n_uk" in retreat
    assert "catch_hi = n_uk + n_win" in retreat
    assert "frontier = range(catch_hi, n_all)" in retreat, "深さ0のフロンティアが範囲でない"


def test_the_dictionary_is_dropped_before_the_predecessors_are_allocated() -> None:
    """★ピークを決める一行。

    入次数を数えるのに辞書は要らない (succ には既に連番が入っている) ので、
    pred[] (3.50 GiB) を確保する前に辞書 (24.41 GiB) を捨てられる。
    """
    body = top_level_functions(SOURCE)["retreatAnalysis"]
    assert "del idx" in body, "辞書を捨てていない"
    assert body.index("del idx") < body.index("buildPredecessors("), (
        "前任リストを確保してから辞書を捨てている。ピークが 24 GiB ぶん上がる"
    )


def test_the_counter_is_the_full_out_degree() -> None:
    """cnt[] には出次数そのものを入れる。

    未発見の後続 (全探索を打ち切った dat/ でだけ起きる) も数に入れておくことで、
    その局面の cnt は 0 にならない。#5 の「all_wins にも入らない後続」と同じ扱い。
    """
    body = top_level_functions(SOURCE)["buildSuccessors"]
    assert "append_cnt(nbn)" in body, "cnt が出次数になっていない"
    assert "if nbn > 255:" in body, "bytearray に入らない出次数を検査していない"
    assert "if nbn <= 0:" in body, "未知盤面に終端が混ざる場合を検査していない"


def test_the_parity_decides_win_or_lose() -> None:
    """奇数＝勝ち / 偶数＝負け。結果ビットを持たない代わりにここが効く。"""
    body = top_level_functions(SOURCE)["retreatAnalysis"]
    assert "nd % 2 == 1" in body, "パリティで勝ち負けを決めていない"
    assert 'dtm = bytearray(b"\\xff") * n_all' in body, "未確定が 255 で初期化されていない"


def test_depth_one_merges_the_catches_into_the_frontier() -> None:
    """深さ1は「キャッチ」と「トライ由来の1手勝ち」の2つからなる。

    ログに出すのは後者だけ (前者は前向き探索が既に書いている) だが、
    フロンティアとしては両方を流さないと深さ2が出ない。
    """
    body = top_level_functions(SOURCE)["retreatAnalysis"]
    assert "itertools.chain(range(catch_lo, catch_hi), found)" in body, (
        "深さ1のフロンティアにキャッチが入っていない"
    )
    assert "キャッチ除く" in body, "深さ1のログが #5 と違う"


def test_it_refuses_to_resume_from_a_half_finished_dat() -> None:
    """途中まで進んだ dat/ からは再開できない。黙って違う答えを出させない。"""
    body = top_level_functions(SOURCE)["retreatAnalysis"]
    assert "再開できない" in body
    assert "WIN_PATH_FORMAT.format(3, 0)" in body


def test_no_impl_env_needed() -> None:
    """構成がベースラインと同じなので、ハーネスの既定値でそのまま走る。"""
    assert not (IMPL_DIR / "impl.env").exists()
