"""impl/08_c_index — パック値 → 連番 の索引をC側へ移した版。

#7 までの後退解析は Python の `dict` で照合していた。2.4 億件で 24.41 GiB に
膨らんでキャッシュに全く乗らず、1回の引きに約 0.85 µs かかる。P1 (167 s) と
P2 (1,035 s) を合わせて後退解析の 55.8% がこの照合に消えていた。

C側にオープンアドレス法の平坦な表を置けば本番で 8.59 GB に収まり、
1回の引きで触るキャッシュラインが1本で済む。

⚠️ **辺ごとに ctypes を呼んではいけない。** 呼び出し1回が約 1 µs なので、
9.4 億本に個別に呼ぶと辞書引きより遅くなる。照合は既存の1回の呼び出し
(未知盤面ごと = 99,485,568 回) の中で完結させる。

⚠️ **衝突処理のバグは静かに間違った連番を返す。** 構造テストでは見つからないので、
ここでは C の索引を実際に動かして Python の `dict` と突き合わせる。
全規模の検算は門番 G1 (オラクル174行) で行う。
"""

from __future__ import annotations

import ast
import difflib
import pathlib
from array import array
from ctypes import CDLL, POINTER, c_int32, c_uint32, c_uint64, cast

from conftest import BASELINE_DIR, ROOT, impl_library, load_impl

IMPL_DIR = ROOT / "impl" / "08_c_index"
SOURCE = IMPL_DIR / "animal_shogi.py"
PREV_SOURCE = ROOT / "impl" / "07_batch_forward_write" / "animal_shogi.py"

CHANGED = {"buildIndex", "buildSuccessors", "retreatAnalysis"}

# 全探索は今回の対照群。1バイトも動かさない
UNTOUCHED_FORWARD = (
    "searchNext",
    "searchAll",
    "buildSeenBoards",
    "updateUKFile",
    "flushTerminalBoards",
    "writeWLFilesForDepth",
    "nextBoardInvNormalWrap",
    "writeAndBackup",
    "s2hms",
    "main",
)

# 後退解析でも、今回の変数に入らないものはそのまま
UNTOUCHED_RETREAT = (
    "appendFamily",
    "loadForwardResult",
    "buildPredecessors",
    "loadAllUnknownBoards",
    "writeUnknownChunks",
)

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


def test_the_c_only_gains_lines() -> None:
    """C とヘッダは baseline に対して純粋な追加。既存の1行も動かさない。

    ここが崩れると「指し手生成そのものを変えたのか、照合だけ変えたのか」が
    言えなくなる。
    """
    for name in ("animal_shogi.c", "animal_shogi.h"):
        base = (BASELINE_DIR / name).read_text(encoding="utf-8").splitlines()
        cur = (IMPL_DIR / name).read_text(encoding="utf-8").splitlines()
        removed = [
            ln[2:]
            for ln in difflib.unified_diff(base, cur, n=0, lineterm="")
            if ln.startswith("-") and not ln.startswith("---")
        ]
        assert removed == [], f"{name} で baseline の行が消えている: {removed[:3]}"
        assert len(cur) > len(base), f"{name} に索引が入っていない"


def test_the_build_is_untouched() -> None:
    """Makefile はベースラインとバイト単位で同一 (＝ -O0 のまま)。

    ⚠️ C の比率が上がるので -O2 は効くはずだが、それは次の試行。
    ここで一緒に変えると2変数になる。
    """
    assert (IMPL_DIR / "Makefile").read_bytes() == (BASELINE_DIR / "Makefile").read_bytes(), (
        "impl/08_c_index/Makefile がベースラインと違う。"
        "索引の効果とビルドフラグの効果が分離できなくなる"
    )


def test_only_the_index_changed() -> None:
    """全探索が1バイトも動いていないこと。これが対照群の担保になる。"""
    prev = top_level_functions(PREV_SOURCE)
    cur = top_level_functions(SOURCE)
    changed = {n for n in prev if n in cur and cur[n] != prev[n]}
    assert changed == CHANGED, f"想定外の関数が変わっている: {changed ^ CHANGED}"
    assert set(cur) - set(prev) == set(), f"想定外の関数が増えている: {set(cur) - set(prev)}"
    assert set(prev) - set(cur) == set(), f"想定外の関数が消えている: {set(prev) - set(cur)}"

    for name in UNTOUCHED_FORWARD + UNTOUCHED_RETREAT:
        assert cur[name] == prev[name], f"{name} が impl/07 から変わっている"


def test_the_ffi_is_called_once_per_unknown_board() -> None:
    """★辺ごとに ctypes を呼んだら負ける。

    呼び出し1回が約 1 µs、辞書引きが約 0.85 µs なので、9.4 億本に
    個別に呼ぶと今より遅くなる。呼び出しは未知盤面ごとの1回だけ。
    """
    body = top_level_functions(SOURCE)["buildSuccessors"]
    tree = ast.parse(body.strip())
    calls = [
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    assert calls.count("nbi") == 1, "C の呼び出しが1か所でない"
    assert "nextBoardInvNormalWrap" not in body, "まだ Python 側で指し手を受け取っている"


def test_the_successors_cross_the_boundary_as_bytes() -> None:
    """★記録 #1 とまったく同じ罠。

    ctypes 配列のスライスは PyLong を n 個作る。9.4 億個ぶん作ったら
    C側に移した意味が消える。memoryview 経由でバイト列のまま繋ぐ。
    """
    body = top_level_functions(SOURCE)["buildSuccessors"]
    assert "frombytes(" in body, "バイト列のまま繋いでいない"
    assert 'memoryview(out).cast("B")' in body, "memoryview を作っていない"
    # 罠そのものを警告するコメントに引っかからないよう、コードの行だけ見る
    code = "\n".join(ln for ln in body.splitlines() if not ln.lstrip().startswith("#"))
    assert "succ.extend(" not in code, "ctypes のスライスから list を作っている (記録 #1 の罠)"
    assert "out[:" not in code, "ctypes のスライスを取っている (記録 #1 の罠)"


def test_the_buffer_is_allocated_once() -> None:
    """受け取り用の配列はループの外で1回だけ。

    呼び出しごとに確保すると 99,485,568 回ぶん効く (梯子の別レバー)。
    """
    body = top_level_functions(SOURCE)["buildSuccessors"]
    assert body.index("c_uint32_array50()") < body.index("for i in range(n_uk)"), (
        "バッファをループの中で確保している"
    )


def test_the_index_is_freed_before_the_predecessors_are_allocated() -> None:
    """★ピークを決める一行。#6 の `del idx` と同じ位置。"""
    body = top_level_functions(SOURCE)["retreatAnalysis"]
    assert "indexFree()" in body, "索引を捨てていない"
    assert body.index("indexFree()") < body.index("buildPredecessors("), (
        "前任リストを確保してから索引を捨てている。索引と前任配列が同時に常駐する"
    )


def test_the_out_of_index_successors_are_tolerated() -> None:
    """索引外の後続は、辺を張らずに出次数にだけ数える。

    ⚠️ ここで落とすと、全探索を打ち切った dat/ を使う等価性テスト
    (tests/test_retreat_analysis_equivalence.py) が通らなくなる。
    本走では「未発見の後続 0」がログに出るので、検出力は落ちない。
    """
    body = top_level_functions(SOURCE)["buildSuccessors"]
    assert "n == -2" in body, "索引外の後続を扱っていない"
    assert "outside += degree - n_found" in body, "索引外のぶんを数えていない"
    assert "未発見の後続" in body, "ログの書式が #6・#7 と違う"


def test_no_impl_env_needed() -> None:
    """構成がベースラインと同じなので、ハーネスの既定値でそのまま走る。"""
    assert not (IMPL_DIR / "impl.env").exists()


# --------------------------------------------------------------------------
# ここから下は C の索引を実際に動かす。
# 衝突処理のバグは静かに間違った連番を返すので、構造テストでは見つからない。
# --------------------------------------------------------------------------


class Index:
    """impl/08 の .so を索引として使うための薄い口。"""

    def __init__(self) -> None:
        self.lib = CDLL(str(impl_library("08_c_index")))
        self.lib.nextBoardInvNormal.restype = c_int32
        self.lib.nextBoardInvNormal.argtypes = (c_uint64, c_uint64 * 48)
        self.lib.indexBuild.restype = c_int32
        self.lib.indexBuild.argtypes = (POINTER(c_uint64), c_uint32)
        self.lib.indexFree.restype = None
        self.lib.nextBoardIndexNormal.restype = c_int32
        self.lib.nextBoardIndexNormal.argtypes = (c_uint32, c_uint32 * 50)
        self.buf = (c_uint64 * 48)()
        self.out = (c_uint32 * 50)()

    def build(self, packed: array[int]) -> int:
        ptr = cast(packed.buffer_info()[0], POINTER(c_uint64))
        return int(self.lib.indexBuild(ptr, len(packed)))

    def successors(self, board: int) -> tuple[int, list[int]]:
        n = int(self.lib.nextBoardInvNormal(c_uint64(board), self.buf))
        return n, list(self.buf[:n]) if n > 0 else []


def collect_boards(index: Index, limit: int) -> list[int]:
    """初期局面から幅優先で盤面を集める。終端も集合には入れる。"""
    seen = {INITIAL_BOARD}
    order = [INITIAL_BOARD]
    frontier = [INITIAL_BOARD]
    while frontier and len(order) < limit:
        nxt: list[int] = []
        for b in frontier:
            for nb in index.successors(b)[1]:
                if nb not in seen:
                    seen.add(nb)
                    order.append(nb)
                    nxt.append(nb)
        frontier = nxt
    return order


def test_the_c_index_agrees_with_a_python_dict() -> None:
    """★本物の盤面で、C の索引が dict と同じ連番を返すこと。

    線形探査の折り返しと番兵の扱いを間違えると、ここで食い違う。
    索引外の後続 (-2) の経路も通る。
    """
    index = Index()
    boards = collect_boards(index, 60000)
    assert len(boards) > 50000, "盤面が集まっていない (テストが空振り)"
    packed = array("Q", boards)
    assert index.build(packed) == 0, "索引を作れない"

    idx = {v: i for i, v in enumerate(packed)}
    terminals = outside = checked = 0
    for i, board in enumerate(boards):
        n = int(index.lib.nextBoardIndexNormal(i, index.out))
        degree, successors = index.successors(board)
        want = [idx[b] for b in successors if b in idx]
        if degree <= 0:
            assert n == degree, f"{i} 番目の終端の扱いが違う"
            terminals += 1
            continue
        if n == -2:
            n_found, reported_degree = index.out[48], index.out[49]
            assert reported_degree == degree, f"{i} 番目の出次数が違う"
            assert n_found == len(want), f"{i} 番目の引けた数が違う"
            got = list(index.out[:n_found])
            outside += degree - n_found
        else:
            assert n == degree, f"{i} 番目の後続数が違う"
            got = list(index.out[:n])
        assert got == want, f"{i} 番目の連番が dict と違う"
        checked += 1
    index.lib.indexFree()
    assert terminals > 0, "終端を1つも通っていない (テストが空振り)"
    assert outside > 0, "索引外の後続を1つも通っていない (テストが空振り)"
    assert checked > 40000


def test_the_index_refuses_duplicate_keys() -> None:
    """重複があると連番が全単射にならない。

    #6・#7 の `if len(idx) != len(packed): raise` に相当する検算で、
    3群が互いに素であることの保証になっている。
    """
    index = Index()
    assert index.build(array("Q", [11, 22, 11])) == -5, "重複を検出できない"
    assert index.build(array("Q", [11, 22, 33])) == 0, "重複が無いのに作れない"
    index.lib.indexFree()


def test_the_index_refuses_the_sentinel_value() -> None:
    """空きスロットの番兵と同じ値が入力にあると、その局面を引けなくなる。"""
    index = Index()
    assert index.build(array("Q", [11, 0xFFFFFFFFFFFFFFFF])) == -4, "番兵を検出できない"
    index.lib.indexFree()


def test_it_refuses_to_generate_successors_without_an_index() -> None:
    """索引が無いまま呼ばれたら -3。黙って 0 を返させない。"""
    index = Index()
    index.lib.indexFree()
    assert int(index.lib.nextBoardIndexNormal(0, index.out)) == -3


def test_the_index_grows_with_the_input() -> None:
    """スロット数は件数に合わせる。

    ⚠️ 2^29 固定にすると、数千件の等価性テストでも 8.59 GB を掴む。
    本番の 246,803,167 件では結局 2^29 (占有率 0.46) になる。
    """
    header = (IMPL_DIR / "animal_shogi.h").read_text(encoding="utf-8")
    assert "INDEX_MAX_BITS" in header, "スロット数が可変になっていない"
    body = (IMPL_DIR / "animal_shogi.c").read_text(encoding="utf-8")
    assert "(size_t)n * 2" in body, "占有率 0.5 以下を選んでいない"


def test_each_impl_gets_its_own_shared_library(
    shared_library: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """★#7 を読んだあとに #8 を読んでも、#8 の .so が使われること。

    ⚠️ glibc の dlopen は「名前の文字列」で読み込み済みを引き当てる。
    どの実装も `CDLL("./animal_shogi.so")` と書くので、閉じずに次を読むと
    **1つめに読み込んだ .so** が返る。#7 までは C がどれもバイト同一だった
    ので害が出なかった。ここが壊れると #8 が baseline の C で動く。
    """
    load_impl("07_batch_forward_write", tmp_path / "prev", shared_library)
    module = load_impl("08_c_index", tmp_path / "cur", shared_library)
    assert module.lib.indexBuild is not None, "impl/08 が自分の .so を掴んでいない"
