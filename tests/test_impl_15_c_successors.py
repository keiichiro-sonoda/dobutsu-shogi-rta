"""impl/15_c_successors — P2 後続生成のループをC側へ移した版。

`buildSuccessors()` の 99,485,568 周のループが、プログラムに最後まで残っていた
「局面ごとの FFI 往復」だった。記録 #13 が F1 で潰したのと同じ形。

⚠️ この版でいちばん壊れやすいのは速度ではなく順序。`succ` の並びが CSR を決め、
CSR が P4 の `pred` を決め、`pred` が174段ループの `found` を決め、`found` が
`dat/` のバイト列を決める。4段下流まで効く。

この版には速度のレバーではない修正がもう1つ入る（記録 #13・#14 の `expandRound` が
空入力で初見バッファの件数を戻さない件）。`docs/review-checklist.md` の
「C と Python をまたぐところ」を全部通す:
2回目の呼び出し・空入力・エラー経路・同じ量を2か所から取れないこと。
"""

from __future__ import annotations

import ast
import difflib
import hashlib
import pathlib
import re
import shutil
import types
from array import array
from collections.abc import Iterator
from ctypes import CDLL, POINTER, c_int32, c_int64, c_ubyte, c_uint32, c_uint64, cast
from typing import Any

import pytest
from conftest import ROOT, chdir, impl_library, load_impl, run_forward, run_retreat

IMPL_DIR = ROOT / "impl" / "15_c_successors"
PREV_DIR = ROOT / "impl" / "14_c_retreat"
SOURCE = IMPL_DIR / "animal_shogi.py"
PREV_SOURCE = PREV_DIR / "animal_shogi.py"

CHANGED = {"buildSuccessors"}

# C 側で動かしたのは expandRound のリセット1行とその説明コメントだけ。
# ⚠️ ここを緩めない。増えるぶん (buildSuccRange) は下の行数検査で見る
C_REMOVED = {
    "// ⚠️ 入口で 0 に戻す. 出口で戻すと, 途中で落ちたラウンドの残骸に",
    "//    次のラウンドが積み足してしまう",
    "g_exp_n = 0;",
}

SMALL_BOARD_NUM_MAX = 2000
FORWARD_ROUNDS = 7

MAX_ACTION_NUM = 48
INITIAL_BOARD = 0x000A003C914B002
UINT32_MAX = 0xFFFFFFFF

# (モジュール, 作業ディレクトリ, packed, 未知局面数)
Built = tuple[types.ModuleType, pathlib.Path, array[int], int]


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
    """
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return "\n".join(ln.split("//", 1)[0] for ln in text.splitlines())


def c_function(name: str) -> str:
    """C ソースから、その関数の定義以降をコメント抜きで返す。"""
    csrc = c_code((IMPL_DIR / "animal_shogi.c").read_text(encoding="utf-8"))
    return csrc[csrc.index(f"int {name}(") :]


# --------------------------------------------------------------------------
# 構造
# --------------------------------------------------------------------------


def test_the_c_only_moves_the_expand_reset() -> None:
    """★C で消えた行は expandRound のリセット1行とその説明だけ。

    ⚠️ #14 は impl/13 への純粋な追加だったが、この版は違う。`expandRound` の
    `g_exp_n = 0;` を早期 return より前に出している (CLAUDE.md の
    「次の実装で必ず直すもの」)。消えてよい行をここで名指しで固定する。
    """
    for name in ("animal_shogi.c", "animal_shogi.h"):
        prev = (PREV_DIR / name).read_text(encoding="utf-8").splitlines()
        cur = (IMPL_DIR / name).read_text(encoding="utf-8").splitlines()
        removed = {
            ln[1:].strip()
            for ln in difflib.unified_diff(prev, cur, n=0, lineterm="")
            if ln.startswith("-") and not ln.startswith("---")
        }
        allowed = C_REMOVED if name == "animal_shogi.c" else set()
        assert removed <= allowed, f"{name} で想定外の行が消えている: {removed - allowed}"
        assert len(cur) > len(prev), f"{name} に P2 のループが入っていない"


def test_the_build_is_untouched() -> None:
    """Makefile は impl/14 とバイト単位で同一 (＝ -O0 のまま)。"""
    assert (IMPL_DIR / "Makefile").read_bytes() == (PREV_DIR / "Makefile").read_bytes(), (
        "impl/15_c_successors/Makefile が impl/14 と違う。-O2 は別の試行で1変数として測る"
    )


def test_no_impl_env_needed() -> None:
    assert not (IMPL_DIR / "impl.env").exists(), "既定のビルド・実行コマンドで走るはず"


def test_only_the_successor_loop_changed() -> None:
    """変わるのは buildSuccessors だけ。全探索も P0・P1・P4 も174段も対照群。"""
    prev = top_level_functions(PREV_SOURCE)
    cur = top_level_functions(SOURCE)
    changed = {n for n in prev if n in cur and cur[n] != prev[n]}
    assert changed == CHANGED, f"想定外の関数が変わっている: {changed ^ CHANGED}"
    assert set(cur) == set(prev), f"関数の顔ぶれが変わっている: {set(cur) ^ set(prev)}"
    for name in (
        "searchNext",
        "searchAll",
        "retreatAnalysis",
        "buildPredecessors",
        "buildIndex",
        "loadForwardResult",
        "writeWLFilesForDepth",
    ):
        assert cur[name] == prev[name], f"{name} が impl/14 から変わっている"


def test_the_successor_loop_left_python() -> None:
    """★99,485,568 回の FFI 往復が Python から消えていること。"""
    body = code_lines(top_level_functions(SOURCE)["buildSuccessors"])
    assert "nextBoardIndexNormal" not in body, "まだ局面ごとに C を呼んでいる"
    assert body.count("buildSuccRange(") == 1, "C の呼び出しが1か所でない"
    assert "from_buffer_copy" not in body, "写しを渡すと cnt に出次数が出ない"
    assert "from_buffer(" in body, "cnt を書き込み可能なまま渡していない"


def test_an_error_from_c_raises() -> None:
    """★戻り値を握りつぶさない (記録 #11・#13 と同じ家族の不具合を作らない)。"""
    body = code_lines(top_level_functions(SOURCE)["buildSuccessors"])
    assert "rc == -5" in body, "後続を作れない局面の経路を見ていない"
    assert "if rc != 0:" in body, "それ以外の戻り値を見ていない"
    assert body.count("raise RuntimeError") >= 3, "異常時に上げていない経路がある"


def test_the_c_keeps_no_state_between_calls() -> None:
    """★C 側に static を置かない。カーソルは呼び出し側が持つ。"""
    step = c_function("buildSuccRange")
    assert "static" not in step, "buildSuccRange が static を持っている"
    # out のリセットは、out が NULL でないと分かった直後に来ること。
    # NULL 検査だけは書き込みより前に要るので、そこが唯一の例外になる
    head, sep, rest = step.partition("if (!out) return -1;")
    assert sep, "out の NULL 検査が無い"
    assert "return" not in head, "NULL 検査より前に return がある"
    assert rest.index("out[0] = out[1] = out[2] = out[3] = 0;") < rest.index("return"), (
        "リセットが早期 return の後ろにある (記録 #13 と同じ形)"
    )


def test_the_expand_reset_is_now_first() -> None:
    """★記録 #13・#14 の積み残し。空入力の早期 return より前に戻す。"""
    body = c_function("expandRound")
    body = body[: body.index("\n}")]
    assert body.index("g_exp_n = 0;") < body.index("if (n == 0) return 0;"), (
        "リセットが空入力の早期 return の後ろにある。"
        "CLAUDE.md の「次の実装で必ず直すもの」を見ること"
    )


def test_the_expand_reset_is_still_behind_the_null_check() -> None:
    """★既知の不具合。impl/15 は凍結なので直さず、ここで固定する。

    `g_exp_n = 0;` の前にまだ `if (!out) return -1;` が残っていて、その経路だけは
    前のラウンドの件数がそのまま残る。記録 #13 で直したのと同じ形の生き残り。

    ⚠️ `buildSuccRange` の「NULL 検査だけが例外」という理屈は `out[]` への書き込みに
    しか当てはまらない（書けないポインタには書けないから）。`g_exp_n` は static なので
    `!out` の検査より前に出せる。次の実装では関数の先頭へ出す。

    本走への影響は無い。Python 側は必ず有効な `counts` を渡すので `!out` を通らない。
    """
    body = c_function("expandRound")
    body = body[: body.index("\n}")]
    assert body.index("if (!out) return -1;") < body.index("g_exp_n = 0;"), (
        "NULL 検査より前にリセットが出ている。直っているなら、この固定と "
        "CLAUDE.md の「次の実装で必ず直すもの」を一緒に畳むこと"
    )
    # コメントは「どの早期 return よりも前」と言っているが、実コードはそうなっていない。
    # ⚠️ この食い違いも impl/15 では直せないので、CLAUDE.md 側に書いてある
    assert "どの早期 return よりも前" in (IMPL_DIR / "animal_shogi.c").read_text(
        encoding="utf-8"
    ), "コメントの文面が変わった。CLAUDE.md の積み残しの説明と突き合わせること"


# --------------------------------------------------------------------------
# C を実際に動かす
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def built(
    tmp_path_factory: pytest.TempPathFactory, shared_library: pathlib.Path
) -> Iterator[Built]:
    """小さく打ち切った dat/ を読み込み、索引まで作った状態のモジュール。"""
    work = tmp_path_factory.mktemp("impl15")
    module = load_impl("15_c_successors", work, shared_library)
    module.seenInit()
    run_forward(module, work, FORWARD_ROUNDS, SMALL_BOARD_NUM_MAX)
    module.seenFree()
    module.expandFreeBuffer()
    with chdir(work):
        packed, n_uk, _n_win, _n_lose = module.loadForwardResult()
        module.buildIndex(packed)
    assert n_uk > 100, "未知局面が少なすぎる (テストが空振り)"
    yield module, work, packed, n_uk
    module.indexFree()


def reference(module: types.ModuleType, n_uk: int) -> tuple[array[int], array[int], bytearray, int]:
    """impl/14 までの純 Python のループ。独立した答え合わせに使う。"""
    succ = array("I")
    succ_off = array("I", bytes(4))
    cnt = bytearray()
    out = module.c_uint32_array50()
    mv = memoryview(out).cast("B")
    total = 0
    outside = 0
    for i in range(n_uk):
        n = module.nextBoardIndexNormal(i, out)
        if n > 0:
            succ.frombytes(mv[: 4 * n])
            cnt.append(n)
            total += n
        elif n == -2:
            n_found = out[48]
            degree = out[49]
            succ.frombytes(mv[: 4 * n_found])
            cnt.append(degree)
            total += n_found
            outside += degree - n_found
        else:
            raise AssertionError(f"未知盤面の後続を作れない：{i} 番目 (戻り値 {n})")
        succ_off.append(total)
    return succ, succ_off, cnt, outside


class Range:
    """impl/15 の buildSuccRange を直に叩く。"""

    def __init__(self, module: types.ModuleType, n_uk: int, stage_cap: int) -> None:
        self.module = module
        self.n_uk = n_uk
        self.stage_cap = stage_cap
        self.stage = array("I", bytes(4)) * stage_cap
        self.stage_mv = memoryview(self.stage).cast("B")
        self.stage_ptr = cast(self.stage.buffer_info()[0], POINTER(c_uint32))
        self.succ_off = array("I", bytes(4)) * (n_uk + 1)
        self.succ_off_ptr = cast(self.succ_off.buffer_info()[0], POINTER(c_uint32))
        self.cnt = bytearray(n_uk)
        self.cnt_c = (c_ubyte * n_uk).from_buffer(self.cnt)
        self.out = (c_int64 * 4)()
        self.succ = array("I")
        self.total = 0
        self.outside = 0

    def call(self, lo: int, hi: int, base: int | None = None, **kw: Any) -> int:
        """1回ぶん呼ぶ。書かれたぶんは succ に繋がない (生の戻り値を見るため)。"""
        rc = self.module.buildSuccRange(
            lo,
            hi,
            kw.get("n_uk", self.n_uk),
            kw.get("stage", self.stage_ptr),
            kw.get("cap", self.stage_cap),
            kw.get("succ_off", self.succ_off_ptr),
            kw.get("cnt", self.cnt_c),
            self.total if base is None else base,
            kw.get("out", self.out),
        )
        return int(rc)

    def drive(self, lo: int, hi: int) -> None:
        """buildSuccessors と同じ回し方で lo..hi-1 を処理する。"""
        i = lo
        while i < hi:
            rc = self.call(i, hi)
            assert rc == 0, f"buildSuccRange が {rc} を返した ({i} 番目)"
            self.succ.frombytes(self.stage_mv[: 4 * self.out[0]])
            self.total += self.out[0]
            self.outside += self.out[2]
            assert self.out[1] > i or self.out[1] == hi, (
                "1周も進んでいない (呼び出し側が回り続ける)"
            )
            i = self.out[1]


def test_one_call_matches_the_python_loop(built: Built) -> None:
    """★中継バッファが十分大きければ1回で完走し、答えは純 Python と同じ。"""
    module, _work, _packed, n_uk = built
    want_succ, want_off, want_cnt, want_outside = reference(module, n_uk)
    r = Range(module, n_uk, len(want_succ) + MAX_ACTION_NUM)
    r.drive(0, n_uk)
    assert r.out[1] == n_uk, "1回で終わっていない"
    assert r.succ.tobytes() == want_succ.tobytes(), "succ の並びが違う"
    assert r.succ_off.tobytes() == want_off.tobytes(), "succ_off が違う"
    assert bytes(r.cnt) == bytes(want_cnt), "cnt (出次数) が違う"
    assert r.outside == want_outside, "未発見の後続の数が違う"
    assert want_outside > 0, "打ち切った dat/ なのに -2 の経路を通っていない (テストが空振り)"


def test_a_full_staging_buffer_stops_and_resumes(built: Built) -> None:
    """★中継バッファが一杯になっても、続きから呼び直せば同じ答えになる。

    ⚠️ 1局面ぶん (MAX_ACTION_NUM) しか入らない最小の容量で回す。
    区切りの位置が変わっても succ の並びは変わってはいけない。
    """
    module, _work, _packed, n_uk = built
    want_succ, want_off, want_cnt, want_outside = reference(module, n_uk)
    r = Range(module, n_uk, MAX_ACTION_NUM)
    r.drive(0, n_uk)
    assert r.succ.tobytes() == want_succ.tobytes(), "区切りが変わると succ の並びが動く"
    assert r.succ_off.tobytes() == want_off.tobytes(), "succ_off が違う"
    assert bytes(r.cnt) == bytes(want_cnt), "cnt が違う"
    assert r.outside == want_outside, "未発見の後続の数が違う"


def test_the_pieces_are_walked_in_order(built: Built) -> None:
    """★区間を分けて呼んでも、通しで呼んだのと同じものが同じ順に出る。"""
    module, _work, _packed, n_uk = built
    whole = Range(module, n_uk, 4096)
    whole.drive(0, n_uk)
    cut = n_uk // 3
    parts = Range(module, n_uk, 4096)
    parts.drive(0, cut)
    parts.drive(cut, n_uk)
    assert parts.succ.tobytes() == whole.succ.tobytes(), "区間を分けると並びが動く"
    assert parts.succ_off.tobytes() == whole.succ_off.tobytes(), "succ_off が違う"
    assert bytes(parts.cnt) == bytes(whole.cnt), "cnt が違う"


def test_an_empty_range_writes_nothing(built: Built) -> None:
    """★空区間。lo == hi なら何も書かず、止まった位置は lo のまま。"""
    module, _work, _packed, n_uk = built
    r = Range(module, n_uk, 4096)
    rc = r.call(7, 7)
    assert rc == 0, f"空区間で {rc} を返した"
    assert (r.out[0], r.out[1], r.out[2]) == (0, 7, 0), "空区間なのに何か返している"
    assert bytes(r.cnt) == bytes(n_uk), "空区間なのに cnt を書いている"


def first_board_with_an_edge(module: types.ModuleType, n_uk: int) -> int:
    """辺が1本以上張られる最初の局面。

    ⚠️ 打ち切った dat/ では、先頭の局面の後続が全部索引外ということが起こる
    (このフィクスチャの 0 番目がそうだった)。件数で判定するテストは
    「0 本の局面」を踏むと空振りになる。
    """
    _succ, succ_off, _cnt, _outside = reference(module, n_uk)
    return next(i for i in range(n_uk) if succ_off[i + 1] > succ_off[i])


def test_a_second_call_does_not_inherit_the_first(built: Built) -> None:
    """★2回目の呼び出しが1回目の件数を引きずらない (記録 #13 の不具合の形)。"""
    module, _work, _packed, n_uk = built
    _s, want_off, _c, _o = reference(module, n_uk)
    b = first_board_with_an_edge(module, n_uk)
    # ⚠️ 1回で区間を終える大きさにする。途中で中継バッファが一杯になると
    #    「引きずっていない」ではなく「まだ途中」を見ることになる
    r = Range(module, n_uk, want_off[n_uk] + MAX_ACTION_NUM)

    assert r.call(0, b + 1) == 0
    first = r.out[0]
    assert first == want_off[b + 1] > 0, "1区間目の件数が違う (テストが空振り)"
    r.total += first

    # 空区間をはさんでも、前の区間の件数が返ってこない
    assert r.call(b + 1, b + 1) == 0
    assert r.out[0] == 0, "空区間で前回の件数が返っている"

    assert r.call(b + 1, n_uk) == 0
    assert r.out[0] == want_off[n_uk] - want_off[b + 1], "2区間目の件数が違う"
    assert r.succ_off[b + 1] == want_off[b + 1], "1区間目のオフセットが動いた"
    assert r.succ_off[n_uk] == want_off[n_uk], "base が効いていない"


def test_bad_arguments_are_refused(built: Built) -> None:
    """★引数不正は -1。下流の戻り値 (-1 = トライ負け) と衝突させない。"""
    module, _work, _packed, n_uk = built
    r = Range(module, n_uk, 4096)
    assert r.call(5, 4) == -1, "lo > hi を通している"
    assert r.call(0, n_uk + 1) == -1, "hi > n_uk を通している (succ_off の外を書く)"
    assert r.call(0, 1, cap=MAX_ACTION_NUM - 1) == -1, "1局面も入らない容量を通している"
    assert r.call(0, 1, stage=None) == -1, "中継バッファが NULL でも進んでいる"
    assert r.call(0, 1, succ_off=None) == -1, "succ_off が NULL でも進んでいる"
    assert r.call(0, 1, cnt=None) == -1, "cnt が NULL でも進んでいる"
    assert r.call(0, 1, out=None) == -1, "out が NULL でも進んでいる"


def test_a_board_without_successors_is_refused(built: Built) -> None:
    """★後続を作れない局面は -5。下流の戻り値は out[3] に入れる。

    ⚠️ 索引を解放してから呼ぶと nextBoardIndexNormal が -3 を返す。
    -1 (トライ負け) や 0 (キャッチ) も同じ経路で落ちる。
    """
    module, work, packed, n_uk = built
    r = Range(module, n_uk, 4096)
    module.indexFree()
    try:
        rc = r.call(3, n_uk)
        assert rc == -5, f"索引が無いのに {rc} を返した"
        assert r.out[1] == 3, "落ちた局面番号を返していない"
        assert r.out[3] == -3, f"下流の戻り値を out[3] に入れていない: {r.out[3]}"
        assert r.out[0] == 0, "落ちたのに書いた数を返している"
    finally:
        with chdir(work):
            module.buildIndex(packed)


def test_an_edge_count_over_uint32_is_refused(built: Built) -> None:
    """★辺の総数が uint32 を超えたら -7。黙って巻かせない。"""
    module, _work, _packed, n_uk = built
    r = Range(module, n_uk, 4096)
    # base を上限ちょうどに置くと、辺を1本でも張る最初の局面で溢れる
    rc = r.call(0, n_uk, base=UINT32_MAX)
    assert rc == -7, f"uint32 を溢れる base で {rc} を返した"
    assert r.out[1] == first_board_with_an_edge(module, n_uk), "溢れた局面番号を返していない"
    assert r.out[0] == 0, "落ちたのに書いた数を返している"


def test_the_degree_guard_exists_but_cannot_fire(built: Built) -> None:
    """★出次数が cnt に収まらないときの -6 は、いまの指し手生成では起こらない。

    ⚠️ 実行して起こせないので、ここで固定するのは「検査がコードにあること」と
    「起こらない理由」だけ。テストが通ることを根拠に「通した」と書かない。
    """
    body = c_function("buildSuccRange")
    assert "return -6;" in body, "出次数の検査が無い"
    assert "degree > 255" in body, "cnt (1バイト) に収まるかを見ていない"
    module, _work, _packed, n_uk = built
    out = module.c_uint32_array50()
    worst = max(module.nextBoardIndexNormal(i, out) for i in range(min(n_uk, 3000)))
    assert worst <= MAX_ACTION_NUM, "出次数が MAX_ACTION_NUM を超えた"
    assert MAX_ACTION_NUM <= 255, "MAX_ACTION_NUM が 255 を超えたら -6 が起きうる"


def test_the_expansion_defect_of_impl_13_is_fixed() -> None:
    """★記録 #13・#14 の積み残し。空入力のラウンドで初見バッファが 0 に戻る。

    `expandRound` の `g_exp_n = 0;` を `n == 0` の早期 return より前に出した。
    impl/13・impl/14 は凍結なので直っていない
    (`tests/test_impl_14_c_retreat.py` が「まだ残っている」ことを固定している)。
    """
    lib = CDLL(str(impl_library("15_c_successors")))
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
        assert one_round([INITIAL_BOARD]) > 0, "初期局面から後続が出ていない"
        assert one_round([]) == 0, (
            "空入力で前のラウンドの初見バッファが返っている。g_exp_n = 0 を引数検査より前に出すこと"
        )
    finally:
        lib.seenFree()
        lib.expandFreeBuffer()


# --------------------------------------------------------------------------
# 本物のデータで impl/14 と突き合わせる
# --------------------------------------------------------------------------


@pytest.mark.parametrize(("rounds", "board_num_max"), [(7, 2000), (14, 3000)])
def test_the_retreat_output_is_byte_identical_to_impl_14(
    tmp_path_factory: pytest.TempPathFactory,
    shared_library: pathlib.Path,
    rounds: int,
    board_num_max: int,
) -> None:
    """★`dat/` が impl/14 とバイト一致すること。指紋より強い検査。

    ⚠️ 全探索は impl/14 側で1回だけ回し、同じ `dat/` を両方に配る。
    実装ごとに回すと、打ち切り時点の集合が反復順に依存して比較にならない。
    """
    src = tmp_path_factory.mktemp("fixture")
    module = load_impl("14_c_retreat", src, shared_library)
    module.seenInit()
    run_forward(module, src, rounds, board_num_max)

    digests = {}
    logs = {}
    for impl in ("14_c_retreat", "15_c_successors"):
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
        logs[impl] = [ln for ln in text.splitlines() if "盤面総数" in ln or "辺の総数" in ln]

    a, b = digests["14_c_retreat"], digests["15_c_successors"]
    assert len(a) > 5, "成果物が少なすぎる (テストが空振り)"
    assert sorted(a) == sorted(b), f"ファイルの顔ぶれが違う: {set(a) ^ set(b)}"
    for name in a:
        assert a[name] == b[name], f"{name} のバイト列が impl/14 と違う (succ の並びが動いた)"
    assert logs["14_c_retreat"] == logs["15_c_successors"], "手数別の行が impl/14 と違う"
    assert any("キャッチ除く" in ln for ln in logs["15_c_successors"]), (
        "1手勝ちの別書式が消えている (tools/verify_log.py が読む行)"
    )
    assert any("辺の総数" in ln for ln in logs["15_c_successors"]), "P2 の行が消えている"
