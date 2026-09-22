"""impl/17_no_set — 書き出しの `set(...)` を外した版。

記録 #16 で読む側の `PyLong` 生成は消えた (F0 53 → 1 / P0 95 → 3 秒)。同じ無駄が
書く側に残っていて、`writeBoards(path, set(arr[start:start + N]))` は N 要素につき
`PyLong` を N 個起こしてハッシュし、約 2N スロットの表を組み、それをランダム順に
反復して `uint64` に戻していた。F2 111 / F5 160 / F6 54 秒がここに乗っている。

⚠️ **この版で動くのは採番順。** ファイルに並ぶ順序が「集合の反復順」から
「渡された並びそのまま」に変わるので、P2・P4・174段ループの局所性が動く。
順序を保つことは目的ではない (#16 で形式を変えた時点で一度動いている)。
目的は**同時に変えるものを1つに保つこと**で、変えたのは `set(...)` を外すことだけ。

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

IMPL_DIR = ROOT / "impl" / "17_no_set"
PREV_DIR = ROOT / "impl" / "16_raw_binary"
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
# 形式そのもの (#16 から変えていないこと)
# --------------------------------------------------------------------------


def test_the_paths_are_all_bin() -> None:
    """★4系統とも .bin のまま。保存形式は今回のレバーではない。"""
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
    """★#16 で落とした import が戻っていないこと。"""
    tree = ast.parse(source())
    imported = {
        n.name.split(".")[0]
        for node in tree.body
        if isinstance(node, ast.Import)
        for n in node.names
    }
    for name in ("pickle", "re", "shutil"):
        assert name not in imported, f"import {name} が戻っている"
    code = "\n".join(ln for ln in source().splitlines() if not ln.lstrip().startswith("#"))
    assert "pickle" not in code, "コメント以外に pickle が残っている"


def test_the_raw_format_is_checked_at_import() -> None:
    """★8 バイトとリトルエンディアンの検査が残っていること。"""
    text = source()
    assert "def checkRawFormat():" in text
    assert re.search(r"^checkRawFormat\(\)$", text, re.MULTILINE), "呼んでいない"
    assert "itemsize != 8" in text
    assert "リトルエンディアン" in text


@pytest.fixture
def impl17(tmp_path_factory: pytest.TempPathFactory) -> types.ModuleType:
    """.so を伴って実装を読み込む。⚠️ conftest の load_impl を通す。

    素の exec_module で読むと CDLL の後始末が conftest の帳簿から外れて、
    あとに走る実装の C の大域状態を壊す (#16 で実際に踏んだ)。
    """
    work = tmp_path_factory.mktemp("impl17")
    return load_impl("17_no_set", work, impl_library("17_no_set"))


def test_the_round_trip_keeps_the_order_it_was_given(
    impl17: types.ModuleType, tmp_path: pathlib.Path
) -> None:
    """★`writeBoards` が並びを変えないこと。

    `writeBoards` 自身は #16 から1バイトも変えていないので、この性質は
    #16 でも成り立っていた。⚠️ ただし #16 の検査は `set` を渡していたので、
    **順序について何も言っていなかった**。#17 は「渡した並び＝採番順」を
    呼び出し側の責任として使うようになったので、契約をここに固定する。
    レバーが効いているかどうかは下の AST の3本が見る。
    """
    module = impl17
    path = str(tmp_path / "order.bin")
    # 昇順でも降順でもハッシュ順でもない並び
    boards = [1 << 63, 3, (1 << 64) - 1, 1, 2]
    module.writeBoards(path, boards)
    assert list(module.readBoards(path)) == boards, "書いた並びで読み戻らない"
    # array("Q") のスライスでも同じこと (本番で渡るのはこちら)
    path2 = str(tmp_path / "order2.bin")
    module.writeBoards(path2, array("Q", boards)[1:4])
    assert list(module.readBoards(path2)) == boards[1:4]


def test_the_round_trip_is_byte_exact(impl17: types.ModuleType, tmp_path: pathlib.Path) -> None:
    """★書いて読んで同じ中身。件数は開かずに出る。"""
    module = impl17
    path = str(tmp_path / "x.bin")
    boards = [1, 2, 3, 1 << 63, (1 << 64) - 1]
    module.writeBoards(path, boards)
    assert pathlib.Path(path).stat().st_size == 8 * len(boards), "ヘッダが付いている"
    assert list(module.readBoards(path)) == boards
    assert module.countBoards(path) == len(boards)


def test_an_empty_family_is_a_zero_byte_file_that_exists(
    impl17: types.ModuleType, tmp_path: pathlib.Path
) -> None:
    """★空でもファイルは作る。読み手は os.path.exists で打ち切りを決めている。

    ⚠️ 0 バイトのファイルが「無い」と判定されたら、そこから先の副番号が
    まるごと読まれない。
    """
    module = impl17
    path = tmp_path / "empty.bin"
    module.writeBoards(str(path), [])
    assert path.exists(), "空のファイルが作られていない"
    assert path.stat().st_size == 0
    assert module.countBoards(str(path)) == 0
    assert len(module.readBoards(str(path))) == 0


# --------------------------------------------------------------------------
# レバー — 皮だけを剥いだこと
# --------------------------------------------------------------------------


def write_call_args(path: pathlib.Path, name: str, *, peel: bool = False) -> list[str]:
    """書き出しの第2引数を、**ソースに現れる順**に文字列で返す。

    `peel=True` は `set(x)` を `x` として読む。#16 の引数リストを剥いだものが
    #17 の引数リストと一致すれば、「皮以外どこも動かしていない」ことになる。

    ⚠️ 文字列で数えない。どちらの版もコメントで `set()` に触れているので、
    ソースを grep すると数が合わない (#16 のテストで実際に踏んだ)。
    """
    found: list[tuple[int, int, str]] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == name):
            continue
        arg = node.args[1]
        is_set = isinstance(arg, ast.Call) and getattr(arg.func, "id", None) == "set"
        if is_set and not peel:
            kind = "set"
        elif is_set and not arg.args:  # type: ignore[attr-defined]
            kind = "empty"
        elif is_set:
            kind = ast.unparse(arg.args[0])  # type: ignore[attr-defined]
        elif isinstance(arg, ast.List) and not arg.elts:
            kind = "empty"
        else:
            kind = ast.unparse(arg)
        found.append((node.lineno, node.col_offset, kind))
    return [kind for _, _, kind in sorted(found)]


def test_no_write_goes_through_a_set() -> None:
    """★書き出し11か所のどれも `set(...)` を通らないこと。

    ⚠️ これがこの版のレバーそのもの。1か所でも残ると、その系統のファイルだけ
    集合の反復順で並び、効果量の帰属が取れなくなる。
    """
    kinds = write_call_args(SOURCE, "writeBoards")
    assert len(kinds) == 11, f"呼び出しが 11 か所でない: {len(kinds)}"
    assert kinds.count("set") == 0, f"set(...) が残っている: {kinds}"


def test_the_empty_write_has_one_representation() -> None:
    """★空を書く4経路が1つの書き方に揃っていること。

    #16 は `set()` が3つと素の `[]` が1つで4通りあった。
    """
    kinds = write_call_args(SOURCE, "writeBoards", peel=True)
    assert kinds.count("empty") == 4, f"空の書き出しが4か所でない: {kinds}"
    assert write_call_args(SOURCE, "writeBoards").count("empty-list") == 0, (
        "分類が古い (peel=False は set か式の文字列を返す)"
    )
    empties = re.findall(r"writeBoards\([^\n]*, (\[\]|set\(\))\)", source())
    assert empties == ["[]"] * 4, f"空の書き方が揃っていない: {empties}"


def test_the_writes_are_impl_16_with_the_set_peeled_off() -> None:
    """★#16 の引数から皮を剥いだものが、#17 の引数と一字一句一致すること。

    「`set` が0か所」だけだと、書き出しごと消した場合や渡すものを差し替えた場合に
    空振りする。ここが**変えたのは皮だけ**という主張の本体。
    """
    peeled_16 = write_call_args(PREV_SOURCE, "writeBoards", peel=True)
    args_17 = write_call_args(SOURCE, "writeBoards", peel=True)
    assert peeled_16 == args_17, f"皮以外が動いている:\n  #16 {peeled_16}\n  #17 {args_17}"
    # 空振り防止 — 剥ぐ前の #16 は本当に set(...) だらけだった
    assert write_call_args(PREV_SOURCE, "writeBoards").count("set") == 10


def test_the_comment_no_longer_tells_the_next_reader_to_keep_the_set() -> None:
    """★`writeBoards` の上の警告が反転していること。

    #16 は「⚠️ 呼び出し側が渡す set() を外さないこと」と書いていた。残すと
    次の版を作る人が逆の判断をする。
    """
    head = source()[: source().index("def writeBoards(")]
    assert "set() を外さないこと" not in head, "#16 の警告が残っている"
    assert "記録 #17" in head, "何をしたのかが書かれていない"


# --------------------------------------------------------------------------
# 変えていないもの
# --------------------------------------------------------------------------


def test_the_set_of_functions_is_unchanged_from_impl_16() -> None:
    """★関数の顔ぶれは #16 と同じ。増減はレバーの外。"""
    prev = set(top_level_functions(PREV_SOURCE))
    cur = set(top_level_functions(SOURCE))
    assert prev == cur, f"増減がある: 消えた {prev - cur} / 増えた {cur - prev}"


def test_the_c_side_is_byte_identical_to_impl_16() -> None:
    """★C と .h と Makefile は #16 とバイト同一。

    今回のレバーは Python 側だけなので、C が動いていたら1試行1変数が崩れている。
    ⚠️ #16 の C 向けの静的な検査 (`-8` の分離、`outside` の位置、`out[4]`) は
    ここに畳んである。バイト同一ならその全部が保たれている。
    """
    for name in ("animal_shogi.c", "animal_shogi.h", "Makefile"):
        assert (IMPL_DIR / name).read_bytes() == (PREV_DIR / name).read_bytes(), (
            f"{name} が #16 と違う"
        )


def test_the_dead_print_stays_fixed() -> None:
    """★#16 で直した「末端盤面数」の tbn_win 二重足しが戻っていないこと。"""
    assert "tbn_win + tbn_win" not in source(), "#15 の誤りが戻っている"
    assert "format(tbn_win + tbn_lose)" in source()


def test_counting_does_not_open_the_files() -> None:
    """★件数は getsize // 8 で出す。ヘッダ無しにした見返り。"""
    body = top_level_functions(SOURCE)["countTotalBoardNum"]
    assert "countBoards(" in body
    assert "open(" not in body, "まだファイルを開いている"


def test_the_reset_survives_a_null_out_pointer() -> None:
    """★この版の .so を実際に叩いて、`out` が NULL でも件数が残らないこと。

    #16 で直した不変条件。C はバイト同一なので静的には自明だが、
    **この実装のビルドが通り、その .so が期待どおり動く**ことまで見ておく。
    """
    lib = CDLL(str(impl_library("17_no_set")))
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
        assert lib.expandRound(ptr(arr), 1, ptr(win), ptr(lose), ptr(uk), None) == -1
        assert int(lib.expandNewCount()) == 0, "NULL の out で前のラウンドの件数が残っている"
    finally:
        lib.seenFree()
        lib.expandFreeBuffer()
