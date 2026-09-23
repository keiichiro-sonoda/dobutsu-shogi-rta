"""impl/19_c_gather — 連番→パック値の翻訳を C 側へ移し、後退解析に計装を入れた版。

記録 #18 まで、億単位のループで Python に残っていたのは「出力の準備」の2か所だけ。
後退解析は**連番**で動くが `dat/` に書くのは**パック値**で、その翻訳が
リスト内包に残っていた。

    ① 174段ループ   [packed[i] for i in found]                96,802,868 回
    ② 引き分けの抽出 [packed[i] for i in range(n_uk) if ...]  99,485,568 回走査

どちらも平たい配列から平たいバイト列を作るのに `PyLong` を2個ずつ起こしている。
記録 #16 (読む側)・#17 (書く側) とまったく同じ形の3回目。

⚠️ **この版でいちばん壊れやすいのは速度ではなく順序。** ① は `found` の順、
② は連番の昇順で、どちらも `dat/` のバイト列をそのまま決める。
ここでは小さいフィクスチャで **impl/18 と成果物がバイト一致すること**まで見る
(本走の検査も `results/19_c_gather/bytecompare.txt` で同じ形)。

計装 (`_profMark` の後退解析側) は記録 #10 の全探索の計装と同じ扱いで同乗させる。
⚠️ **列は増やさない。** `forward.tsv` は `PROFILE_COLUMNS` が決めているので、
`_prof` にキーが増えても `results/` の凍結物と列が揃ったままになる。
"""

from __future__ import annotations

import ast
import difflib
import pathlib
import re
import shutil
from array import array
from ctypes import CDLL, POINTER, c_int32, c_ubyte, c_uint32, c_uint64, cast

import pytest
from conftest import ROOT, impl_library, load_impl, run_forward, run_retreat

IMPL_DIR = ROOT / "impl" / "19_c_gather"
PREV_DIR = ROOT / "impl" / "18_optimized"
SOURCE = IMPL_DIR / "animal_shogi.py"
PREV_SOURCE = PREV_DIR / "animal_shogi.py"

# 翻訳を移した2か所と、その受け皿と、計装を置いた3つ
CHANGED = {
    "retreatAnalysis",  # ①②の呼び出し側と、後退解析の境界
    "writeUnknownChunks",  # ②の受け皿を list から array("Q") に
    "_profMark",  # ページフォルトの2列を足した
    "buildSuccessors",  # P2_alloc の境界
    "buildPredecessors",  # P4_count の境界
}
ADDED = {"_retreatWriteSummary"}

SMALL_BOARD_NUM_MAX = 2000
FORWARD_ROUNDS = 7

UNDECIDED = 255

# 後退解析の TSV に必ず出る行 (RETREAT_SPANS と RETREAT_MARKS から来る)
SPAN_ROWS = ("P0", "P1", "P2", "P4", "loop174", "R_draw", "R_uk", "retreat_total")
RETREAT_MARKS = (
    "R_start",
    "P0",
    "P1",
    "P2_alloc",
    "P2",
    "P2_free",
    "P4_count",
    "P4",
    "R_dtm",
    "R_loop",
    "R_draw",
    "R_uk",
)


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


def module_assignments(path: pathlib.Path, prefix: str) -> dict[str, str]:
    """モジュール直下の代入のうち、名前が prefix で始まるものを返す。"""
    text = path.read_text(encoding="utf-8")
    out: dict[str, str] = {}
    for node in ast.parse(text).body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id.startswith(prefix):
                segment = ast.get_source_segment(text, node)
                assert segment is not None, f"{path} の {target.id} のソースを取れない"
                out[target.id] = segment
    return out


def code_lines(body: str) -> str:
    """コメント行を除いたコード。罠を警告するコメントに引っかからないため。"""
    return "\n".join(ln for ln in body.splitlines() if not ln.lstrip().startswith("#"))


def c_code(text: str) -> str:
    """C からコメントを落とす。規約を説明した文が、その規約の語を含むため。"""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return "\n".join(ln.split("//", 1)[0] for ln in text.splitlines())


# --------------------------------------------------------------------------
# 構造
# --------------------------------------------------------------------------


def test_the_c_only_gains_lines() -> None:
    """C とヘッダは impl/18 に対して純粋な追加。既存の1行も動かさない。"""
    for name in ("animal_shogi.c", "animal_shogi.h"):
        prev = (PREV_DIR / name).read_text(encoding="utf-8").splitlines()
        cur = (IMPL_DIR / name).read_text(encoding="utf-8").splitlines()
        removed = [
            ln[2:]
            for ln in difflib.unified_diff(prev, cur, n=0, lineterm="")
            if ln.startswith("-") and not ln.startswith("---")
        ]
        assert removed == [], f"{name} で impl/18 の行が消えている: {removed[:3]}"
        assert len(cur) > len(prev), f"{name} に翻訳の2関数が入っていない"


def test_the_build_is_untouched() -> None:
    """★`Makefile` は impl/18 とバイト同一 (＝ `-O2` のまま)。

    記録 #18 で `-O` を1段動かしたばかりなので、ここでまた触ると
    「翻訳を C に移したぶん」と「フラグのぶん」が混ざる。
    """
    assert (IMPL_DIR / "Makefile").read_bytes() == (PREV_DIR / "Makefile").read_bytes(), (
        "impl/19_c_gather/Makefile が impl/18 と違う。-march=native などは別のレバー"
    )


def test_no_impl_env_needed() -> None:
    assert not (IMPL_DIR / "impl.env").exists(), "既定のビルド・実行コマンドで走るはず"


def test_only_the_expected_functions_changed() -> None:
    """変わるのは翻訳の2か所と計装だけ。全探索の関数は1バイトも動かさない。"""
    prev = top_level_functions(PREV_SOURCE)
    cur = top_level_functions(SOURCE)
    changed = {n for n in prev if n in cur and cur[n] != prev[n]}
    assert changed == CHANGED, f"想定外の関数が変わっている: {changed ^ CHANGED}"
    assert set(cur) - set(prev) == ADDED, f"増えた関数が想定と違う: {set(cur) - set(prev)}"
    assert set(prev) - set(cur) == set(), f"消えた関数がある: {set(prev) - set(cur)}"
    for name in (
        "searchNext",
        "searchAll",
        "buildIndex",
        "loadForwardResult",
        "writeWLFilesForDepth",
        "writeBoards",
        "readBoards",
    ):
        assert cur[name] == prev[name], f"{name} が impl/18 から変わっている"


def test_the_forward_profile_columns_are_unchanged() -> None:
    """★`forward.tsv` の列が impl/18 と同じであること。

    `_profMark` に `min_` / `maj_` のキーを足したが、列を決めているのは
    `PROFILE_COLUMNS` なので出力は動かない。ここが動くと `results/` に
    並べてある #10〜#18 の `forward.tsv` と列がずれる。
    """
    prev = module_assignments(PREV_SOURCE, "PROFILE")
    cur = module_assignments(SOURCE, "PROFILE")
    assert cur == prev, f"PROFILE_* の定義が変わっている: {set(cur) ^ set(prev)}"
    assert "PROFILE_COLUMNS" in cur, "PROFILE_COLUMNS が見つからない (テストが空振り)"


def test_the_translation_left_python() -> None:
    """★億単位の内包が Python 側に1つも残っていないこと。"""
    body = code_lines(SOURCE.read_text(encoding="utf-8"))
    assert "packed[i] for i in" not in body, "まだ Python 側で連番をパック値に戻している"
    retreat = code_lines(top_level_functions(SOURCE)["retreatAnalysis"])
    assert retreat.count("gatherPacked(") == 1, "①の呼び出しが1か所でない"
    # ②は数える周と詰める周で2回
    assert retreat.count("gatherDraws(") == 2, "②が2周になっていない (数える→詰める)"
    assert retreat.count("if rc != 0:") >= 3, "C の戻り値を確かめていない呼び出しがある"
    assert "raise RuntimeError" in retreat


def test_the_draw_buffer_does_not_grow() -> None:
    """★伸びるバッファも再開の仕組みも持ち込まないこと (指示書 §3-2)。

    ②は長さが事前に分からないが、2周すれば寸法が分かる。記録 #13・#15 の
    「容量不足で止まって呼び直す」形をここに持ち込むと、順序の検査が増える。
    """
    csrc = c_code((IMPL_DIR / "animal_shogi.c").read_text(encoding="utf-8"))
    new = csrc[csrc.index("int gatherPacked(") :]
    assert "static" not in new, "翻訳の関数が呼び出しをまたぐ状態を持っている"
    assert "realloc" not in new and "malloc" not in new, "翻訳の関数が自分で確保している"
    # n_out のリセットは NULL 検査の直後 (記録 #13 の不具合と同じ順序にしない)
    draws = csrc[csrc.index("int gatherDraws(") :]
    head, sep, rest = draws.partition("if (!n_out) return -1;")
    assert sep, "n_out の NULL 検査が無い"
    assert "return" not in head, "NULL 検査より前に return がある"
    assert rest.index("n_out[0] = 0;") < rest.index("return"), (
        "リセットが早期 return の後ろにある (記録 #13 と同じ形)"
    )


def test_the_two_known_defects_are_still_here() -> None:
    """★CLAUDE.md の「次の実装で必ず直すもの」2件が、この版にも残っていることを固定する。

    どちらも直さなかった理由は [`docs/records/19-c-gather.md`](../docs/records/19-c-gather.md)
    に書いてある。要点だけ:

    - `nextBoardInvNormal` の `int *moves` を初期化すると、**全探索で実行される C の行が
      変わる** (`expandRound` → `nextBoardSeenNormal` がこの関数を呼ぶ)。記録 #19 が
      全探索の経路で変えたのは `_profMark` の `getrusage` だけなので、混ぜると2つになる。
    - `updateUKFile` の2分割は、CLAUDE.md が「直すとチャンクの切れ目が動く」と
      名指しで別の試行に回している。

    `moves` は記録 #20 で直した (`tests/test_impl_20_prefetch.py` が固定している)。
    `impl/19` は凍結なので、この固定は外さない (凍結した版には残り続ける)。
    """
    csrc = c_code((IMPL_DIR / "animal_shogi.c").read_text(encoding="utf-8"))
    decl = "int i, j, dst, own_num, own_p, *moves, moves_num, src_mod16, dst_mod16;"
    assert decl in csrc, "moves の未初期化が直っている (宣言の形が変わった)"
    body = code_lines(top_level_functions(SOURCE)["updateUKFile"])
    assert "ukl[BOARD_NUM_MAX:]" in body, "updateUKFile の「残り全部」が直っている"


# --------------------------------------------------------------------------
# C を実際に動かす
# --------------------------------------------------------------------------


class Gather:
    """impl/19 の .so の gatherPacked / gatherDraws を直に叩く。"""

    def __init__(self) -> None:
        self.lib = CDLL(str(impl_library("19_c_gather")))
        self.lib.gatherPacked.restype = c_int32
        self.lib.gatherPacked.argtypes = (
            POINTER(c_uint64),
            c_uint32,
            POINTER(c_uint32),
            c_uint32,
            POINTER(c_uint64),
        )
        self.lib.gatherDraws.restype = c_int32
        self.lib.gatherDraws.argtypes = (
            POINTER(c_uint64),
            POINTER(c_ubyte),
            c_uint32,
            POINTER(c_uint64),
            c_uint32,
            POINTER(c_uint32),
        )

    def packed(
        self, packed: list[int], found: list[int], cap: int | None = None, n_all: int | None = None
    ) -> tuple[int, list[int]]:
        pk = array("Q", packed)
        fd = array("I", found)
        out = array("Q", bytes(8)) * (len(found) if cap is None else cap)
        rc = self.lib.gatherPacked(
            cast(pk.buffer_info()[0], POINTER(c_uint64)),
            len(packed) if n_all is None else n_all,
            cast(fd.buffer_info()[0], POINTER(c_uint32)) if found else None,
            len(found),
            cast(out.buffer_info()[0], POINTER(c_uint64)) if len(out) else None,
        )
        return int(rc), list(out)

    def draws(
        self, packed: list[int], dtm: bytes, cap: int | None = None, n_uk: int | None = None
    ) -> tuple[int, int, list[int]]:
        pk = array("Q", packed)
        buf = bytearray(dtm)
        dt = (c_ubyte * len(buf)).from_buffer(buf)
        out = array("Q", bytes(8)) * (0 if cap is None else cap)
        n_out = array("I", bytes(4))
        rc = self.lib.gatherDraws(
            cast(pk.buffer_info()[0], POINTER(c_uint64)),
            dt,
            len(dtm) if n_uk is None else n_uk,
            cast(out.buffer_info()[0], POINTER(c_uint64)) if cap else None,
            0 if cap is None else cap,
            cast(n_out.buffer_info()[0], POINTER(c_uint32)),
        )
        return int(rc), int(n_out[0]), list(out)


@pytest.fixture(scope="module")
def gather() -> Gather:
    if shutil.which("gcc") is None:
        pytest.skip("gcc が無い")
    return Gather()


def test_gather_packed_translates_in_the_order_of_found(gather: Gather) -> None:
    """★詰める順は found の順。連番の昇順ではない。"""
    packed = [0x11, 0x22, 0x33, 0x44]
    rc, out = gather.packed(packed, [3, 0, 2])
    assert rc == 0
    assert out == [0x44, 0x11, 0x33], "found の並びで詰めていない"


def test_gather_packed_rejects_an_index_outside_packed(gather: Gather) -> None:
    """★範囲違反は -3。黙って隣の局面を書き出さない。"""
    rc, _ = gather.packed([0x11, 0x22], [0, 2])
    assert rc == -3, f"範囲外の連番が通った: {rc}"
    # ちょうど n_all - 1 は通ること (off-by-one で締めすぎていない)
    rc, out = gather.packed([0x11, 0x22], [1])
    assert rc == 0 and out == [0x22]


def test_gather_packed_accepts_an_empty_frontier(gather: Gather) -> None:
    """★空の段は NULL を渡しても 0 で返ること (array("Q") のアドレスが 0 になる)。"""
    rc, out = gather.packed([0x11], [])
    assert rc == 0 and out == []


def test_gather_packed_rejects_null_arguments(gather: Gather) -> None:
    """★n > 0 なのに出力先が無ければ -1。"""
    pk = array("Q", [0x11])
    fd = array("I", [0])
    rc = gather.lib.gatherPacked(
        cast(pk.buffer_info()[0], POINTER(c_uint64)),
        1,
        cast(fd.buffer_info()[0], POINTER(c_uint32)),
        1,
        None,
    )
    assert rc == -1, f"出力先が NULL なのに通った: {rc}"
    rc = gather.lib.gatherPacked(
        None,
        1,
        cast(fd.buffer_info()[0], POINTER(c_uint32)),
        1,
        cast(pk.buffer_info()[0], POINTER(c_uint64)),
    )
    assert rc == -1, f"packed が NULL なのに通った: {rc}"


def test_gather_draws_counts_then_fills(gather: Gather) -> None:
    """★2周で同じ数になり、詰める順は連番の昇順であること。"""
    packed = [0xA0, 0xA1, 0xA2, 0xA3, 0xA4]
    dtm = bytes([UNDECIDED, 3, UNDECIDED, 0, UNDECIDED])
    rc, n, _ = gather.draws(packed, dtm)
    assert rc == 0 and n == 3, f"数える周が合わない: {rc} / {n}"
    rc, n2, out = gather.draws(packed, dtm, cap=n)
    assert rc == 0 and n2 == n
    assert out == [0xA0, 0xA2, 0xA4], "連番の昇順で詰めていない"


def test_gather_draws_stops_at_the_capacity(gather: Gather) -> None:
    """★容量不足は -2。黙って切り詰めない。"""
    dtm = bytes([UNDECIDED] * 3)
    rc, _, _ = gather.draws([1, 2, 3], dtm, cap=2)
    assert rc == -2, f"容量を超えて詰めた: {rc}"


def test_gather_draws_resets_the_count_before_any_early_return(gather: Gather) -> None:
    """★戻り値が何であれ n_out は 0 に戻っていること (記録 #13 と同じ形を作らない)。"""
    n_out = array("I", [12345])
    rc = gather.lib.gatherDraws(
        None, None, 0, None, 0, cast(n_out.buffer_info()[0], POINTER(c_uint32))
    )
    assert rc == -1 and n_out[0] == 0, f"早期 return がリセットを飛ばした: {rc} / {n_out[0]}"


def test_gather_draws_scans_only_the_unknown_range(gather: Gather) -> None:
    """★走査は [0, n_uk)。キャッチとトライ負けの範囲は見ない。

    連番は [未知][キャッチ][トライ負け] の順に並んでいて、トライ負けの dtm は
    0 なので 255 にはならないが、**C は n_all を受け取らない**ので、
    n_uk より後ろを読まないことをここで固定する。
    """
    packed = [0xB0, 0xB1, 0xB2]
    dtm = bytes([UNDECIDED, UNDECIDED, UNDECIDED])
    rc, n, out = gather.draws(packed, dtm, cap=3, n_uk=2)
    assert rc == 0 and n == 2, f"n_uk を超えて走査している: {rc} / {n}"
    assert out[:2] == [0xB0, 0xB1]


# --------------------------------------------------------------------------
# 走らせて impl/18 と突き合わせる
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def retreat_pair(tmp_path_factory: pytest.TempPathFactory) -> dict[str, pathlib.Path]:
    """同じ打ち切り `dat/` を両方に配って、後退解析を最後まで回す。

    ⚠️ 実装ごとに全探索を回してはいけない (打ち切った時点の集合が変わる)。
    入力を1つに固定するのは `tests/test_retreat_analysis_equivalence.py` と同じ。
    """
    if shutil.which("gcc") is None:
        pytest.skip("gcc が無い")
    src = tmp_path_factory.mktemp("fixture19")
    module = load_impl("18_optimized", src, impl_library("18_optimized"))
    run_forward(module, src, FORWARD_ROUNDS, SMALL_BOARD_NUM_MAX)

    out: dict[str, pathlib.Path] = {}
    for impl in ("18_optimized", "19_c_gather"):
        work = tmp_path_factory.mktemp(impl)
        module = load_impl(impl, work, impl_library(impl))
        for path in sorted((src / "dat").iterdir()):
            shutil.copy(path, work / "dat" / path.name)
        vars(module)["BOARD_NUM_MAX"] = SMALL_BOARD_NUM_MAX
        run_retreat(module, work)
        out[impl] = work
    return out


def test_the_artifacts_are_byte_identical_to_impl_18(
    retreat_pair: dict[str, pathlib.Path],
) -> None:
    """★成果物が impl/18 と**バイト一致**すること。

    ①②はどちらも順序をそのまま `dat/` に流すので、指紋 (順序に依らない) では
    足りない。区切りも順序も動かない変更なのでバイト比較を通す
    (CLAUDE.md の「区切りも順序も動かさない変更では指紋ではなくバイト比較」)。
    """
    a, b = retreat_pair["18_optimized"] / "dat", retreat_pair["19_c_gather"] / "dat"
    names = sorted(p.name for p in a.iterdir())
    assert names == sorted(p.name for p in b.iterdir()), "ファイルの顔ぶれが違う"
    assert len(names) > 3, f"成果物が少なすぎる (テストが空振り): {names}"
    assert any(n.startswith("unknown") for n in names), "引き分けのファイルが無い"
    differ = [n for n in names if (a / n).read_bytes() != (b / n).read_bytes()]
    assert differ == [], f"バイトが違うファイルがある: {differ[:5]}"


def test_the_retreat_summary_is_written(retreat_pair: dict[str, pathlib.Path]) -> None:
    """★後退解析の計装が TSV を1本書き、区間が境界の差と一致すること。"""
    path = retreat_pair["19_c_gather"] / "kaiseki_log" / "retreat_summary.tsv"
    assert path.exists(), "retreat_summary.tsv が出ていない"
    rows = dict(ln.split("\t", 1) for ln in path.read_text(encoding="utf-8").splitlines())
    for name in SPAN_ROWS:
        assert name in rows, f"区間 {name} が出ていない"
    for mark in RETREAT_MARKS:
        for col in ("t_", "rss_", "hwm_", "min_", "maj_"):
            assert col + mark in rows, f"{col}{mark} が出ていない"
    # 区間は境界の差 (丸めずに書いているので 1 ミリ秒まで合う)
    assert abs(float(rows["R_draw"]) - (float(rows["t_R_draw"]) - float(rows["t_R_loop"]))) < 1e-3
    assert abs(float(rows["retreat_total"]) - float(rows["t_R_uk"])) < 1e-3
    # 時刻は単調。境界の順序が入れ替わっていたらここで落ちる
    times = [float(rows["t_" + m]) for m in RETREAT_MARKS]
    assert times == sorted(times), f"境界の時刻が単調でない: {times}"
    # minor fault は積算値なので減らない
    minors = [int(rows["min_" + m]) for m in RETREAT_MARKS]
    assert minors == sorted(minors), f"minor fault が減っている: {minors}"
    assert minors[-1] > 0, "minor fault が1つも計上されていない (テストが空振り)"


def test_the_forward_tsv_columns_did_not_move(retreat_pair: dict[str, pathlib.Path]) -> None:
    """★計装を足しても `forward.tsv` が出るときの列は impl/18 と同じであること。"""
    heads = []
    for impl in ("18_optimized", "19_c_gather"):
        src = ROOT / "impl" / impl / "animal_shogi.py"
        heads.append(module_assignments(src, "PROFILE")["PROFILE_COLUMNS"])
    assert heads[0] == heads[1]
    # 実際に走った側にも retreat_summary.tsv しか増えていないこと
    logs = {p.name for p in (retreat_pair["19_c_gather"] / "kaiseki_log").iterdir()}
    prev = {p.name for p in (retreat_pair["18_optimized"] / "kaiseki_log").iterdir()}
    assert logs - prev == {"retreat_summary.tsv"}, f"増えたログが想定と違う: {logs - prev}"
