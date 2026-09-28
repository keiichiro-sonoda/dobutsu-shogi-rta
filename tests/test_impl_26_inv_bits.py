"""impl/26_inv_bits — 盤面の反転 `invBoard()` をループと分岐の無い形にする。

変数は1つ。`experiments/gen_bench/patches/invbits.patch` (gen_bench の候補 B) を入れた。
コードはパッチのまま、コメントだけを記録の実装として書き直した。
`.py` / `.h` / `Makefile` は impl/25 とバイト同一。

⚠️ 出力は全 246,803,167 局面で旧版と1ビットも違わないことを experiments/gen_bench が
確かめている。ここではそれを小さく固定する: 乱数の盤と端の場合で `invBoard()` を新旧で
突き合わせ、小さい上限で回した成果物が impl/25 とバイト一致することを見る。
"""

from __future__ import annotations

import ctypes
import pathlib
import random
import shutil
import subprocess
from typing import Any

import pytest
from conftest import ROOT, impl_library, load_impl
from test_impl_22_in_memory import limited_run
from test_impl_23_loop_prefetch import code_only, function_body

IMPL = "26_inv_bits"
PREV = "25_huge_retreat"
IMPL_DIR = ROOT / "impl" / IMPL
PREV_DIR = ROOT / "impl" / PREV
PATCH = ROOT / "experiments" / "gen_bench" / "patches" / "invbits.patch"
SIGNATURE = "u_long invBoard("
SEED = 20260928


def c_source(directory: pathlib.Path) -> str:
    return (directory / "animal_shogi.c").read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# 構造
# --------------------------------------------------------------------------


def test_everything_but_the_c_is_byte_identical_to_impl_25() -> None:
    for name in ("animal_shogi.py", "animal_shogi.h", "Makefile"):
        assert (IMPL_DIR / name).read_bytes() == (PREV_DIR / name).read_bytes(), name


def test_no_impl_env_needed() -> None:
    assert not (IMPL_DIR / "impl.env").exists(), "既定のビルド・実行コマンドで走るはず"


def test_the_c_is_impl_25_plus_the_patch(tmp_path: pathlib.Path) -> None:
    """★C のコード (コメントを除く) が「impl/25 ＋ invbits.patch」と一致する。

    パッチはテストの中で当てる (fuzz なし)。門番の2腕の差がこのパッチだけであることの根拠。
    """
    if shutil.which("patch") is None:
        pytest.skip("patch が無い")
    shutil.copy(PREV_DIR / "animal_shogi.c", tmp_path / "animal_shogi.c")
    with PATCH.open("rb") as f:
        done = subprocess.run(
            [
                "patch",
                "--forward",
                "--fuzz=0",
                "--no-backup-if-mismatch",
                "-p1",
                "-d",
                str(tmp_path),
            ],
            stdin=f,
            capture_output=True,
            check=False,
        )
    assert done.returncode == 0, f"invbits.patch が当たらない:\n{done.stdout!r}"
    assert code_only(c_source(IMPL_DIR)) == code_only(c_source(tmp_path))


def test_only_inv_board_changed() -> None:
    """★変わったのは `invBoard()` (とその上のコメント) だけ。ほかはコメントまでバイト同一。"""

    def without_inv_board(text: str) -> str:
        body = function_body(text, SIGNATURE)
        start = text.index("// 先手後手入れ替え\n")
        return text[:start] + text[text.index(body) + len(body) :]

    new, old = c_source(IMPL_DIR), c_source(PREV_DIR)
    assert new != old
    assert without_inv_board(new) == without_inv_board(old)


def test_the_new_inv_board_has_no_loop_or_branch() -> None:
    """★ループも分岐も無い。名前・引数・戻り値の型は変えない。"""
    body = "\n".join(code_only(function_body(c_source(IMPL_DIR), SIGNATURE)))
    assert body.startswith("u_long invBoard(u_long b) {")
    for word in ("for", "while", "if", "?", "getKoma", "putKoma"):
        assert word not in body.split("{", 1)[1], word
    assert "__builtin_bswap64" in body


@pytest.mark.parametrize("extra", [[], ["-Wextra"]])
def test_the_c_builds_without_warnings(tmp_path: pathlib.Path, extra: list[str]) -> None:
    """★`make animal_shogi.so` (`-Wall`) が通り、`-Wextra` を足しても警告を1つも出さないこと。"""
    if shutil.which("gcc") is None or shutil.which("make") is None:
        pytest.skip("gcc か make が無い")
    for name in ("animal_shogi.c", "animal_shogi.h", "Makefile"):
        shutil.copy(IMPL_DIR / name, tmp_path / name)
    if extra:
        cmd = ["gcc", "-O2", "-Wall", *extra, "-fPIC", "-shared", "animal_shogi.c", "-o", "x.so"]
    else:
        cmd = ["make", "animal_shogi.so"]
    done = subprocess.run(cmd, cwd=tmp_path, capture_output=True, text=True, check=False)
    assert done.returncode == 0, f"ビルドが失敗した:\n{done.stdout}\n{done.stderr}"
    assert "warning" not in done.stderr.lower(), f"警告が出ている:\n{done.stderr}"


# --------------------------------------------------------------------------
# invBoard() を新旧で突き合わせる
# --------------------------------------------------------------------------


def boards() -> list[int]:
    """突き合わせる盤 (64ビット)。端の場合と、固定の種の乱数。

    旧版も新版も上位16ビット (持ち駒と未使用の4ビット) を同じ式で扱うので、どんな 64 ビット値でも
    一致するはず。駒の値として有り得ない値 (所有者ビットだけの 0b1000 など) も混ぜる。
    """
    full = (1 << 48) - 1
    out = [0, full, full << 16 & ((1 << 64) - 1), (1 << 64) - 1, 0xFFF << 48, 0x0888_8888_8888]
    out += [0x8 << (4 * i) for i in range(12)]  # 所有者ビットだけのマス1つ (旧版は 0 に反転)
    out += [0x1 << (4 * i) for i in range(12)]  # 駒1つ、ほかは空き
    out += [0xF << (4 * i) | 0x3F << 48 for i in range(12)]  # 駒1つ ＋ 先手の持ち駒
    out += [full ^ 0xF << (4 * i) | 0x3F << 54 for i in range(12)]  # 空き1つ ＋ 後手の持ち駒
    rng = random.Random(SEED)
    out += [rng.getrandbits(64) for _ in range(20000)]
    # 本物に近い盤: 各マスが空きか、駒 1〜5 に所有者ビットを付けたもの
    for _ in range(20000):
        b = 0
        for i in range(12):
            if rng.random() < 0.6:
                b |= rng.choice((1, 2, 3, 4, 5, 9, 10, 11, 12, 13)) << (4 * i)
        out.append(b | rng.getrandbits(12) << 48)
    return out


def inv_board(impl: str) -> Any:
    lib = ctypes.CDLL(str(impl_library(impl)))
    fn = lib.invBoard
    fn.restype = ctypes.c_ulong
    fn.argtypes = [ctypes.c_ulong]
    return fn


def test_inv_board_agrees_with_impl_25() -> None:
    """★乱数の盤と端の場合で、新旧の `invBoard()` が全ビット一致する。"""
    if shutil.which("gcc") is None:
        pytest.skip("gcc が無い")
    old, new = inv_board(PREV), inv_board(IMPL)
    cases = boards()
    differ = [hex(b) for b in cases if old(b) != new(b)]
    assert differ == [], f"{len(differ)} / {len(cases)} 個で違う: {differ[:5]}"


def test_inv_board_is_an_involution_on_real_boards() -> None:
    """★2回反転すると元に戻る。旧版と同じ性質。

    除くのは、持ち駒の上の未使用の4ビットが立った盤と、所有者ビットだけのマス (0b1000) がある盤
    (反転で空きマスになる)。どちらも本物の盤には無い。
    """
    if shutil.which("gcc") is None:
        pytest.skip("gcc が無い")
    new = inv_board(IMPL)
    for b in boards():
        if b >> 60 == 0 and all(b >> (4 * i) & 0xF != 0x8 for i in range(12)):
            assert new(new(b)) == b, hex(b)


# --------------------------------------------------------------------------
# 走らせて impl/25 と突き合わせる
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def runs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, dict[str, Any]]:
    """impl/25 と impl/26 を、同じ上限・同じラウンド数で打ち切って後退解析まで回す。"""
    if shutil.which("gcc") is None:
        pytest.skip("gcc が無い")
    out: dict[str, dict[str, Any]] = {}
    for impl in (PREV, IMPL):
        work = tmp_path_factory.mktemp(impl)
        out[impl] = limited_run(load_impl(impl, work, impl_library(impl)), work)
    return out


def test_the_rounds_and_p0_agree_with_impl_25(runs: dict[str, dict[str, Any]]) -> None:
    """★ラウンドごとの件数と、P0 に渡る中身・P0 が詰めたバイト列が impl/25 と一致する。"""
    a, b = runs[PREV], runs[IMPL]
    assert len(a["counts"]) > 10
    for key in ("counts", "queue", "uk_all", "catch_wins", "try_loses", "tbn", "packed", "n"):
        assert a[key] == b[key], key


def test_the_artifacts_are_byte_identical_to_impl_25(runs: dict[str, dict[str, Any]]) -> None:
    """★後退解析まで回した成果物が impl/25 とバイト一致する (生成器の後続の順番も同じ)。"""
    da, db = runs[PREV]["work"] / "dat", runs[IMPL]["work"] / "dat"
    names = sorted(p.name for p in da.iterdir())
    assert names == sorted(p.name for p in db.iterdir()), "ファイルの顔ぶれが違う"
    assert len(names) > 3, f"成果物が少なすぎる (テストが空振り): {names}"
    differ = [n for n in names if (da / n).read_bytes() != (db / n).read_bytes()]
    assert differ == [], f"バイトが違うファイルがある: {differ[:5]}"


def test_the_retreat_totals_agree_with_impl_25(runs: dict[str, dict[str, Any]]) -> None:
    def totals(work: pathlib.Path) -> list[str]:
        text = (work / "kaiseki_log" / "kaizenkaiseki1.txt").read_text(encoding="utf-8")
        return [ln for ln in text.splitlines() if "盤面総数" in ln]

    a = totals(runs[PREV]["work"])
    assert len(a) > 2, f"深さが進んでいない: {a}"
    assert a == totals(runs[IMPL]["work"])
