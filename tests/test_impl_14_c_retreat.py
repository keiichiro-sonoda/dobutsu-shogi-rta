"""impl/14_c_retreat — 174段ループをC側へ移した版。

記録 #13 のあと、単独で最大の段は後退解析の174段ループだった
(`results/13_c_expand/main.log` から 266〜302 秒)。中身は辺 938,671,869 本を
1本ずつ辿る純 Python の二重ループで、未知局面ごとに
`pred[pred_off[q]:pred_off[q + 1]]` のスライスを作っていた。

⚠️ この版でいちばん壊れやすいのは速度ではなく順序。`found` の並びがそのまま
`dat/` のバイト列を決める (`writeWLFilesForDepth` が `set(...)` に包んで pickle する)。

`docs/review-checklist.md` の「C と Python をまたぐところ」を全部通す:
2回目の呼び出し・空入力・エラー経路・同じ量を2か所から取れないこと。
"""

from __future__ import annotations

import ast
import difflib
import hashlib
import pathlib
import re
import shutil
from array import array
from ctypes import CDLL, POINTER, c_int32, c_ubyte, c_uint32, c_uint64, cast

import pytest
from conftest import ROOT, impl_library, load_impl, run_forward, run_retreat

IMPL_DIR = ROOT / "impl" / "14_c_retreat"
PREV_DIR = ROOT / "impl" / "13_c_expand"
SOURCE = IMPL_DIR / "animal_shogi.py"
PREV_SOURCE = PREV_DIR / "animal_shogi.py"

CHANGED = {"retreatAnalysis"}

SMALL_BOARD_NUM_MAX = 2000
FORWARD_ROUNDS = 7

UNDECIDED = 255
INITIAL_BOARD = 0x000A003C914B002


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


def c_code(text: str) -> str:
    """C からコメントを落とす。

    ⚠️ 規約を説明したコメントは、その規約が探している語をそのまま含んでいる
    (`docs/review-checklist.md` の「規約を書いた文が、その規約で落ちる」)。
    「早期 return より前にリセットを置く」と書いたコメントの `return` を
    拾ってしまったので、検査はコードだけを見る。
    """
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return "\n".join(ln.split("//", 1)[0] for ln in text.splitlines())


# --------------------------------------------------------------------------
# 構造
# --------------------------------------------------------------------------


def test_the_c_only_gains_lines() -> None:
    """C とヘッダは impl/13 に対して純粋な追加。既存の1行も動かさない。"""
    for name in ("animal_shogi.c", "animal_shogi.h"):
        prev = (PREV_DIR / name).read_text(encoding="utf-8").splitlines()
        cur = (IMPL_DIR / name).read_text(encoding="utf-8").splitlines()
        removed = [
            ln[2:]
            for ln in difflib.unified_diff(prev, cur, n=0, lineterm="")
            if ln.startswith("-") and not ln.startswith("---")
        ]
        assert removed == [], f"{name} で impl/13 の行が消えている: {removed[:3]}"
        assert len(cur) > len(prev), f"{name} に174段ループが入っていない"


def test_the_build_is_untouched() -> None:
    """Makefile は impl/13 とバイト単位で同一 (＝ -O0 のまま)。"""
    assert (IMPL_DIR / "Makefile").read_bytes() == (PREV_DIR / "Makefile").read_bytes(), (
        "impl/14_c_retreat/Makefile が impl/13 と違う。-O2 は別の試行で1変数として測る"
    )


def test_no_impl_env_needed() -> None:
    assert not (IMPL_DIR / "impl.env").exists(), "既定のビルド・実行コマンドで走るはず"


def test_only_the_retreat_loop_changed() -> None:
    """変わるのは retreatAnalysis だけ。全探索も P0〜P4 も今回の対照群。"""
    prev = top_level_functions(PREV_SOURCE)
    cur = top_level_functions(SOURCE)
    changed = {n for n in prev if n in cur and cur[n] != prev[n]}
    assert changed == CHANGED, f"想定外の関数が変わっている: {changed ^ CHANGED}"
    assert set(cur) == set(prev), f"関数の顔ぶれが変わっている: {set(cur) ^ set(prev)}"
    for name in (
        "searchNext",
        "searchAll",
        "buildSuccessors",
        "buildPredecessors",
        "buildIndex",
        "loadForwardResult",
        "writeWLFilesForDepth",
    ):
        assert cur[name] == prev[name], f"{name} が impl/13 から変わっている"


def test_the_edge_walk_left_python() -> None:
    """★9.4 億辺を回す Python の二重ループが無いこと。"""
    body = code_lines(top_level_functions(SOURCE)["retreatAnalysis"])
    assert "for p in pred[pred_off[q]" not in body, "まだ Python 側で辺を舐めている"
    assert body.count("retreatStep(") == 1, "C の呼び出しが1か所でない"
    assert "from_buffer_copy" not in body, "写しを渡すと引き分けの書き出しが壊れる"
    assert "from_buffer(" in body, "dtm / cnt を書き込み可能なまま渡していない"


def test_an_error_from_c_raises() -> None:
    """★戻り値を握りつぶさない (記録 #11・#13 と同じ家族の不具合を作らない)。"""
    body = code_lines(top_level_functions(SOURCE)["retreatAnalysis"])
    assert "if rc != 0:" in body and "raise RuntimeError" in body, "戻り値を確かめていない"


def test_the_c_keeps_no_state_between_calls() -> None:
    """★C 側に static を置かない。

    記録 #13 の不具合は、呼び出しをまたいで残る件数を早期 return が
    リセットし損ねたもの。static が無ければその形は起こりようがない。
    """
    csrc = c_code((IMPL_DIR / "animal_shogi.c").read_text(encoding="utf-8"))
    step = csrc[csrc.index("int retreatStep(") :]
    assert "static" not in step, "retreatStep が static を持っている"
    # out[0] のリセットは、out が NULL でないと分かった直後に来ること。
    # NULL 検査だけは書き込みより前に要るので、そこが唯一の例外になる
    head, sep, rest = step.partition("if (!out) return -1;")
    assert sep, "out の NULL 検査が無い"
    assert "return" not in head, "NULL 検査より前に return がある"
    assert rest.index("out[0] = 0;") < rest.index("return"), (
        "リセットが早期 return の後ろにある (記録 #13 と同じ形)"
    )


def test_the_expansion_defect_of_impl_13_is_still_here() -> None:
    """★記録 #13 の既知の不具合が、この版にもそのまま残っていることを固定する。

    impl/14 の C は impl/13 への純粋な追加で、`expandRound` は1行も動かして
    いない。`n == 0` の早期 return が `g_exp_n = 0` より前にあるままなので、
    空入力のラウンドで `expandNewCount()` が**前のラウンドの値**を返す。
    Python 側はそれを見て初見の後続を読むので、同じ局面がもう一度未探索盤面に積まれる。

    ⚠️ 記録 #14 の本走に空入力のラウンドは無く、成果物は #13 とバイト一致している
    ので記録への影響は無い。impl/14 は凍結なので、直すのは次の実装
    (CLAUDE.md の「次の実装で必ず直すもの」)。
    """
    lib = CDLL(str(impl_library("14_c_retreat")))
    lib.seenInit.restype = c_int32
    lib.seenInit.argtypes = ()
    lib.seenFree.restype = None
    lib.seenFree.argtypes = ()
    lib.expandRound.restype = c_int32
    lib.expandRound.argtypes = (
        POINTER(c_uint64),
        c_uint32,
        POINTER(c_uint64),
        POINTER(c_uint64),
        POINTER(c_uint64),
        POINTER(c_uint64),
    )
    lib.expandNewCount.restype = c_uint64
    lib.expandNewCount.argtypes = ()
    lib.expandFreeBuffer.restype = None
    lib.expandFreeBuffer.argtypes = ()

    def ptr(a: array[int]) -> object:
        return cast(a.buffer_info()[0], POINTER(c_uint64))

    def one_round(boards: list[int]) -> int:
        n = len(boards)
        arr = array("Q", boards)
        win = array("Q", bytes(8)) * max(n, 1)
        lose = array("Q", bytes(8)) * max(n, 1)
        uk = array("Q", bytes(8)) * max(n, 1)
        out = array("Q", bytes(8)) * 5
        rc = lib.expandRound(ptr(arr), n, ptr(win), ptr(lose), ptr(uk), ptr(out))
        assert rc == 0, f"expandRound が {rc} を返した"
        return int(lib.expandNewCount())

    assert lib.seenInit() == 0
    try:
        first = one_round([INITIAL_BOARD])
        assert first, "初期局面から後続が出ていない (テストが空振り)"
        assert one_round([]) == first, (
            "空入力で初見バッファが 0 に戻っている。直っているなら、この固定と "
            "CLAUDE.md の「次の実装で必ず直すもの」を一緒に畳むこと"
        )
    finally:
        lib.seenFree()
        lib.expandFreeBuffer()


# --------------------------------------------------------------------------
# C を実際に動かす
# --------------------------------------------------------------------------


class Retreat:
    """impl/14 の .so の retreatStep を直に叩く。"""

    def __init__(self, pred: list[int], pred_off: list[int], n_all: int, n_uk: int) -> None:
        self.lib = CDLL(str(impl_library("14_c_retreat")))
        self.lib.retreatStep.restype = c_int32
        self.lib.retreatStep.argtypes = (
            POINTER(c_uint32),
            POINTER(c_uint32),
            POINTER(c_ubyte),
            POINTER(c_ubyte),
            c_uint32,
            c_uint32,
            POINTER(c_uint32),
            c_uint32,
            c_uint32,
            c_ubyte,
            c_int32,
            POINTER(c_uint32),
            c_uint32,
            POINTER(c_uint32),
        )
        self.pred = array("I", pred)
        self.pred_off = array("I", pred_off)
        self.n_all = n_all
        self.n_uk = n_uk

    def run(
        self,
        dtm: bytearray,
        cnt: bytearray,
        frontier: array[int] | None,
        lo: int,
        hi: int,
        nd: int,
        odd: int,
        found: array[int],
        cursor: int,
        cap: int | None = None,
    ) -> tuple[int, int]:
        out = array("I", bytes(4))

        def p(a: array[int]) -> object:
            return cast(a.buffer_info()[0], POINTER(c_uint32))

        rc = self.lib.retreatStep(
            p(self.pred),
            p(self.pred_off),
            (c_ubyte * len(dtm)).from_buffer(dtm),
            (c_ubyte * len(cnt)).from_buffer(cnt),
            self.n_all,
            self.n_uk,
            p(frontier) if frontier is not None else None,
            lo,
            hi,
            nd,
            odd,
            cast(found.buffer_info()[0] + 4 * cursor, POINTER(c_uint32)),
            (len(found) - cursor) if cap is None else cap,
            p(out),
        )
        return rc, out[0]


# 小さな有向グラフ。局面 0,1 が未知 (後続を持つ)、2,3 が終端
#   0 -> 2, 3    1 -> 2
# 前任は  pred[2] = [0, 1],  pred[3] = [0]
SMALL_N_ALL = 4
SMALL_N_UK = 2
SMALL_PRED = [0, 1, 0]  # q=2 の前任 2件, q=3 の前任 1件
SMALL_PRED_OFF = [0, 0, 0, 2, 3]  # q=0,1 は前任なし / q=2 は [0,2) / q=3 は [2,3)


@pytest.fixture
def small() -> Retreat:
    return Retreat(SMALL_PRED, SMALL_PRED_OFF, SMALL_N_ALL, SMALL_N_UK)


def fresh() -> tuple[bytearray, bytearray, array[int]]:
    dtm = bytearray([UNDECIDED, UNDECIDED, 0, 0])
    cnt = bytearray([2, 1])
    return dtm, cnt, array("I", bytes(4)) * SMALL_N_UK


def test_the_range_mode_walks_the_frontier(small: Retreat) -> None:
    """frontier が NULL なら [lo, hi) そのものをフロンティアにする。"""
    dtm, cnt, found = fresh()
    rc, n = small.run(dtm, cnt, None, 2, 4, 1, 0, found, 0)
    assert rc == 0
    # q=2 の前任 0,1 が確定し、q=3 の前任 0 は既に確定済みなので増えない
    assert (n, list(found[:n])) == (2, [0, 1])
    assert bytes(dtm) == bytes([1, 1, 0, 0])


def test_the_list_mode_walks_the_given_array(small: Retreat) -> None:
    """frontier があれば frontier[lo..hi-1] を見る。"""
    dtm, cnt, found = fresh()
    rc, n = small.run(dtm, cnt, array("I", [9, 3, 9]), 1, 2, 1, 0, found, 0)
    assert rc == 0
    assert (n, list(found[:n])) == (1, [0]), "lo/hi の外を見ている"
    assert bytes(dtm) == bytes([1, UNDECIDED, 0, 0])


def test_an_empty_frontier_writes_nothing(small: Retreat) -> None:
    """★空入力。lo == hi で何も起きず、out も 0 になること。"""
    dtm, cnt, found = fresh()
    for frontier in (None, array("I", [2, 3])):
        rc, n = small.run(dtm, cnt, frontier, 1, 1, 1, 0, found, 0)
        assert (rc, n) == (0, 0)
    assert bytes(dtm) == bytes([UNDECIDED, UNDECIDED, 0, 0]), "空入力で dtm が動いた"


def test_a_second_call_does_not_inherit_the_first(small: Retreat) -> None:
    """★2回目の呼び出し。1回目の結果が out に残らないこと。

    記録 #13 の不具合は、1回目だけを見るテストが素通りしていた形だった。
    """
    dtm, cnt, found = fresh()
    rc, n1 = small.run(dtm, cnt, None, 2, 4, 1, 0, found, 0)
    assert (rc, n1) == (0, 2)
    # 2回目は全部確定済みなので 0 件。前回の 2 が残っていないこと
    rc, n2 = small.run(dtm, cnt, None, 2, 4, 3, 0, found, n1)
    assert (rc, n2) == (0, 0), "前の呼び出しの件数が残っている"
    # 空入力でも同じ
    rc, n3 = small.run(dtm, cnt, None, 1, 1, 3, 0, found, n1)
    assert (rc, n3) == (0, 0), "空入力で前の件数が返っている"


def test_the_odd_depth_counts_down(small: Retreat) -> None:
    """奇数深さは cnt を1減らし、0 になったものだけ確定させる。"""
    dtm, cnt, found = fresh()
    # q=2 の前任は 0 (cnt 2) と 1 (cnt 1)。1 だけが 0 になる
    rc, n = small.run(dtm, cnt, None, 2, 3, 2, 1, found, 0)
    assert rc == 0
    assert (n, list(found[:n])) == (1, [1])
    assert bytes(cnt) == bytes([1, 0]), "出次数の減らし方が違う"
    assert bytes(dtm) == bytes([UNDECIDED, 2, 0, 0])


def test_it_refuses_to_count_below_zero(small: Retreat) -> None:
    """★0 から減らそうとしたら落とす。

    Python 版は bytearray への代入で ValueError になっていたところ。
    黙って 255 に回すと、その局面は二度と確定しない。
    """
    dtm, cnt, found = fresh()
    cnt[1] = 0
    rc, _ = small.run(dtm, cnt, None, 2, 3, 2, 1, found, 0)
    assert rc == -4, f"0 から減らせてしまった (rc={rc})"


def test_it_refuses_when_found_is_full(small: Retreat) -> None:
    """★容量不足。黙って書き潰さない。"""
    dtm, cnt, found = fresh()
    rc, _ = small.run(dtm, cnt, None, 2, 4, 1, 0, found, 0, cap=1)
    assert rc == -2, f"容量を超えて書けてしまった (rc={rc})"


def test_it_refuses_a_frontier_outside_the_table(small: Retreat) -> None:
    """★範囲違反。pred_off / cnt の外を読み書きしない。"""
    dtm, cnt, found = fresh()
    # 範囲モードで n_all を超える
    rc, _ = small.run(dtm, cnt, None, 2, 5, 1, 0, found, 0)
    assert rc == -1, f"n_all を超える範囲が通った (rc={rc})"
    # リストモードで n_all を超える値
    rc, _ = small.run(dtm, cnt, array("I", [99]), 0, 1, 1, 0, found, 0)
    assert rc == -3, f"n_all を超える q が通った (rc={rc})"


def test_a_predecessor_outside_the_unknown_range_is_refused() -> None:
    """★p >= n_uk。cnt は n_uk 要素しかないので、外を書くと別の何かを潰す。"""
    r = Retreat([3], [0, 0, 1], 2, 1)  # q=1 の前任が 3 (n_uk=1 の外)
    dtm, cnt, found = bytearray([UNDECIDED, 0]), bytearray([1]), array("I", bytes(4))
    rc, _ = r.run(dtm, cnt, None, 1, 2, 1, 0, found, 0)
    assert rc == -3, f"未知の範囲の外の前任が通った (rc={rc})"


# --------------------------------------------------------------------------
# 本物を走らせて impl/13 と突き合わせる
# --------------------------------------------------------------------------


@pytest.mark.parametrize(("rounds", "board_num_max"), [(7, 2000), (14, 3000)])
def test_the_retreat_output_is_byte_identical_to_impl_13(
    tmp_path_factory: pytest.TempPathFactory,
    shared_library: pathlib.Path,
    rounds: int,
    board_num_max: int,
) -> None:
    """★指紋ではなくバイト比較。found の並びが1つでも動けばここで落ちる。

    打ち切った dat/ を1つ作り、同じものを両方の実装に配って後退解析を回す。
    ⚠️ 実装ごとに全探索を回してはいけない (打ち切り時点の集合が反復順に依存する)。
    """
    src = tmp_path_factory.mktemp("fixture")
    module = load_impl("13_c_expand", src, shared_library)
    module.seenInit()
    run_forward(module, src, rounds, board_num_max)

    digests = {}
    logs = {}
    for impl in ("13_c_expand", "14_c_retreat"):
        work = tmp_path_factory.mktemp(f"{impl}_{rounds}")
        m = load_impl(impl, work, shared_library)
        for path in (src / "dat").iterdir():
            shutil.copy(path, work / "dat" / path.name)
        vars(m)["BOARD_NUM_MAX"] = board_num_max
        run_retreat(m, work)
        digests[impl] = {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((work / "dat").iterdir())
        }
        text = (work / "kaiseki_log" / "kaizenkaiseki1.txt").read_text(encoding="utf-8")
        logs[impl] = [ln for ln in text.splitlines() if "盤面総数" in ln]

    a, b = digests["13_c_expand"], digests["14_c_retreat"]
    assert len(a) > 5, "成果物が少なすぎる (テストが空振り)"
    assert sorted(a) == sorted(b), f"ファイルの顔ぶれが違う: {set(a) ^ set(b)}"
    for name in a:
        assert a[name] == b[name], f"{name} のバイト列が impl/13 と違う (found の並びが動いた)"
    assert logs["13_c_expand"] == logs["14_c_retreat"], "手数別の行が impl/13 と違う"
    assert any("キャッチ除く" in ln for ln in logs["14_c_retreat"]), (
        "1手勝ちの別書式が消えている (tools/verify_log.py が読む行)"
    )
