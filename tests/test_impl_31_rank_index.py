"""impl/31_rank_index — 後退解析の索引を「ランク → 連番」の対応表にする。

変数は1つ。#30 までの索引 (パック値 → 連番のオープンアドレス法のハッシュ表, 16 B のエントリ,
本番 2^29 スロット = 8 GiB) を, #30 のランク (正規化した盤面どうしで単射, 値域 855,232,344) を
添字にした uint32_t の表 (3.42 GB) に替えた。連番は今までと同じ (packed の並びの添字) なので,
採番順も成果物も #30 と変わらないはず。`.py` と `Makefile` は #30 とバイト同一。

ここで固定するもの:

- 差分の範囲 (`.c` は索引の節だけ, `.h` は索引の宣言の節だけ)
- 新しい索引が, 素朴な対応 (Python の dict) と同じ連番を返す (到達局面の標本で)
- 重複キーで -5, 番兵で -4, 索引にない後続で -2 が返る
- 打ち切って後退解析まで回した成果物が #30 とバイト一致する (それぞれの Makefile の .so で)
"""

from __future__ import annotations

import ctypes
import pathlib
import random
import shutil
from array import array
from typing import Any

import conftest
import pytest
from conftest import ROOT, load_impl
from test_impl_22_in_memory import limited_run
from test_impl_23_loop_prefetch import code_only
from test_impl_27_no_interposition import make_so
from test_impl_30_rank_seen import normal_board, random_board

IMPL = "31_rank_index"
PREV = "30_rank_seen"
IMPL_DIR = ROOT / "impl" / IMPL
PREV_DIR = ROOT / "impl" / PREV
SEED = 20261004
MAX_ACTION_NUM = 48
INDEX_EMPTY = (1 << 64) - 1


def text(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def section(src: str, head: str, tail: str) -> tuple[str, str]:
    start = src.index(head)
    end = src.index(tail, start)
    return src[:start] + src[end:], src[start:end]


# --------------------------------------------------------------------------
# 1変数であること (差分の範囲)
# --------------------------------------------------------------------------


def test_the_python_and_the_makefile_are_byte_identical_to_impl_30() -> None:
    """★`.py` と `Makefile` は #30 とバイト同一。ctypes から見える口は名前も型も同じ。"""
    for name in ("animal_shogi.py", "Makefile"):
        assert (IMPL_DIR / name).read_bytes() == (PREV_DIR / name).read_bytes(), name


def test_only_the_index_sections_of_the_c_changed() -> None:
    """★`.c` で変わったのは索引の宣言と, `indexFree` / `indexBuild` / `nextBoardIndexNormal` だけ。

    索引の宣言と関数のあいだにある巨大ページの確保 (記録 #21・#25) はコメントまでバイト同一。
    """
    old, new = text(PREV_DIR / "animal_shogi.c"), text(IMPL_DIR / "animal_shogi.c")
    head1, tail1 = "// パック値 -> 連番 の索引", "// ---- 2 MiB ページを頼んで確保する (記録 #21)"
    head2, tail2 = "void indexFree(void) {", "// ---- 全探索の発見済み集合: ランクで引く"
    old_rest, _ = section(old, head1, tail1)
    new_rest, new_decl = section(new, head1, tail1)
    old_rest, _ = section(old_rest, head2, tail2)
    new_rest, new_funcs = section(new_rest, head2, tail2)
    assert new_rest == old_rest
    code = "\n".join(code_only(new_decl + new_funcs))
    for word in ("IndexEntry", "INDEX_SLOT", "INDEX_MULT", "g_index_mask"):
        assert word not in code, word
    assert "rankOf(" in code and "uint32_t *g_index" in code


def test_only_the_index_declarations_of_the_header_changed() -> None:
    """★`.h` で変わったのは索引の宣言の節だけ (ハッシュ表の定数とエントリの型を外した)。"""
    head, tail = (
        "// 記録 #8: パック値 -> 連番 の索引をC側に置く",
        "// 既存の nextBoardInvNormal と同じ規約だが",
    )
    old_rest, _ = section(text(PREV_DIR / "animal_shogi.h"), head, tail)
    new_rest, new_sec = section(text(IMPL_DIR / "animal_shogi.h"), head, tail)
    assert new_rest == old_rest
    assert "#define INDEX_EMPTY" in new_sec and "IndexEntry" not in new_sec


def test_no_impl_env_needed() -> None:
    assert not (IMPL_DIR / "impl.env").exists()


# --------------------------------------------------------------------------
# 索引そのもの (ctypes で直接呼ぶ)
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def lib(tmp_path_factory: pytest.TempPathFactory) -> Any:
    if shutil.which("gcc") is None or shutil.which("make") is None:
        pytest.skip("gcc か make が無い")
    so = make_so(IMPL_DIR, tmp_path_factory.mktemp("index"))
    handle = ctypes.CDLL(str(so))
    handle.indexBuild.restype = ctypes.c_int32
    handle.indexBuild.argtypes = [ctypes.POINTER(ctypes.c_uint64), ctypes.c_uint32]
    handle.indexFree.restype = None
    handle.nextBoardIndexNormal.restype = ctypes.c_int32
    handle.nextBoardIndexNormal.argtypes = [ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)]
    handle.nextBoardInvNormal.restype = ctypes.c_int32
    handle.nextBoardInvNormal.argtypes = [ctypes.c_uint64, ctypes.POINTER(ctypes.c_uint64)]
    return handle


def build(lib: Any, keys: list[int]) -> tuple[int, array[int]]:
    packed = array("Q", keys)
    ptr = ctypes.cast(packed.buffer_info()[0], ctypes.POINTER(ctypes.c_uint64))
    return lib.indexBuild(ptr, len(packed)), packed


def successors(lib: Any, b: int) -> list[int]:
    out = (ctypes.c_uint64 * MAX_ACTION_NUM)()
    n = lib.nextBoardInvNormal(b, out)
    return list(out[:n]) if n > 0 else []


def reachable_sample(lib: Any, n: int) -> list[int]:
    """初期局面から幅優先でたどった正規化済みの局面 (到達局面の標本)。"""
    start = 0x000A003C914B002
    seen, queue = {start}, [start]
    while queue and len(seen) < n:
        b = queue.pop(0)
        for nb in successors(lib, b):
            if nb not in seen:
                seen.add(nb)
                queue.append(nb)
    return list(seen)[:n]


def test_the_index_returns_the_same_serials_as_a_dict(lib: Any) -> None:
    """★到達局面の標本で, 後続の連番が素朴な対応 (dict) と同じ。索引にない後続は -2 で数が返る。"""
    keys = reachable_sample(lib, 20000)
    random.Random(SEED).shuffle(keys)
    # C は packed を指したまま引くので, 引き終わるまで配列を生かしておく
    rc, _packed = build(lib, keys)
    assert rc == 0
    naive = {k: i for i, k in enumerate(keys)}
    out = (ctypes.c_uint32 * (MAX_ACTION_NUM + 2))()
    full = partial = 0
    for src, b in enumerate(keys):
        nbs = successors(lib, b)
        k = lib.nextBoardIndexNormal(src, out)
        if not nbs:
            assert k <= 0
            continue
        want = [naive[nb] for nb in nbs if nb in naive]
        if len(want) == len(nbs):
            assert k == len(nbs) and list(out[:k]) == want
            full += 1
        else:
            assert k == -2
            assert out[MAX_ACTION_NUM] == len(want) and out[MAX_ACTION_NUM + 1] == len(nbs)
            assert list(out[: len(want)]) == want
            partial += 1
    assert full > 100 and partial > 100, (full, partial)
    lib.indexFree()


def test_duplicates_and_invalid_keys_are_rejected(lib: Any) -> None:
    """★重複キーで -5 (3群が互いに素であることの検算), 番兵で -4 (#30 までと同じ意味)。"""
    rng = random.Random(SEED + 1)
    keys = list({normal_board(random_board(rng)) for _ in range(1000)})
    assert build(lib, keys)[0] == 0
    assert build(lib, [*keys, keys[3]])[0] == -5
    assert build(lib, [*keys, INDEX_EMPTY])[0] == -4
    lib.indexFree()


def test_the_index_is_freed(lib: Any) -> None:
    """★indexFree のあとは -3 (索引が未構築)。"""
    lib.indexFree()
    out = (ctypes.c_uint32 * (MAX_ACTION_NUM + 2))()
    assert lib.nextBoardIndexNormal(0, out) == -3


# --------------------------------------------------------------------------
# 走らせて impl/30 と突き合わせる (それぞれの Makefile の .so で)
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def runs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, dict[str, Any]]:
    """⚠️ `load_impl()` は自前の C を持つ実装に `conftest.impl_library()` (-O0 の自前の gcc 行) の
    `.so` を差し込むので、ここだけそれを Makefile で作った `.so` に差し替える。"""
    if shutil.which("gcc") is None or shutil.which("make") is None:
        pytest.skip("gcc か make が無い")
    root = tmp_path_factory.mktemp("make")
    built = {impl: make_so(ROOT / "impl" / impl, root / impl) for impl in (PREV, IMPL)}
    out: dict[str, dict[str, Any]] = {}
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(conftest, "impl_library", lambda impl: built[impl])
        for impl in (PREV, IMPL):
            work = tmp_path_factory.mktemp(impl)
            module = load_impl(impl, work, built[impl])
            assert (work / "animal_shogi.so").read_bytes() == built[impl].read_bytes()
            out[impl] = limited_run(module, work)
    return out


def test_the_rounds_and_p0_agree_with_impl_30(runs: dict[str, dict[str, Any]]) -> None:
    """★ラウンドごとの件数と、P0 に渡る中身・P0 が詰めたバイト列が impl/30 と一致する。"""
    a, b = runs[PREV], runs[IMPL]
    assert len(a["counts"]) > 10
    for key in ("counts", "queue", "uk_all", "catch_wins", "try_loses", "tbn", "packed", "n"):
        assert a[key] == b[key], key


def test_the_artifacts_are_byte_identical_to_impl_30(runs: dict[str, dict[str, Any]]) -> None:
    """★後退解析まで回した成果物が impl/30 とバイト一致する (連番と採番順が同じ)。"""
    da, db = runs[PREV]["work"] / "dat", runs[IMPL]["work"] / "dat"
    names = sorted(p.name for p in da.iterdir())
    assert names == sorted(p.name for p in db.iterdir()), "ファイルの顔ぶれが違う"
    assert len(names) > 3, f"成果物が少なすぎる (テストが空振り): {names}"
    differ = [n for n in names if (da / n).read_bytes() != (db / n).read_bytes()]
    assert differ == [], f"バイトが違うファイルがある: {differ[:5]}"
