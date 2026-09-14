"""impl/03_resident_seen — 全探索の重複排除をメモリ常駐にした版。

1試行1変数。変えたのは「過去の集合を読み直す回数を毎ラウンド→初回だけ」の1点で、
BFS の構造もチャンク分割も後退解析も触っていない。
記録 #3 のタイム差がその1点の効果だと言えるように、ここで機械的に固定する。

実際に同じ答えを出すかは tests/test_forward_search_equivalence.py が走らせて確かめる。
"""

from __future__ import annotations

import ast
import pathlib
import re

from conftest import BASELINE_DIR, ROOT

IMPL_DIR = ROOT / "impl" / "03_resident_seen"
SOURCE = IMPL_DIR / "animal_shogi.py"
PREV_SOURCE = ROOT / "impl" / "02_resident_wins" / "animal_shogi.py"

# 指示書の「触ってはいけないもの」。impl/02 からソースが1バイトも動いていないこと。
# ここが動いたら、タイム差がどの変更の効果なのか言えなくなる。
UNTOUCHED = (
    "nextBoardInvNormalWrap",
    "writeAndBackup",
    "s2hms",
    "updateWLFile",
    "updateUKFile",
    "countTotalBoardNum",
    "searchWinBoard",
    "searchLoseBoard",
    "addUKBoards",
    "writeUKFiles",
    "organizeUKFiles",
    "loadAllWinBoards",
    "retreatAnalysis",
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


def source_without_comments(path: pathlib.Path) -> str:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("#"):
            continue
        out.append(line.split("#", 1)[0])
    return "\n".join(out)


def test_c_and_build_are_untouched() -> None:
    """C・ヘッダ・Makefile はベースラインとバイト単位で同一 (＝ -O0 のまま)。"""
    for name in ("animal_shogi.c", "animal_shogi.h", "Makefile"):
        assert (IMPL_DIR / name).read_bytes() == (BASELINE_DIR / name).read_bytes(), (
            f"impl/03_resident_seen/{name} がベースラインと違う。"
            f"この試行で変えるのは全探索の重複排除だけ"
        )


def test_everything_but_the_forward_search_is_identical_to_impl_02() -> None:
    """後退解析側とファイル入出力は impl/02 のまま。変えたのは searchNext まわりだけ。"""
    prev = top_level_functions(PREV_SOURCE)
    cur = top_level_functions(SOURCE)
    for name in UNTOUCHED:
        assert name in prev and name in cur, f"{name} がどちらかに無い"
        assert cur[name] == prev[name], f"{name} が impl/02 から変わっている"

    # 変わってよいのは searchNext / searchAll と、新設の buildSeenBoards だけ
    changed = {n for n in prev if n in cur and cur[n] != prev[n]}
    assert changed == {"searchNext", "searchAll"}, f"想定外の関数が変わっている: {changed}"
    assert set(cur) - set(prev) == {"buildSeenBoards"}, "想定外の関数が増えている"
    assert not set(prev) - set(cur), "impl/02 にあった関数が消えている"


def test_search_next_no_longer_reads_the_past_files() -> None:
    """重複排除のためにチャンクを読み直すループが消えていること。"""
    body = top_level_functions(SOURCE)["searchNext"]
    # 残ってよい pickle.load は「今回の未探索チャンク」と「書き込み先の既存分」の2つだけ
    assert body.count("pickle.load") == 2, "searchNext にファイル読み込みが残っている"
    assert "past_boards" not in body, "searchNext に過去チャンクの読み直しが残っている"
    assert "-= " not in body.replace("new_unexp_boards -= seen_boards", ""), (
        "searchNext に常駐集合以外からの差集合が残っている"
    )


def test_the_resident_set_is_subtracted_and_then_extended() -> None:
    """引いてから足す。順番が逆だと、その回の新規が自分自身で消える。"""
    body = top_level_functions(SOURCE)["searchNext"]
    sub = body.index("new_unexp_boards -= seen_boards")
    add = body.index("seen_boards |= new_unexp_boards")
    assert sub < add, "seen_boards への追加が差集合より先に来ている"


def test_totals_are_kept_as_counters() -> None:
    """総数は読み直しループの副産物だった。ループを消した以上カウンタで維持する。

    main.log の「総未知盤面数 / 総勝ち盤面数 / 総負け盤面数」がここから出る。
    """
    body = top_level_functions(SOURCE)["searchNext"]
    for name, boards in (
        ("tbn_uk", "uk_boards"),
        ("tbn_win", "win_boards"),
        ("tbn_lose", "lose_boards"),
    ):
        assert f"{name} += len({boards})" in body, f"{name} がカウンタになっていない"
    assert "global seen_boards, tbn_uk, tbn_win, tbn_lose" in body


def test_the_resident_set_is_built_from_disk_only_once() -> None:
    """初回だけディスクから組み立てる。途中で落ちても次の起動で作り直せること。

    計測機は UPS が無く、2026-09-09 と 2026-09-13 に電源が落ちている。
    毎ラウンド状態をディスクから読む性質は、3時間超の無人稼働の保険なので残す。
    """
    body = top_level_functions(SOURCE)["searchNext"]
    assert "if seen_boards is None:" in body
    assert "buildSeenBoards(offset)" in body

    build = top_level_functions(SOURCE)["buildSeenBoards"]
    # 現行の4ループと同じ4系統を読むこと
    for fmt in ("UK_PATH_FORMAT", "WIN_PATH_FORMAT", "LOSE_PATH_FORMAT", "UNEXP_PATH_FORMAT"):
        assert fmt in build, f"buildSeenBoards が {fmt} を読んでいない"
    # 今まさに空にしたチャンクは読まない (中身は未知/勝ち/負けへ移っている)
    assert "range(offset + 1, LOOP_MAX)" in build


def test_the_resident_set_is_released_before_the_retreat_analysis() -> None:
    """後退解析の勝ち集合と同時に抱えないこと。抱えると 30GiB 級になる。"""
    search_all = top_level_functions(SOURCE)["searchAll"]
    assert "seen_boards = None" in search_all, "全探索の終了時に解放していない"
    assert "global seen_boards" in search_all

    for name in ("retreatAnalysis", "searchWinBoard", "searchLoseBoard", "loadAllWinBoards"):
        assert "seen_boards" not in top_level_functions(SOURCE)[name], (
            f"{name} が全探索の常駐集合を参照している"
        )


def test_the_chunking_itself_is_untouched() -> None:
    """変数は1つ。チャンク分割も辺のため方も触らない (それは次の試行)。"""
    body = source_without_comments(SOURCE)
    assert re.search(r"^BOARD_NUM_MAX = 5000000$", body, re.MULTILINE)
    assert "new_unexp_boards += nbl" in body, "生成時の逐次判定に変わっている (#3 の変数ではない)"


def test_no_impl_env_needed() -> None:
    """構成がベースラインと同じなので、ハーネスの既定値でそのまま走る。"""
    assert not (IMPL_DIR / "impl.env").exists()
