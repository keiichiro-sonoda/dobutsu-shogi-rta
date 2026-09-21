"""impl/16_raw_binary — `dat/` を pickle から 8 バイト整数の生バイナリへ。

記録 #15 の完走 1,189 秒のうち、読み書き 5 段 (F0 53 / F2 181 / F5 199 / F6 55 /
P0 95 = 583.5 秒) が pickle を解いたり作ったりする時間だった。全体の 49.07%。

⚠️ **この版でいちばん壊れやすいのは速度ではなく採番順。** 書き出しの `set(...)` を
外すと、ファイルに並ぶ順序＝後退解析の採番順が動き、P2・P4・174段ループの局所性が
変わる。「形式の効果」と「採番順の副作用」が混ざって帰属が取れなくなる。
**外すのは別のレバーで、この版では触らない。**

答えが変わっていないことは2つの等価性検査が実際に走らせて見ている
(`tests/test_forward_search_equivalence.py` が全探索の4系統、
`tests/test_retreat_analysis_equivalence.py` が後退解析の指紋)。
ここが見るのは、その2つでは捕まえられない形の不変条件。
"""

from __future__ import annotations

import ast
import pathlib
import re
import types
from array import array
from ctypes import CDLL, POINTER, c_int32, c_uint32, c_uint64, cast

import pytest
from conftest import ROOT, impl_library, load_impl

IMPL_DIR = ROOT / "impl" / "16_raw_binary"
PREV_DIR = ROOT / "impl" / "15_c_successors"
SOURCE = IMPL_DIR / "animal_shogi.py"
PREV_SOURCE = PREV_DIR / "animal_shogi.py"
C_SOURCE = IMPL_DIR / "animal_shogi.c"
H_SOURCE = IMPL_DIR / "animal_shogi.h"

INITIAL_BOARD = 0x000A003C914B002


def source() -> str:
    return SOURCE.read_text(encoding="utf-8")


def top_level_functions(path: pathlib.Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    lines = text.splitlines(keepends=True)
    out: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            out[node.name] = "".join(lines[node.lineno - 1 : node.end_lineno])
    return out


# --------------------------------------------------------------------------
# 形式そのもの
# --------------------------------------------------------------------------


def test_the_paths_are_all_bin() -> None:
    """★4系統とも .bin。1つでも取り残すと、その系統だけ pickle で書かれる。"""
    paths = dict(re.findall(r"^(\w+_PATH_FORMAT) = DIR_PATH \+ \"(.+)\"$", source(), re.MULTILINE))
    assert set(paths) == {
        "LOSE_PATH_FORMAT",
        "WIN_PATH_FORMAT",
        "UK_PATH_FORMAT",
        "UNEXP_PATH_FORMAT",
    }
    for name, fmt in paths.items():
        assert fmt.endswith(".bin"), f"{name} が .bin でない: {fmt}"


def test_pickle_is_gone_from_the_code() -> None:
    """★import も呼び出しも残っていないこと。

    ⚠️ `re` と `shutil` は writeAndBackup のバックアップ分岐のためだけに在った。
    その分岐ごと落としたので、import も要らない。
    """
    tree = ast.parse(source())
    imported = {
        n.name.split(".")[0]
        for node in tree.body
        if isinstance(node, ast.Import)
        for n in node.names
    }
    for name in ("pickle", "re", "shutil"):
        assert name not in imported, f"import {name} が残っている"
    code = "\n".join(ln for ln in source().splitlines() if not ln.lstrip().startswith("#"))
    assert "pickle" not in code, "コメント以外に pickle が残っている"


@pytest.fixture
def impl16(tmp_path_factory: pytest.TempPathFactory) -> types.ModuleType:
    """.so を伴って実装を読み込む。⚠️ conftest の load_impl を通す。

    素の exec_module で読むと CDLL の後始末が conftest の帳簿から外れて、
    あとに走る実装の C の大域状態を壊す（実際にここで踏んだ）。
    """
    work = tmp_path_factory.mktemp("impl16")
    return load_impl("16_raw_binary", work, impl_library("16_raw_binary"))


def test_the_round_trip_is_byte_exact(impl16: types.ModuleType, tmp_path: pathlib.Path) -> None:
    """★書いて読んで同じ集合。件数は開かずに出る。"""
    module = impl16
    path = str(tmp_path / "x.bin")
    boards = {1, 2, 3, 1 << 63, (1 << 64) - 1}
    module.writeBoards(path, boards)
    assert pathlib.Path(path).stat().st_size == 8 * len(boards), "ヘッダが付いている"
    assert set(module.readBoards(path)) == boards
    assert module.countBoards(path) == len(boards)


def test_an_empty_family_is_a_zero_byte_file_that_exists(
    impl16: types.ModuleType, tmp_path: pathlib.Path
) -> None:
    """★空でもファイルは作る。読み手は os.path.exists で打ち切りを決めている。

    ⚠️ 0 バイトのファイルが「無い」と判定されたら、そこから先の副番号が
    まるごと読まれない。
    """
    module = impl16
    path = tmp_path / "empty.bin"
    module.writeBoards(str(path), set())
    assert path.exists(), "空のファイルが作られていない"
    assert path.stat().st_size == 0
    assert module.countBoards(str(path)) == 0
    assert len(module.readBoards(str(path))) == 0


def test_the_raw_format_is_checked_at_import() -> None:
    """★8 バイトとリトルエンディアンを起動時に1回だけ確かめていること。

    処理系依存なので、違う機械では書いたものが読めない。落ちる場所が
    遠いと原因が分からなくなる。
    """
    text = source()
    assert "def checkRawFormat():" in text
    assert re.search(r"^checkRawFormat\(\)$", text, re.MULTILINE), "呼んでいない"
    assert "itemsize != 8" in text
    assert "リトルエンディアン" in text


# --------------------------------------------------------------------------
# 最大の罠 — 書き出しの set(...) を外していないこと
# --------------------------------------------------------------------------


def write_call_args(path: pathlib.Path, name: str) -> list[str]:
    """書き出しの第2引数の種類を、呼び出しの順に返す。"""
    out = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == name):
            continue
        arg = node.args[1]
        if isinstance(arg, ast.Call) and getattr(arg.func, "id", None) == "set":
            out.append("set")
        elif isinstance(arg, ast.List) and not arg.elts:
            out.append("empty-list")
        else:
            out.append(ast.unparse(arg))
    return out


def test_every_write_still_goes_through_a_set() -> None:
    """★書き出しに渡すものが set(...) のまま (1か所だけ空のリスト)。

    ⚠️ **ここがこの版でいちばん大事な検査。** ファイルに並ぶ順序は集合の反復順で、
    それがそのまま後退解析の採番順になる (`experiments/numbering_order/` が実測)。
    `array("Q", x)` に変えると並びが変わり、P2・P4・174段ループの局所性が動くので、
    「形式の効果」と「採番順の副作用」が混ざって帰属が取れない。
    """
    kinds = write_call_args(SOURCE, "writeBoards")
    assert len(kinds) == 11, f"呼び出しが 11 か所でない: {len(kinds)}"
    bad = [k for k in kinds if k not in ("set", "empty-list")]
    assert bad == [], f"set() を通していない書き出しがある: {bad}"


def test_the_writes_are_distributed_exactly_as_in_impl_15() -> None:
    """★#15 の「set(...) が10か所・素の [] が1か所」が、そのまま保たれていること。

    上の検査だけだと「書き出しごと消した」場合に空振りする。
    ⚠️ 文字列で数えない。この版はコメントで `set()` に触れているので、
    ソースを grep すると数が合わない（実際にここで踏んだ）。
    """
    assert write_call_args(PREV_SOURCE, "writeAndBackup") == write_call_args(SOURCE, "writeBoards")
    kinds = write_call_args(SOURCE, "writeBoards")
    assert kinds.count("set") == 10, f"set(...) が10か所でない: {kinds}"
    assert kinds.count("empty-list") == 1, f"素の [] が1か所でない: {kinds}"


# --------------------------------------------------------------------------
# 関数の顔ぶれ
# --------------------------------------------------------------------------


def test_the_write_function_was_renamed_and_the_rest_stayed() -> None:
    """★増減するのは writeAndBackup → writeBoards と、読みの2関数だけ。"""
    prev = set(top_level_functions(PREV_SOURCE))
    cur = set(top_level_functions(SOURCE))
    assert prev - cur == {"writeAndBackup"}, f"消えた関数が想定外: {prev - cur}"
    assert cur - prev == {"writeBoards", "readBoards", "countBoards", "checkRawFormat"}, (
        f"増えた関数が想定外: {cur - prev}"
    )


def test_the_dead_print_was_fixed() -> None:
    """★countTotalBoardNum の「末端盤面数」が tbn_win を2回足していた。

    2021年から残っていた印字だけの死んだ行。どこからも呼ばれないので
    `dat/` にも記録にも影響しないが、直したことを記録ノートに書いてある。
    """
    assert "tbn_win + tbn_win" not in source(), "impl/15 の誤りが残っている"
    assert "format(tbn_win + tbn_lose)" in source()


def test_counting_does_not_open_the_files() -> None:
    """★件数は getsize // 8 で出す。ヘッダ無しにした見返りがこれ。"""
    body = top_level_functions(SOURCE)["countTotalBoardNum"]
    assert "countBoards(" in body
    assert "open(" not in body, "まだファイルを開いている"


# --------------------------------------------------------------------------
# 記録 #15 の積み残し3件 (CLAUDE.md の「次の実装で必ず直すもの」)
# --------------------------------------------------------------------------


def c_text() -> str:
    return C_SOURCE.read_text(encoding="utf-8")


def c_code() -> str:
    """// のコメントを落とした C。

    ⚠️ この版のコメントには「早期 return」「out[4] は書けない」といった
    説明が入っている。コメントごと検索すると、**直したことを説明した文のせいで
    直っていないと判定される**（実際にここで踏んだ）。
    """
    return "\n".join(re.sub(r"//.*$", "", ln) for ln in c_text().splitlines())


def test_the_expansion_counter_is_reset_before_every_early_return() -> None:
    """★#15 では `if (!out) return -1;` だけが `g_exp_n = 0;` より前に残っていた。

    ⚠️ #15 のコメントは「どの早期 return よりも前に 0 に戻す」と書いてあって、
    **実コードより強いことを言っていた**。ここは順序を直に見る。
    """
    body = re.search(r"int expandRound\(.*?\n\}", c_code(), re.DOTALL)
    assert body, "expandRound が見つからない"
    text = body.group(0)
    reset = text.index("g_exp_n = 0;")
    for early in re.finditer(r"return [^;]+;", text):
        assert early.start() > reset, (
            f"g_exp_n = 0; より前に return がある: {text[early.start() : early.end()]}"
        )


def test_the_reset_survives_a_null_out_pointer() -> None:
    """★実際に走らせて確かめる。`out` が NULL の経路でも件数が残らないこと。

    #13 は空入力、#15 はここが残っていた。同じ形の3度目。
    """
    lib = CDLL(str(impl_library("16_raw_binary")))
    lib.seenInit.restype = c_int32
    lib.seenInit.argtypes = ()
    lib.seenFree.restype = None
    lib.seenFree.argtypes = ()
    lib.expandRound.restype = c_int32
    lib.expandRound.argtypes = (POINTER(c_uint64),) + (c_uint32,) + (POINTER(c_uint64),) * 4
    lib.expandNewCount.restype = c_uint64
    lib.expandNewCount.argtypes = ()
    lib.expandFreeBuffer.restype = None
    lib.expandFreeBuffer.argtypes = ()

    def ptr(a: array[int]) -> object:
        return cast(a.buffer_info()[0], POINTER(c_uint64))

    assert lib.seenInit() == 0
    try:
        arr = array("Q", [INITIAL_BOARD])
        win = array("Q", bytes(8))
        lose = array("Q", bytes(8))
        uk = array("Q", bytes(8))
        out = array("Q", bytes(8)) * 5
        assert lib.expandRound(ptr(arr), 1, ptr(win), ptr(lose), ptr(uk), ptr(out)) == 0
        assert int(lib.expandNewCount()) > 0, "初期局面から後続が出ていない"
        # out が NULL の経路。引数不正で戻るが、件数は 0 に戻っていなければならない
        assert lib.expandRound(ptr(arr), 1, ptr(win), ptr(lose), ptr(uk), None) == -1
        assert int(lib.expandNewCount()) == 0, (
            "NULL の out で前のラウンドの件数が残っている。"
            "g_exp_n = 0; を !out の検査より前に出すこと"
        )
    finally:
        lib.seenFree()
        lib.expandFreeBuffer()


def succ_range_body() -> str:
    body = re.search(r"int buildSuccRange\(.*?\n\}", c_code(), re.DOTALL)
    assert body, "buildSuccRange が見つからない"
    return body.group(0)


def test_the_two_invariants_have_separate_return_codes() -> None:
    """★#15 は `degree > 255 || n_found > degree` を -6 に束ねていた。

    後者で落ちたときに「出次数が cnt に収まらない」という嘘の説明が出る。
    """
    text = succ_range_body()
    assert "degree > 255 || n_found > degree" not in text, "まだ束ねている"
    assert re.search(r"if \(degree > 255\)", text), "-6 の条件が出次数だけになっていない"
    assert re.search(r"if \(n_found > degree\)", text), "-8 の条件が無い"
    assert "return -8;" in text
    h = H_SOURCE.read_text(encoding="utf-8")
    assert "-8=発見済みの後続が出次数を超えた" in h, ".h に -8 の説明が無い"


def test_the_outside_counter_is_added_after_the_check() -> None:
    """★#15 は `outside +=` を `n_found > degree` の検査より前に足していた。

    out[2] は正常終了のときしか書かないので外へは出なかったが、
    検査を先に置くほうが素直。
    """
    text = succ_range_body()
    assert text.index("if (n_found > degree)") < text.index("outside += degree - n_found;"), (
        "outside を検査より前に足している"
    )


def test_the_error_report_stays_inside_the_out_array() -> None:
    """★out は4要素。-8 の経路が out[4] に書いていないこと。

    ⚠️ Python 側が渡すのは c_int64 * 4 なので、out[4] は呼び出し側のスタックを踏む。
    """
    assert "c_int64_array4 = c_int64 * 4" in source(), "out の長さが変わった"
    assert "out[4]" not in succ_range_body(), "buildSuccRange が out[4] を書いている"
