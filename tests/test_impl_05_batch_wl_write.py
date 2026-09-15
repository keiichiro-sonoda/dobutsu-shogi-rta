"""impl/05_batch_wl_write — 勝ち／負けの書き出しを深さごと1回にまとめた版。

1試行1変数。変えたのは「チャンクごとに末尾ファイルへ追記する」のをやめて
「深さごとに新しい副番号へ書く」だけ。全探索も指し手の再生成も常駐方式も触っていない。

`updateWLFile()` 自体は残す。前向き探索がまだ使っていて、そこは今回の対照群だから。
実際に同じ答えを出すかは tests/test_retreat_analysis_equivalence.py が走らせて確かめる。
"""

from __future__ import annotations

import ast
import pathlib

from conftest import BASELINE_DIR, ROOT

IMPL_DIR = ROOT / "impl" / "05_batch_wl_write"
SOURCE = IMPL_DIR / "animal_shogi.py"
PREV_SOURCE = ROOT / "impl" / "04_resident_unknown" / "animal_shogi.py"

CHANGED = {"searchWinBoard", "searchLoseBoard"}
ADDED = {"writeWLFilesForDepth"}


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
    """C・ヘッダ・Makefile はベースラインとバイト単位で同一 (＝ -O0 のまま)。"""
    for name in ("animal_shogi.c", "animal_shogi.h", "Makefile"):
        assert (IMPL_DIR / name).read_bytes() == (BASELINE_DIR / name).read_bytes(), (
            f"impl/05_batch_wl_write/{name} がベースラインと違う。"
            f"この試行で変えるのは書き出しの粒度だけ"
        )


def test_only_the_two_retreat_phases_changed() -> None:
    """全探索側が1バイトも動いていないこと。これが対照群の担保になる。"""
    prev = top_level_functions(PREV_SOURCE)
    cur = top_level_functions(SOURCE)
    changed = {n for n in prev if n in cur and cur[n] != prev[n]}
    assert changed == CHANGED, f"想定外の関数が変わっている: {changed ^ CHANGED}"
    assert set(cur) - set(prev) == ADDED, "想定外の関数が増えている"
    assert not set(prev) - set(cur), "関数が消えている"

    for name in ("searchNext", "searchAll", "buildSeenBoards", "updateUKFile", "updateWLFile"):
        assert cur[name] == prev[name], f"{name} が impl/04 から変わっている"


def test_updateWLFile_is_kept_for_the_forward_search() -> None:
    """前向き探索はまだ追記方式のまま。そこは今回の対照群なので触らない。

    前向き側にも同じ往復が 639,329,035 要素ぶん残っている (次のレバーの候補)。
    """
    cur = top_level_functions(SOURCE)
    assert "updateWLFile" in cur, "updateWLFile を消してしまっている"
    assert "updateWLFile(win_boards, 1, True)" in cur["searchNext"]
    assert "updateWLFile(lose_boards, 0, False)" in cur["searchNext"]


def test_the_retreat_phases_no_longer_append_per_chunk() -> None:
    """チャンクループの中でファイルに触らないこと。"""
    cur = top_level_functions(SOURCE)
    for name, acc, new in (
        ("searchWinBoard", "depth_wins", "new_win_boards"),
        ("searchLoseBoard", "depth_loses", "new_lose_boards"),
    ):
        body = cur[name]
        assert "updateWLFile" not in body, f"{name} がまだチャンクごとに追記している"
        assert f"{acc} += {new}" in body, f"{name} が深さぶんを貯めていない"
        assert f"writeWLFilesForDepth({acc}," in body, f"{name} が深さごとの書き出しをしていない"
        # 貯めてから書く。逆だとその深さのぶんが落ちる
        assert body.index(f"{acc} += {new}") < body.index("writeWLFilesForDepth")


def test_the_depth_write_never_reads() -> None:
    """読み直しは「減らす」ではなく「無くす」。追記しないなら読む理由が無い。"""
    body = top_level_functions(SOURCE)["writeWLFilesForDepth"]
    assert "pickle.load" not in body, "まだ既存ファイルを読んでいる"
    assert '"rb"' not in body, "まだ既存ファイルを開いている"
    assert "BOARD_NUM_MAX" in body, "上限で分割していない"


def test_an_empty_depth_still_creates_a_file() -> None:
    """0件の深さでもファイルを作る。次の手数の導出が存在を見ている。

    終端 (174手負けが0件) で効く。fingerprint_dat.py の照合項目にもなっている。
    """
    body = top_level_functions(SOURCE)["writeWLFilesForDepth"]
    assert "if not wlbl:" in body
    assert "if wl_sub == 0:" in body


def test_no_impl_env_needed() -> None:
    """構成がベースラインと同じなので、ハーネスの既定値でそのまま走る。"""
    assert not (IMPL_DIR / "impl.env").exists()
