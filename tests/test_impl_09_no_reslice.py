"""impl/09_no_reslice — 分割書き出しの「残りを作り直す」スライスをやめた版。

計装 (experiments/forward_profile/) で、実行全体のピーク RSS 23.73 GiB が
終端の書き出しの中で立つことが測れた。その +1.98 GiB の一過性は

    while wlbl:
        writeAndBackup(..., set(wlbl[:BOARD_NUM_MAX]))
        wlbl = wlbl[BOARD_NUM_MAX:]      # 残り全部を毎回コピーし直す

で、呼び出し元が元のリストを持ったままなので「元 + 残り1 + 残り2」が同居する
瞬間だと推定されている (バイト数が 0.5 MB 差で合う)。同型が4箇所あり、全部を
「添字で区切って集合にする」形に直す。

⚠️ 時間効果は測定限界以下。目的はピーク RSS。
🔑 区切りの位置も要素も動かないので、成果物は impl/08 と**バイト単位で**同一になる。
指紋ではなくバイト比較で検査する (本走の主検査も同じ)。
"""

from __future__ import annotations

import ast
import pathlib
import re

from conftest import ROOT, load_impl, run_forward, run_retreat

IMPL_DIR = ROOT / "impl" / "09_no_reslice"
PREV_DIR = ROOT / "impl" / "08_c_index"
SOURCE = IMPL_DIR / "animal_shogi.py"
PREV_SOURCE = PREV_DIR / "animal_shogi.py"

# 同型の4箇所。これ以外は impl/08 から1バイトも動かさない
CHANGED = {"writeWLFilesForDepth", "updateUKFile", "searchNext", "writeUnknownChunks"}

# 「残りを作り直す」形。x = x[BOARD_NUM_MAX:]
RESLICE = re.compile(r"^\s*(\w+)\s*=\s*\1\[BOARD_NUM_MAX:\]")

# 分割を小さく何度も起こすための上限。本番は 5,000,000
SMALL_BOARD_NUM_MAX = 3000
ROUNDS = 40


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


def code_lines(body: str) -> list[str]:
    """コメント行を除いたコードの行。罠を警告するコメントに引っかからないため。"""
    return [ln for ln in body.splitlines() if not ln.lstrip().startswith("#")]


def test_c_and_build_are_untouched() -> None:
    """C・ヘッダ・Makefile は impl/08 とバイト単位で同一 (索引はそのまま、-O0 のまま)。"""
    for name in ("animal_shogi.c", "animal_shogi.h", "Makefile"):
        assert (IMPL_DIR / name).read_bytes() == (PREV_DIR / name).read_bytes(), (
            f"impl/09_no_reslice/{name} が impl/08 と違う。"
            f"この試行で変えるのは Python の書き出しだけ"
        )


def test_only_the_four_writers_changed() -> None:
    """同型の4箇所だけ。関数の追加も削除も無し。"""
    prev = top_level_functions(PREV_SOURCE)
    cur = top_level_functions(SOURCE)
    changed = {n for n in prev if n in cur and cur[n] != prev[n]}
    assert changed == CHANGED, f"想定外の関数が変わっている: {changed ^ CHANGED}"
    assert set(cur) == set(prev), f"関数の顔ぶれが変わっている: {set(cur) ^ set(prev)}"


def test_no_reslice_remains() -> None:
    """★`x = x[BOARD_NUM_MAX:]` が1つも残っていないこと。4箇所とも添字で区切る。"""
    text = SOURCE.read_text(encoding="utf-8")
    left = [ln for ln in code_lines(text) if RESLICE.match(ln)]
    assert left == [], f"残りを作り直すスライスが残っている: {left}"

    funcs = top_level_functions(SOURCE)
    # 何度も分割する3箇所は添字のループ
    for name in CHANGED - {"updateUKFile"}:
        code = "\n".join(code_lines(funcs[name]))
        assert "[start:start + BOARD_NUM_MAX]" in code, f"{name} が添字で区切っていない"
        assert "range(0, " in code, f"{name} が range で回っていない"
    # 未知盤面は分割が最大1回 (ukl ≤ 2×BOARD_NUM_MAX が常に成り立つ) なので、残りを直接集合にする
    code = "\n".join(code_lines(funcs["updateUKFile"]))
    assert "set(ukl[BOARD_NUM_MAX:])" in code, "updateUKFile が残りを直接集合にしていない"


def test_the_chunk_numbering_is_preserved() -> None:
    """③ 未探索の書き出しは、先頭が latest 番、以後 +1。④ は空でも1ファイル作る。"""
    funcs = top_level_functions(SOURCE)
    body = "\n".join(code_lines(funcs["searchNext"]))
    assert "UNEXP_PATH_FORMAT.format(latest)" in body, "未探索の先頭チャンクが latest 番でない"
    assert body.index("UNEXP_PATH_FORMAT.format(latest), set(new_unexp_boards[start") < body.index(
        "latest += 1"
    ), "番号を進めてから書いている (先頭チャンクの番号がずれる)"

    body = "\n".join(code_lines(funcs["writeUnknownChunks"]))
    assert "if not rest:" in body and "set())" in body, "空でも1ファイル作る分岐が消えている"


def test_no_impl_env_needed() -> None:
    """構成がベースラインと同じなので、ハーネスの既定値でそのまま走る。"""
    assert not (IMPL_DIR / "impl.env").exists()


def test_the_artifacts_are_byte_identical_to_impl_08(
    shared_library: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """★本走の主検査を小さく再現する。dat/ がファイル名もバイト列も impl/08 と同一。

    分割が何度も起きる上限で全探索を回し、続けて後退解析も最後まで回す。
    4箇所 (未探索 / 未知 / 終端と深さごとの勝ち負け / 引き分け) の書き出しを全部通る。
    `set(list[a:b])` と旧コードの `set(作り直したリスト)` は同じ順に要素を足すので、
    集合の表 → 反復順 → pickle のバイト列まで同一になるはず。
    """
    dats: dict[str, pathlib.Path] = {}
    for impl in ("08_c_index", "09_no_reslice"):
        work = tmp_path / impl
        module = load_impl(impl, work, shared_library)
        run_forward(module, work, ROUNDS, SMALL_BOARD_NUM_MAX)
        run_retreat(module, work)
        dats[impl] = work / "dat"

    def listing(dat: pathlib.Path) -> dict[str, bytes]:
        return {p.name: p.read_bytes() for p in dat.iterdir() if p.is_file()}

    prev, cur = listing(dats["08_c_index"]), listing(dats["09_no_reslice"])

    # 空振り防止: 4系統とも分割が起きている (＝4箇所の書き出しを通った)
    for prefix in ("unexplored", "unknown", "win", "lose"):
        n = sum(1 for name in prev if name.startswith(prefix))
        assert n >= 2, f"impl/08 で {prefix} が {n} ファイルしかない (分割が起きていない)"

    assert set(prev) == set(cur), f"ファイルの顔ぶれが違う: {set(prev) ^ set(cur)}"
    differ = sorted(name for name in prev if prev[name] != cur[name])
    assert differ == [], f"バイト列が違うファイル: {differ}"
