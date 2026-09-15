"""impl/04_resident_unknown — 未知盤面をメモリ常駐にした版。

1試行1変数。変えたのは「未知盤面の置き場所をディスクからメモリへ移す」の1点で、
全探索も指し手の再生成も勝ち集合の常駐方式も触っていない。
記録 #4 のタイム差がその1点の効果だと言えるように、ここで機械的に固定する。

実際に同じ答えを出すかは tests/test_retreat_analysis_equivalence.py が走らせて確かめる。
"""

from __future__ import annotations

import ast
import pathlib

from conftest import BASELINE_DIR, ROOT

IMPL_DIR = ROOT / "impl" / "04_resident_unknown"
SOURCE = IMPL_DIR / "animal_shogi.py"
PREV_SOURCE = ROOT / "impl" / "03_resident_seen" / "animal_shogi.py"

# ディスク上のチャンクを結合するためだけに存在していた機構。
# 結合の判定すらファイルのバイト数で行っていたので、常駐化すると存在理由ごと消える。
REMOVED = {"organizeUKFiles", "addUKBoards", "writeUKFiles"}
ADDED = {"loadAllUnknownBoards", "writeUnknownChunks"}
CHANGED = {"searchWinBoard", "searchLoseBoard", "retreatAnalysis"}


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
            f"impl/04_resident_unknown/{name} がベースラインと違う。"
            f"この試行で変えるのは未知盤面の置き場所だけ"
        )


def test_only_the_retreat_analysis_changed() -> None:
    """全探索側が1バイトも動いていないこと。これが対照群の担保になる。

    記録 #4 では全探索 0:40:30 が誤差内で再現することを予測として登録している。
    ここが動いていたら、その予測は検査にならない。
    """
    prev = top_level_functions(PREV_SOURCE)
    cur = top_level_functions(SOURCE)
    changed = {n for n in prev if n in cur and cur[n] != prev[n]}
    assert changed == CHANGED, f"想定外の関数が変わっている: {changed ^ CHANGED}"
    assert set(cur) - set(prev) == ADDED, "想定外の関数が増えている"
    assert set(prev) - set(cur) == REMOVED, "想定外の関数が消えている"

    for name in ("searchNext", "searchAll", "buildSeenBoards", "updateUKFile", "updateWLFile"):
        assert cur[name] == prev[name], f"{name} が impl/03 から変わっている"


def test_the_unknown_boards_never_touch_the_disk_during_the_analysis() -> None:
    """後退解析の中に未知盤面ファイルの読み書きが残っていないこと。"""
    cur = top_level_functions(SOURCE)
    for name in ("searchWinBoard", "searchLoseBoard"):
        body = cur[name]
        assert "UK_PATH_FORMAT" not in body, f"{name} がまだ未知盤面ファイルを組み立てている"
        assert "writeAndBackup" not in body, f"{name} がまだ未知盤面を書き戻している"
        assert "uk_chunks[i] = new_uk_boards" in body, f"{name} が常駐チャンクを更新していない"
        assert "for i, uk_boards in enumerate(uk_chunks):" in body

    # searchWinBoard に残る pickle は「ひとつ前の手数の負け盤面」の読み込み。
    # 未知盤面とは別物で、今回の変数ではない。
    assert cur["searchWinBoard"].count("pickle.load") == 1
    assert "pickle" not in cur["searchLoseBoard"]


def test_the_unknown_boards_are_kept_as_lists() -> None:
    """所属判定に使われない (pop と len だけ) ので、集合で持つ必要が無い。

    集合だと 2^28 の表で 77B/要素。リストなら 40B/要素で、約 3.5GiB 安い。
    """
    cur = top_level_functions(SOURCE)
    assert "list(pickle.load(f))" in cur["loadAllUnknownBoards"]
    for name in ("searchWinBoard", "searchLoseBoard"):
        assert "set(new_uk_boards)" not in cur[name], f"{name} がまだ集合に変換している"


def test_the_files_are_removed_on_load_and_written_back_at_the_end() -> None:
    """古い未知盤面を残さない。ただし引き分けは成果物として書き出す。"""
    cur = top_level_functions(SOURCE)
    assert "os.remove(fnamer_uk)" in cur["loadAllUnknownBoards"], (
        "読み込んだ未知盤面ファイルを消していない。"
        "途中で落ちたとき「再開できそうに見えて中身が古い」壊れ方をする"
    )
    assert "writeUnknownChunks(uk_chunks)" in cur["retreatAnalysis"], (
        "最後まで未知だった盤面 (引き分け 2,682,700 個) を書き出していない。"
        "tools/fingerprint_dat.py が全局面を照合できなくなる"
    )
    assert "BOARD_NUM_MAX" in cur["writeUnknownChunks"], "書き出しが分割されていない"


def test_the_organize_step_is_gone_from_the_loop() -> None:
    """結合はディスク都合の機構だったので、ループから消えていること。"""
    body = top_level_functions(SOURCE)["retreatAnalysis"]
    assert "organizeUKFiles" not in body
    assert "loadAllUnknownBoards()" in body
    assert "UK_FILE_SIZE_MAX" not in SOURCE.read_text(encoding="utf-8")


def test_no_impl_env_needed() -> None:
    """構成がベースラインと同じなので、ハーネスの既定値でそのまま走る。"""
    assert not (IMPL_DIR / "impl.env").exists()
