"""impl/02_resident_wins — 中間ファイル機構を撤去し、勝ち局面をメモリ常駐にした版。

1試行1変数。変えたのは「_next / _next_win をやめて勝ち集合を常駐させる」ことだけで、
C 側も最適化フラグも触っていない。記録 #2 のタイム差がその1点の効果だと言えるように、
ここで機械的に固定する。
"""

from __future__ import annotations

import ast
import re

from conftest import BASELINE_DIR, ROOT

IMPL_DIR = ROOT / "impl" / "02_resident_wins"
SOURCE = IMPL_DIR / "animal_shogi.py"

# 撤去したものの名前。ソースのどこにも「コードとして」残っていてはいけない
REMOVED_NAMES = (
    "UK_NEXT_PATH_FORMAT",
    "UK_NEXT_WIN_PATH_FORMAT",
    "createNextWin",
    "updateNextWin",
    "addUKRelatedBoards",
    "writeUKRelatedFiles",
)


def code_text() -> str:
    """コメントと docstring を除いたソース。

    撤去の経緯を説明として書き残すのは許す。消えているべきなのは「コード」の方。
    """
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            doc = ast.get_docstring(node, clean=False)
            if doc is not None:
                docstrings.add(doc)

    pieces = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            pieces.append(node.id)
        elif isinstance(node, ast.Attribute):
            pieces.append(node.attr)
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value not in docstrings
        ):
            pieces.append(node.value)
    return "\n".join(pieces)


def source_without_comments() -> str:
    """呼び出しの形をそのまま見たいとき用。コメントだけ落とす。"""
    out = []
    for line in SOURCE.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("#"):
            continue
        out.append(line.split("#", 1)[0])
    return "\n".join(out)


def test_c_and_build_are_untouched() -> None:
    """C・ヘッダ・Makefile はベースラインとバイト単位で同一 (＝ -O0 のまま)。"""
    for name in ("animal_shogi.c", "animal_shogi.h", "Makefile"):
        assert (IMPL_DIR / name).read_bytes() == (BASELINE_DIR / name).read_bytes(), (
            f"impl/02_resident_wins/{name} がベースラインと違う。"
            f"この試行で変えるのは中間ファイル機構の撤去だけ"
        )


def test_intermediate_file_machinery_is_gone() -> None:
    body = code_text()
    for name in REMOVED_NAMES:
        assert name not in body, f"{name} がコードに残っている"


def test_no_next_win_files_are_touched() -> None:
    """_next / _next_win のパスを組み立てる箇所が残っていないこと。"""
    body = code_text()
    assert "_next.pickle" not in body
    assert "_next_win.pickle" not in body


def test_win_and_lose_files_are_still_written() -> None:
    """深さカウンタは win/lose ファイルの存在から導出されている。

    常駐集合にしたからといって updateWLFile を消すと act_num が進まなくなる。
    """
    body = source_without_comments()
    assert body.count("updateWLFile(new_win_boards, act_num, True)") == 1
    assert body.count("updateWLFile(new_lose_boards, act_num, False)") == 1


def test_resident_set_is_passed_not_global() -> None:
    """all_wins は retreatAnalysis のローカル変数。グローバルを増やさない。"""
    body = source_without_comments()
    assert "def searchWinBoard(all_wins: set):" in body
    assert "def searchLoseBoard(all_wins: set):" in body
    # モジュール先頭 (インデント 0) に all_wins への代入が無いこと
    assert not re.search(r"^all_wins\s*=", body, re.MULTILINE)


def test_new_wins_are_added_to_the_resident_set() -> None:
    """その回に確定した勝ちが、同じ回の負け判定から見えていなければ答えが変わる。"""
    body = source_without_comments()
    assert "all_wins.update(new_win_boards)" in body
    assert "if not nb in all_wins:" in body


def test_no_impl_env_needed() -> None:
    """構成がベースラインと同じなので、ハーネスの既定値でそのまま走る。"""
    assert not (IMPL_DIR / "impl.env").exists()
