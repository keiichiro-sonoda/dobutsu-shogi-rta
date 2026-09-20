"""impl/13_c_expand — 全探索の展開ループをC側へ移した版。

記録 #12 のあと、単独で最大の段は全探索の F1 展開 454 秒 (全体の 26.2%) だった。
指し手生成そのものは #11 でC側にあり、残っていたのは Python 側の
246,803,167 回ぶんの往復 (FFI 越え・48要素バッファの確保・`nba[:nbn]` の list 生成)。
これをラウンドあたり1回の呼び出しにまとめる。

⚠️ **この版でいちばん壊れやすいのは速度ではなく順序。** 展開順が変わると
未知・未探索チャンクの区切りと中身が動き、採番順を通して後退解析の局所性まで動く。
`#12` と `dat/` がバイト一致することをここで固定する。

指示書は「`unexp_boards.pop()` は末尾から取るので展開順はリストの逆順」としていたが、
`unexp_boards` は list ではなく **`set`** で、`set.pop()` の繰り返しは集合の反復順。
`array("Q", 集合)` の並びがちょうどそれになる。下の検査がその前提を固定する。
"""

from __future__ import annotations

import ast
import difflib
import pathlib
import pickle
import random
from array import array
from ctypes import CDLL, POINTER, c_int32, c_uint32, c_uint64, c_void_p, cast

import pytest
from conftest import ROOT, impl_library, load_impl, run_forward

IMPL_DIR = ROOT / "impl" / "13_c_expand"
PREV_DIR = ROOT / "impl" / "12_c_predecessors"
SOURCE = IMPL_DIR / "animal_shogi.py"
PREV_SOURCE = PREV_DIR / "animal_shogi.py"

# 型が list から array("Q") に変わるので、その値に触る関数だけが変わる
CHANGED = {"searchNext", "updateUKFile", "writeWLFilesForDepth", "flushTerminalBoards", "searchAll"}
REMOVED = {"nextBoardSeenNormalWrap"}

MAX_ACTION_NUM = 48
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


# --------------------------------------------------------------------------
# 構造
# --------------------------------------------------------------------------


def test_the_c_only_gains_lines() -> None:
    """C とヘッダは impl/12 に対して純粋な追加。既存の1行も動かさない。

    索引も発見済み表も指し手生成も計数ソートもそのまま。
    """
    for name in ("animal_shogi.c", "animal_shogi.h"):
        prev = (PREV_DIR / name).read_text(encoding="utf-8").splitlines()
        cur = (IMPL_DIR / name).read_text(encoding="utf-8").splitlines()
        removed = [
            ln[2:]
            for ln in difflib.unified_diff(prev, cur, n=0, lineterm="")
            if ln.startswith("-") and not ln.startswith("---")
        ]
        assert removed == [], f"{name} で impl/12 の行が消えている: {removed[:3]}"
        assert len(cur) > len(prev), f"{name} に展開ループが入っていない"


def test_the_build_is_untouched() -> None:
    """Makefile は impl/12 とバイト単位で同一 (＝ -O0 のまま)。"""
    assert (IMPL_DIR / "Makefile").read_bytes() == (PREV_DIR / "Makefile").read_bytes(), (
        "impl/13_c_expand/Makefile が impl/12 と違う。-O2 は次の試行で1変数として測る"
    )


def test_no_impl_env_needed() -> None:
    assert not (IMPL_DIR / "impl.env").exists(), "既定のビルド・実行コマンドで走るはず"


def test_only_the_container_facing_functions_changed() -> None:
    """変わるのは、勝ち負け未知のコンテナ型に触る関数だけ。"""
    prev = top_level_functions(PREV_SOURCE)
    cur = top_level_functions(SOURCE)
    changed = {n for n in prev if n in cur and cur[n] != prev[n]}
    assert changed == CHANGED, f"想定外の関数が変わっている: {changed ^ CHANGED}"
    assert set(prev) - set(cur) == REMOVED, "消えた関数が想定と違う"
    assert set(cur) - set(prev) == set(), "関数が増えている"
    # 後退解析は今回の対照群。1行も変わっていないこと
    for name in ("buildSuccessors", "buildIndex", "buildPredecessors", "retreatAnalysis"):
        assert cur[name] == prev[name], f"{name} が impl/12 から変わっている"


def test_the_expansion_loop_left_python() -> None:
    """★2.4 億回まわる Python のループが無いこと。FFI はラウンドに1回。"""
    body = code_lines(top_level_functions(SOURCE)["searchNext"])
    assert "while unexp_boards:" not in body, "まだ Python 側で局面を1つずつ取り出している"
    assert "nextBoardSeenNormalWrap" not in body, "局面ごとのラッパーが残っている"
    assert body.count("expandRound(") == 1, "C の呼び出しが1回でない"
    assert "itemsize != 8" in body, "array('Q') が8バイトであることを確かめていない"


def test_an_unknown_return_code_still_raises() -> None:
    """★確保失敗を握りつぶさない (記録 #11 の不具合の再発防止)。

    C 側は -2 (バッファ) と -3 (発見済み表) と -4 (知らない戻り値) を区別して返し、
    Python は 0 以外をすべて落とす。
    """
    body = code_lines(top_level_functions(SOURCE)["searchNext"])
    assert "if rc != 0:" in body and "raise RuntimeError" in body, "戻り値を確かめていない"
    csrc = (IMPL_DIR / "animal_shogi.c").read_text(encoding="utf-8")
    expand = csrc[csrc.index("int expandRound(") :]
    assert "rc = (nbn == -3) ? -3 : -4;" in expand, "知らない戻り値を素通ししている"


def test_the_c_walks_the_input_forwards() -> None:
    """★走査の向き。逆から回すと採番順が変わる (この版の一番の risk)。"""
    csrc = (IMPL_DIR / "animal_shogi.c").read_text(encoding="utf-8")
    expand = csrc[csrc.index("int expandRound(") :]
    assert "for (i = 0; i < n; i++)" in expand, "前から後ろへ走査していない"


# --------------------------------------------------------------------------
# 前提: array("Q", 集合) の並びは set.pop() の繰り返しと同じ
# --------------------------------------------------------------------------


@pytest.mark.parametrize("n", [1, 5, 1000, 50000])
def test_an_array_of_a_set_matches_repeated_pop(n: int) -> None:
    """★この版が成り立つ前提そのもの。

    #12 までの `while unexp_boards: board = unexp_boards.pop()` は `set.pop()` の
    繰り返し。CPython の `set.pop()` はスロットを前から走査するので、取り出す順は
    集合の反復順と一致する。`array("Q", 集合)` の並びがちょうどそれになるので、
    C が前から回せば展開順は #12 と同じになる。

    ⚠️ これは CPython の実装詳細で、言語の保証ではない。だから本走では
    `dat/` のバイト比較でも裏を取る (CLAUDE.md がインタプリタを 3.12 に固定している)。
    """
    rng = random.Random(n)
    values = [rng.getrandbits(60) for _ in range(n)]
    popped_from = set(values)
    popped = [popped_from.pop() for _ in range(len(popped_from))]
    assert list(array("Q", set(values))) == popped, "array の並びが pop の順と違う"
    assert popped == list(set(values)), "pop の順が集合の反復順と違う"


# --------------------------------------------------------------------------
# C を実際に動かす
# --------------------------------------------------------------------------


class Expand:
    """impl/13 の .so を直に叩く。"""

    def __init__(self) -> None:
        self.lib = CDLL(str(impl_library("13_c_expand")))
        self.lib.seenInit.restype = c_int32
        self.lib.seenInit.argtypes = ()
        self.lib.seenFree.restype = None
        self.lib.seenFree.argtypes = ()
        self.lib.seenProbes.restype = c_uint64
        self.lib.seenProbes.argtypes = ()
        self.lib.nextBoardSeenNormal.restype = c_int32
        self.lib.nextBoardSeenNormal.argtypes = (c_uint64, c_uint64 * MAX_ACTION_NUM)
        self.lib.expandRound.restype = c_int32
        self.lib.expandRound.argtypes = (
            POINTER(c_uint64),
            c_uint32,
            POINTER(c_uint64),
            POINTER(c_uint64),
            POINTER(c_uint64),
            POINTER(c_uint64),
        )
        self.lib.expandNewPtr.restype = c_void_p
        self.lib.expandNewPtr.argtypes = ()
        self.lib.expandNewCount.restype = c_uint64
        self.lib.expandNewCount.argtypes = ()
        self.lib.expandFreeBuffer.restype = None
        self.lib.expandFreeBuffer.argtypes = ()
        assert self.lib.seenInit() == 0

    def close(self) -> None:
        self.lib.seenFree()
        self.lib.expandFreeBuffer()

    def round(self, boards: list[int]) -> tuple[int, list[int], list[int], list[int], list[int]]:
        n = len(boards)
        arr = array("Q", boards)
        win = array("Q", bytes(8)) * max(n, 1)
        lose = array("Q", bytes(8)) * max(n, 1)
        uk = array("Q", bytes(8)) * max(n, 1)
        out = array("Q", bytes(8)) * 5

        def ptr(a: array[int]) -> object:
            return cast(a.buffer_info()[0], POINTER(c_uint64))

        rc = self.lib.expandRound(ptr(arr), n, ptr(win), ptr(lose), ptr(uk), ptr(out))
        k = self.lib.expandNewCount()
        new = array("Q")
        if k:
            buf = (c_uint64 * k).from_address(self.lib.expandNewPtr())
            new.frombytes(memoryview(buf).cast("B"))
        return (
            rc,
            list(win[: out[0]]),
            list(lose[: out[1]]),
            list(uk[: out[2]]),
            list(new),
        )


@pytest.fixture
def expand() -> object:
    e = Expand()
    yield e
    e.close()


def test_it_classifies_the_same_way_as_calling_one_board_at_a_time(expand: Expand) -> None:
    """★1局面ずつ呼んだ結果と、まとめて呼んだ結果が一致すること。

    分類も、初見の後続の並びも、生成した後続の延べ数も。
    """
    # 初期局面から数ラウンド広げて、勝ち・負け・未知が混ざった入力を作る
    frontier = [INITIAL_BOARD]
    seen = {INITIAL_BOARD}
    for _ in range(4):
        rc, win, lose, uk, new = expand.round(frontier)
        assert rc == 0
        frontier = [b for b in new if b not in seen]
        seen.update(frontier)
    assert len(frontier) > 50, "入力が小さすぎて検査にならない"
    assert win and uk, "勝ちと未知が両方出ていない"

    # 同じ状態からもう一度。表を作り直して、1局面ずつ呼ぶ側と突き合わせる
    expand.close()
    assert expand.lib.seenInit() == 0
    one_win: list[int] = []
    one_lose: list[int] = []
    one_uk: list[int] = []
    one_new: list[int] = []
    buf = (c_uint64 * MAX_ACTION_NUM)()
    probes0 = expand.lib.seenProbes()
    for b in frontier:
        nbn = expand.lib.nextBoardSeenNormal(b, buf)
        if nbn == -1:
            one_win.append(b)
        elif nbn >= 0:
            one_uk.append(b)
            one_new += buf[:nbn]
        elif nbn == -2:
            one_lose.append(b)
        else:
            raise AssertionError(f"後続を作れない：{nbn}")
    one_probes = expand.lib.seenProbes() - probes0

    expand.close()
    assert expand.lib.seenInit() == 0
    rc, win, lose, uk, new = expand.round(frontier)
    assert rc == 0
    assert win == one_win, "勝ちの並びが1局面ずつ呼んだときと違う"
    assert lose == one_lose, "負けの並びが違う"
    assert uk == one_uk, "未知の並びが違う"
    assert new == one_new, "★初見の後続の並びが違う (採番順が動く)"
    assert len(new) == len(set(new)), "同じ局面を2回返している"
    assert one_probes > len(new), "検算値が取れていない"


def test_an_empty_round_is_allowed(expand: Expand) -> None:
    """空のチャンクは起こりうる (searchNext が unexplored に set() を書く)。

    長さ0の array("Q") の buffer_info() は 0 を返すので、C は NULL を受け取る。
    """
    rc, win, lose, uk, new = expand.round([])
    assert (rc, win, lose, uk, new) == (0, [], [], [], [])


def test_the_buffer_is_reset_at_the_start_of_each_round(expand: Expand) -> None:
    """初見の後続はラウンドごとに積み直す。前のラウンドの残りを足さない。"""
    rc, _, _, _, first = expand.round([INITIAL_BOARD])
    assert rc == 0 and first, "初期局面から後続が出ていない"
    # 2回目は全部既出なので、初見は0件になる
    rc, _, _, uk, second = expand.round([INITIAL_BOARD])
    assert rc == 0 and uk == [INITIAL_BOARD], "未知に入っていない"
    assert second == [], f"前のラウンドの残りが残っている: {second[:3]}"


# --------------------------------------------------------------------------
# 本物を走らせて impl/12 と突き合わせる
# --------------------------------------------------------------------------


@pytest.mark.parametrize(("rounds", "board_num_max"), [(9, 3000), (20, 1000)])
def test_the_forward_output_is_byte_identical_to_impl_12(
    tmp_path_factory: pytest.TempPathFactory,
    shared_library: pathlib.Path,
    rounds: int,
    board_num_max: int,
) -> None:
    """★指紋ではなくバイト比較。順序が1つでも動けばここで落ちる。

    `dat/` に出るものはすべて `set(...)` を通るので、コンテナ型が
    list から array("Q") に変わっても pickle されるオブジェクトの型は変わらない。
    同じ挿入順なら同じ表になり、同じバイト列になる。
    (20 ラウンド / 上限 1000 のほうはチャンク分割を何度も通る)
    """
    digests = {}
    for impl in ("12_c_predecessors", "13_c_expand"):
        work = tmp_path_factory.mktemp(f"{impl}_{rounds}")
        module = load_impl(impl, work, shared_library)
        module.seenInit()
        run_forward(module, work, rounds, board_num_max)
        digests[impl] = {p.name: p.read_bytes() for p in sorted((work / "dat").iterdir())}

    a, b = digests["12_c_predecessors"], digests["13_c_expand"]
    assert len(a) > 10, "探索が進んでいない (テストが空振り)"
    assert sorted(a) == sorted(b), f"ファイルの顔ぶれが違う: {set(a) ^ set(b)}"
    for name in a:
        assert a[name] == b[name], f"{name} のバイト列が impl/12 と違う (展開順が動いた)"


def test_the_unexplored_files_hold_sets(
    tmp_path: pathlib.Path, shared_library: pathlib.Path
) -> None:
    """バイト一致が成り立つ理由。pickle されるのは set のままで、型は変わらない。"""
    module = load_impl("13_c_expand", tmp_path, shared_library)
    module.seenInit()
    run_forward(module, tmp_path, 6, 2000)
    for name in ("unexplored000.pickle", "unknown000.pickle"):
        with (tmp_path / "dat" / name).open("rb") as f:
            assert isinstance(pickle.load(f), set), f"{name} が set でない"
