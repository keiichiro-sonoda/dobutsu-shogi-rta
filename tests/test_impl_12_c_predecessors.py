"""impl/12_c_predecessors — 前任リストの計数ソートをC側へ移した版。

記録 #11 のあと、単独で最大の段は後退解析の P4「前任リスト」548 秒
(全体の 25.8%、後退解析の 47.5%) だった。中身は純 Python の計数ソートで、
9億3867万辺を2周し、1辺あたり `array` の要素アクセスが4回、さらに未知局面ごとに
`succ` のスライスを作っていた。

`succ` / `succ_off` / `pred` / `pred_off` はどれも `array("I")` の連続バッファなので、
ゼロコピーでCに渡せる。FFI はフェーズ全体で2回 (数える / 散らす)。

⚠️ **P4 の出力は最終成果物からしか検証されない。** オラクルも指紋も `dat/` を見ていて、
`pred` / `pred_off` を直接は見ない。**だからここで Python 版とバイト一致を固定する。**

この版にはもう1つ、記録 #11 の積み残し (C の `-3` を握りつぶす不具合) の修正も入る。
⚠️ **速度のレバーではない**ので、1試行1変数には当たらない。
"""

from __future__ import annotations

import ast
import difflib
import pathlib
import random
from array import array
from ctypes import CDLL, POINTER, c_int32, c_size_t, c_uint32, cast

from conftest import ROOT, chdir, impl_library, load_impl, run_forward

IMPL_DIR = ROOT / "impl" / "12_c_predecessors"
PREV_DIR = ROOT / "impl" / "11_c_seen"
SOURCE = IMPL_DIR / "animal_shogi.py"
PREV_SOURCE = PREV_DIR / "animal_shogi.py"

CHANGED = {"buildPredecessors", "searchNext"}

# 小さいフィクスチャ (等価性テスト用)。本番は 5,000,000
SMALL_BOARD_NUM_MAX = 2000
FORWARD_ROUNDS = 7


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


def code_lines(body: str) -> str:
    """コメント行を除いたコード。罠を警告するコメントに引っかからないため。"""
    return "\n".join(ln for ln in body.splitlines() if not ln.lstrip().startswith("#"))


def test_the_c_only_gains_lines() -> None:
    """C とヘッダは impl/11 に対して純粋な追加。既存の1行も動かさない。

    索引 (indexBuild) も発見済み表 (seenInsert) も指し手生成もそのまま。
    """
    for name in ("animal_shogi.c", "animal_shogi.h"):
        prev = (PREV_DIR / name).read_text(encoding="utf-8").splitlines()
        cur = (IMPL_DIR / name).read_text(encoding="utf-8").splitlines()
        removed = [
            ln[2:]
            for ln in difflib.unified_diff(prev, cur, n=0, lineterm="")
            if ln.startswith("-") and not ln.startswith("---")
        ]
        assert removed == [], f"{name} で impl/11 の行が消えている: {removed[:3]}"
        assert len(cur) > len(prev), f"{name} に計数ソートが入っていない"


def test_the_build_is_untouched() -> None:
    """Makefile は impl/11 とバイト単位で同一 (＝ -O0 のまま)。"""
    assert (IMPL_DIR / "Makefile").read_bytes() == (PREV_DIR / "Makefile").read_bytes(), (
        "impl/12_c_predecessors/Makefile が impl/11 と違う。-O2 は次の試行で1変数として測る"
    )


def test_only_the_two_functions_changed() -> None:
    """変わるのは P4 の入れ物と、展開ループの分岐だけ。"""
    prev = top_level_functions(PREV_SOURCE)
    cur = top_level_functions(SOURCE)
    changed = {n for n in prev if n in cur and cur[n] != prev[n]}
    assert changed == CHANGED, f"想定外の関数が変わっている: {changed ^ CHANGED}"
    assert set(cur) == set(prev), f"関数の顔ぶれが変わっている: {set(cur) ^ set(prev)}"
    # 全探索も後退解析の他の段も今回の対照群
    for name in ("buildSuccessors", "buildIndex", "retreatAnalysis", "loadForwardResult"):
        assert cur[name] == prev[name], f"{name} が impl/11 から変わっている"


def test_the_counting_sort_left_python() -> None:
    """★9.4 億辺を回す Python のループが無いこと。FFI はフェーズで2回。"""
    body = code_lines(top_level_functions(SOURCE)["buildPredecessors"])
    assert "for q in succ" not in body, "まだ Python 側で辺を舐めている"
    assert "cur = pred_off[:n_all]" not in body, "987 MB のカーソル複製が残っている"
    assert body.count("predCount(") == 1 and body.count("predScatter(") == 1, (
        "C の呼び出しが1回ずつでない"
    )
    assert "itemsize != 4" in body, "array('I') が4バイトであることを確かめていない"


def test_the_buffers_stay_alive_while_c_reads_them() -> None:
    """★C に渡している間、succ / succ_off を解放しない。

    解放は呼び出し元 (retreatAnalysis) で、buildPredecessors が返ったあと。
    """
    body = top_level_functions(SOURCE)["buildPredecessors"]
    assert "del succ" not in body, "C に渡すバッファを自分で解放している"
    caller = top_level_functions(SOURCE)["retreatAnalysis"]
    assert caller.index("buildPredecessors(") < caller.index("del succ, succ_off"), (
        "前任リストを作る前に succ を解放している"
    )


def test_an_unknown_return_code_now_raises() -> None:
    """★記録 #11 の積み残し。知らない戻り値を握りつぶさない。

    #11 は `-1` (勝ち) でも `-2` (負け) でもない値が `else` に落ちて
    「未知・初見0件」になり、その局面の後続が探索キューに入らないまま静かに進んだ。
    ⚠️ `-3` を名指しせず、**知らない値は全部落とす**形にする (#8 の buildSuccessors と同じ)。
    """
    body = code_lines(top_level_functions(SOURCE)["searchNext"])
    assert "raise RuntimeError" in body, "知らない戻り値で落ちない"
    assert "後続を作れない" in body, "エラーの文面が無い"
    # ⚠️ 分岐は件数の多い順 (勝ち 140.3M > 未知 99.5M > 負け 7.0M)。
    #    未知を先頭に置くと比較回数がむしろ増える
    assert body.index("nbn == -1") < body.index("nbn >= 0") < body.index("nbn == -2"), (
        "分岐の順が件数の多い順でない"
    )


def test_no_impl_env_needed() -> None:
    """構成がベースラインと同じなので、ハーネスの既定値でそのまま走る。"""
    assert not (IMPL_DIR / "impl.env").exists()


# --------------------------------------------------------------------------
# ここから下はCの計数ソートを実際に動かす
# --------------------------------------------------------------------------


class Pred:
    """impl/12 の .so を計数ソートとして使うための薄い口。"""

    def __init__(self) -> None:
        self.lib = CDLL(str(impl_library("12_c_predecessors")))
        self.lib.predCount.restype = c_int32
        self.lib.predCount.argtypes = (POINTER(c_uint32), c_size_t, c_uint32, POINTER(c_uint32))
        self.lib.predScatter.restype = c_int32
        self.lib.predScatter.argtypes = (
            POINTER(c_uint32),
            c_size_t,
            POINTER(c_uint32),
            c_uint32,
            c_uint32,
            POINTER(c_uint32),
            POINTER(c_uint32),
        )

    @staticmethod
    def ptr(arr: array[int]) -> object:
        return cast(arr.buffer_info()[0], POINTER(c_uint32))

    def build(
        self, succ: array[int], succ_off: array[int], n_all: int
    ) -> tuple[int, array[int] | None, array[int] | None]:
        pred_off = array("I", bytes(4)) * (n_all + 1)
        rc = self.lib.predCount(self.ptr(succ), len(succ), n_all, self.ptr(pred_off))
        if rc != 0:
            return rc, None, None
        pred = array("I", bytes(4)) * len(succ)
        rc = self.lib.predScatter(
            self.ptr(succ),
            len(succ),
            self.ptr(succ_off),
            len(succ_off) - 1,
            n_all,
            self.ptr(pred),
            self.ptr(pred_off),
        )
        return rc, pred, pred_off


def reference(succ: array[int], succ_off: array[int], n_all: int) -> tuple[array[int], array[int]]:
    """impl/11 までの純 Python 版と同じ計数ソート (テストの中の参照実装)。"""
    pred_off = [0] * (n_all + 1)
    for q in succ:
        pred_off[q + 1] += 1
    for i in range(1, n_all + 1):
        pred_off[i] += pred_off[i - 1]
    cur = pred_off[:n_all]
    pred = [0] * len(succ)
    for src in range(len(succ_off) - 1):
        for q in succ[succ_off[src] : succ_off[src + 1]]:
            pred[cur[q]] = src
            cur[q] += 1
    return array("I", pred), array("I", pred_off)


def random_csr(
    rng: random.Random, n_uk: int, n_all: int, max_deg: int = 6
) -> tuple[array[int], array[int]]:
    """未知局面 n_uk 個が n_all 個の局面のどれかへ張る、適当な CSR を作る。"""
    succ = array("I")
    succ_off = array("I", bytes(4))
    total = 0
    for _ in range(n_uk):
        for _ in range(rng.randint(0, max_deg)):
            succ.append(rng.randrange(n_all))
            total += 1
        succ_off.append(total)
    return succ, succ_off


def test_the_c_counting_sort_matches_the_python_one() -> None:
    """★同じ CSR から、同じ pred / pred_off がバイト単位で出ること。

    並びが変われば 174段ループの処理順が変わり、成果物のチャンクの中身も動く。
    """
    pred = Pred()
    rng = random.Random(20260920)
    for n_uk, n_all in ((1, 2), (50, 120), (3000, 9000)):
        succ, succ_off = random_csr(rng, n_uk, n_all)
        rc, got, got_off = pred.build(succ, succ_off, n_all)
        assert rc == 0, f"C 版が失敗した: {rc}"
        assert got is not None and got_off is not None
        want, want_off = reference(succ, succ_off, n_all)
        assert got_off.tobytes() == want_off.tobytes(), f"pred_off が違う (n_uk={n_uk})"
        assert got.tobytes() == want.tobytes(), f"pred が違う (n_uk={n_uk})"
        assert got_off[n_all] == len(succ), "総数が合わない"


def test_an_edge_out_of_range_is_refused() -> None:
    """★範囲外の後続番号を書き込ませない (他の配列を壊す)。"""
    pred = Pred()
    succ = array("I", [0, 5])
    succ_off = array("I", [0, 2])
    rc, _, _ = pred.build(succ, succ_off, 3)  # 5 は n_all=3 の外
    assert rc == -2, f"範囲外を受け入れてしまった: {rc}"


def test_a_broken_offset_table_is_refused() -> None:
    """★succ_off の終端が辺の数と合わなければ落ちる。"""
    pred = Pred()
    succ = array("I", [0, 1, 2])
    succ_off = array("I", [0, 2])  # 終端が 2 で、辺は 3 本
    pred_off = array("I", bytes(4)) * 4
    assert pred.lib.predCount(Pred.ptr(succ), len(succ), 3, Pred.ptr(pred_off)) == 0
    pred_arr = array("I", bytes(4)) * len(succ)
    rc = pred.lib.predScatter(
        Pred.ptr(succ),
        len(succ),
        Pred.ptr(succ_off),
        len(succ_off) - 1,
        3,
        Pred.ptr(pred_arr),
        Pred.ptr(pred_off),
    )
    assert rc == -2, f"壊れたオフセット表を受け入れてしまった: {rc}"


def test_the_empty_graph_is_handled() -> None:
    """辺が1本も無い CSR (小さいフィクスチャで起きうる)。"""
    pred = Pred()
    succ = array("I")
    succ_off = array("I", [0, 0, 0])
    rc, got, got_off = pred.build(succ, succ_off, 2)
    assert rc == 0
    assert got is not None and got_off is not None
    assert len(got) == 0
    assert got_off.tobytes() == (array("I", bytes(4)) * 3).tobytes()


def test_the_real_pipeline_matches_impl_11(
    shared_library: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """★本物の `succ` / `succ_off` で、impl/11 の純 Python 版とバイト一致すること。

    小さく全探索して CSR を作り、同じ配列を両方の実装に通す。
    ⚠️ ここだけが `pred` を直接見る検査 (オラクルも指紋も dat/ しか見ない)。
    """
    work12 = tmp_path / "12"
    mod12 = load_impl("12_c_predecessors", work12, shared_library)
    run_forward(mod12, work12, FORWARD_ROUNDS, SMALL_BOARD_NUM_MAX)
    with chdir(work12):
        packed, n_uk, _n_win, _n_lose = mod12.loadForwardResult()
        n_all = len(packed)
        mod12.buildIndex(packed)
        succ, succ_off, _cnt = mod12.buildSuccessors(n_uk)
        mod12.indexFree()
        got, got_off = mod12.buildPredecessors(succ, succ_off, n_all)
    assert len(succ) > 1000, "辺が少なすぎる (テストが空振り)"

    work11 = tmp_path / "11"
    mod11 = load_impl("11_c_seen", work11, shared_library)
    with chdir(work11):
        want, want_off = mod11.buildPredecessors(succ, succ_off, n_all)

    assert got_off.tobytes() == want_off.tobytes(), "pred_off が impl/11 と違う"
    assert got.tobytes() == want.tobytes(), "pred が impl/11 と違う"
