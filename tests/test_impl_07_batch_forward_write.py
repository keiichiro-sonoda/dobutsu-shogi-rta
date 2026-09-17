"""impl/07_batch_forward_write — 前向き探索の終端書き出しを最後の1回にまとめた版。

1試行1変数。変えたのは「ラウンドごとに末尾ファイルへ追記する」のをやめて
「全探索の最後に1回だけ書く」だけ。後退解析も未知盤面の書き出しも触っていない。

記録 #5 で後退解析側にやったのと同じ修正で、あのとき「全探索は対照群として
空けておけ」と決めたために片側だけ残っていたもの。#6 のログから数え直すと、
名簿に載る 147,317,599 局面に対して書き写した延べ要素は 639,329,035 あった。

⚠️ この版から `buildSeenBoards()` は win001te_* / lose000te_* を読めなくなる。
初回ラウンドは初期局面1個しか見ず終端が0個なので新規の走行では影響しないが、
途中の dat/ から再開すると終端が seen に入らない (それは再走する場面)。
"""

from __future__ import annotations

import ast
import pathlib

from conftest import BASELINE_DIR, ROOT

IMPL_DIR = ROOT / "impl" / "07_batch_forward_write"
SOURCE = IMPL_DIR / "animal_shogi.py"
PREV_SOURCE = ROOT / "impl" / "06_csr_counter" / "animal_shogi.py"

CHANGED = {"searchNext", "searchAll"}
ADDED = {"flushTerminalBoards"}
REMOVED = {"updateWLFile"}

# 後退解析は今回の対照群。1バイトも動かさない
UNTOUCHED_RETREAT = (
    "retreatAnalysis",
    "appendFamily",
    "loadForwardResult",
    "buildIndex",
    "buildSuccessors",
    "buildPredecessors",
    "loadAllUnknownBoards",
    "writeUnknownChunks",
)

# 前向き側でも、今回の変数に入らないものはそのまま
UNTOUCHED_FORWARD = (
    "buildSeenBoards",
    "updateUKFile",
    "writeWLFilesForDepth",
    "nextBoardInvNormalWrap",
    "writeAndBackup",
    "s2hms",
    "main",
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


def test_c_and_build_are_untouched() -> None:
    """C・ヘッダ・Makefile はベースラインとバイト単位で同一 (＝ -O0 のまま)。"""
    for name in ("animal_shogi.c", "animal_shogi.h", "Makefile"):
        assert (IMPL_DIR / name).read_bytes() == (BASELINE_DIR / name).read_bytes(), (
            f"impl/07_batch_forward_write/{name} がベースラインと違う。"
            f"この試行で変えるのは書き出しの粒度だけ"
        )


def test_only_the_forward_write_changed() -> None:
    """後退解析が1バイトも動いていないこと。これが対照群の担保になる。"""
    prev = top_level_functions(PREV_SOURCE)
    cur = top_level_functions(SOURCE)
    changed = {n for n in prev if n in cur and cur[n] != prev[n]}
    assert changed == CHANGED, f"想定外の関数が変わっている: {changed ^ CHANGED}"
    assert set(cur) - set(prev) == ADDED, f"想定外の関数が増えている: {set(cur) - set(prev)}"
    assert set(prev) - set(cur) == REMOVED, f"想定外の関数が消えている: {set(prev) - set(cur)}"

    for name in UNTOUCHED_RETREAT + UNTOUCHED_FORWARD:
        assert cur[name] == prev[name], f"{name} が impl/06 から変わっている"


def test_the_rounds_no_longer_write_the_terminal_boards() -> None:
    """ラウンドの中ではファイルに触らず、リストに貯めるだけにする。"""
    body = top_level_functions(SOURCE)["searchNext"]
    assert "updateWLFile" not in body, "まだラウンドごとに追記している"
    assert "catch_wins += win_boards" in body, "キャッチを貯めていない"
    assert "try_loses += lose_boards" in body, "トライ負けを貯めていない"


def test_the_unknown_boards_are_left_alone() -> None:
    """updateUKFile() には手を出さない。1試行1変数のため。

    ⚠️ まったく同じ往復が未知盤面側にも 447,713,018 要素ぶん残っている (次のレバー)。
    """
    prev = top_level_functions(PREV_SOURCE)
    cur = top_level_functions(SOURCE)
    assert cur["updateUKFile"] == prev["updateUKFile"]
    assert "updateUKFile(uk_boards)" in cur["searchNext"], "未知盤面の書き出しまで消している"


def test_the_flush_happens_inside_the_measured_forward_search() -> None:
    """★書き出しは「全探索終了」のログより前。でないと全探索側に計上されない。"""
    body = top_level_functions(SOURCE)["searchAll"]
    assert "flushTerminalBoards()" in body, "貯めたぶんを書き出していない"
    assert body.index("flushTerminalBoards()") < body.index("で全探索終了"), (
        "書き出しが全探索の計測区間の外にある。タイムの内訳が嘘になる"
    )


def test_the_flush_reuses_the_depth_writer_and_releases_the_lists() -> None:
    """#5 で作った writeWLFilesForDepth をそのまま使い、書いたら手放す。"""
    body = top_level_functions(SOURCE)["flushTerminalBoards"]
    assert "writeWLFilesForDepth(catch_wins, 1, True)" in body
    assert "writeWLFilesForDepth(try_loses, 0, False)" in body
    assert "pickle.load" not in body and '"rb"' not in body, "書き出しなのに読んでいる"
    # 後退解析が 30 GiB 級の構築に入る前に 147,317,599 件ぶんを解放する
    assert body.index("catch_wins = []") > body.index("writeWLFilesForDepth(catch_wins")
    assert "try_loses = []" in body


def test_the_accumulators_are_module_level() -> None:
    """ラウンドをまたいで貯めるので、モジュール変数でなければならない。"""
    text = SOURCE.read_text(encoding="utf-8")
    assert "\ncatch_wins = []\n" in text, "catch_wins がモジュール変数でない"
    assert "\ntry_loses = []\n" in text, "try_loses がモジュール変数でない"
    for name in ("searchNext", "flushTerminalBoards"):
        body = top_level_functions(SOURCE)[name]
        assert "global" in body and "catch_wins" in body, f"{name} で global 宣言が無い"


def test_the_restart_caveat_is_written_down() -> None:
    """再開したときに終端が seen に入らなくなる。黙って変えない。

    buildSeenBoards() は win001te_* / lose000te_* を読んで seen と tbn_* を作るが、
    その2系統は全探索が終わるまで書かれなくなる。
    """
    text = SOURCE.read_text(encoding="utf-8")
    assert "再走" in text, "落ちたら再走になる旨が書かれていない"
    assert "buildSeenBoards()" in top_level_functions(SOURCE)["searchNext"], (
        "順序依存が変わることがコメントに残っていない"
    )


def test_no_impl_env_needed() -> None:
    """構成がベースラインと同じなので、ハーネスの既定値でそのまま走る。"""
    assert not (IMPL_DIR / "impl.env").exists()
