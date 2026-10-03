"""impl/30_rank_seen — 全探索の発見済み表を「ランク＋到達済みビット表」に置き換える。

変数は1つ。#28 までの発見済み表 (オープンアドレス法のハッシュ表, 2^20 スロットから倍々,
最終 4 GiB) を, 盤面から番号を計算で直接出す関数 (ランク) を添字にした 1 ビットの表 (106.9 MB)
に替えた。
意味 (初めて見た局面だけを返す) と返す順序は変えていないので, 成果物は #28 とバイト一致するはず。
`.py` と `Makefile` は #28 とバイト同一 (ctypes の口は同じ名前・同じ型のまま)。

ここで固定するもの:

- 差分の範囲 (`.c` は発見済み集合の節だけ, `.h` はその宣言の節だけ)
- ランクの値域 (駒の数と盤の形から数えた 72 x 11,878,227) と, 素朴な実装 (`Naive`) との一致
- 正規化した盤面どうしで単射 (乱数の盤で。#28 の成果物の全局面での確認は門番の rank_check.c)
- 打ち切って後退解析まで回した成果物が #28 とバイト一致する (それぞれの Makefile の .so で)
"""

from __future__ import annotations

import ctypes
import itertools
import math
import pathlib
import random
import shutil
from typing import Any

import conftest
import pytest
from conftest import ROOT, load_impl
from test_impl_22_in_memory import limited_run
from test_impl_23_loop_prefetch import code_only
from test_impl_27_no_interposition import make_so

IMPL = "30_rank_seen"
PREV = "28_march_native"
IMPL_DIR = ROOT / "impl" / IMPL
PREV_DIR = ROOT / "impl" / PREV
SEED = 20261003
INDEX_EMPTY = (1 << 64) - 1

# 駒の値 (animal_shogi.h の enum PEACES)
EMPTY, CHICK1, GIRAFFE1, ELEPHANT1, LION1, CHICKEN1 = 0, 1, 2, 3, 4, 5
CHICK2, GIRAFFE2, ELEPHANT2, LION2, CHICKEN2 = 9, 10, 11, 12, 13
# 1マスの9通りの並び (この順が 9 進数の桁の値)。種類は 0 空き / 1 きりん / 2 ぞう / 3 ひよこ
CODES = [EMPTY, GIRAFFE1, GIRAFFE2, ELEPHANT1, ELEPHANT2, CHICK1, CHICK2, CHICKEN1, CHICKEN2]
KIND = [0, 1, 1, 2, 2, 3, 3, 3, 3]


def text(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# 素朴な実装 (C の前計算の表を使わず, 同じ定義を数えて出す)
# --------------------------------------------------------------------------


def mirror_square(sq: int) -> int:
    return (2 - sq // 4) * 4 + sq % 4


def mirror_board(b: int) -> int:
    a, mid, c = (b >> 32) & 0xFFFF, (b >> 16) & 0xFFFF, b & 0xFFFF
    return ((b >> 48) << 48) | (c << 32) | (mid << 16) | a


def normal_board(b: int) -> int:
    """animal_shogi.c の normalBoard と同じ。"""
    return b if ((b >> 32) & 0xFFFF) <= (b & 0xFFFF) else mirror_board(b)


def sig(counts: list[int]) -> int:
    return counts[1] * 9 + counts[2] * 3 + counts[3]


class Naive:
    """ランクの定義を, 前計算の表を使わずに数え上げで出す。"""

    def __init__(self) -> None:
        # 5マスの 9 進数ごとの (組, 組の中での順位)。順位は「同じ組で, より小さい 9 進数の数」
        self.half: dict[int, tuple[int, int]] = {}
        self.cnt5 = [0] * 27
        for idx in range(9**5):
            counts = [0, 0, 0, 0]
            for i in range(5):
                counts[KIND[idx // 9**i % 9]] += 1
            if max(counts[1:]) <= 2:
                s = sig(counts)
                self.half[idx] = (s, self.cnt5[s])
                self.cnt5[s] += 1
        self.per_class = 0
        self.sigbase = [0] * 27
        for s in range(27):
            self.sigbase[s] = self.per_class
            self.per_class += self.board10(s) * self.handcnt(s)
        # ライオンの組。走査で先に出た側が代表 (鏡像の側は反転して数える)
        self.lion: dict[tuple[int, int], tuple[int, bool]] = {}
        n = 0
        for a, b in itertools.product(range(12), repeat=2):
            if a == b or (a, b) in self.lion:
                continue
            self.lion[(a, b)] = (n, False)
            m = (mirror_square(a), mirror_square(b))
            if m != (a, b):
                self.lion[m] = (n, True)
            n += 1
        self.classes = n

    @staticmethod
    def handcnt(s: int) -> int:
        return (3 - s // 9) * (3 - s // 3 % 3) * (3 - s % 3)

    @staticmethod
    def add(s0: int, s1: int) -> int:
        g, e, c = s0 // 9 + s1 // 9, s0 // 3 % 3 + s1 // 3 % 3, s0 % 3 + s1 % 3
        return -1 if max(g, e, c) > 2 else g * 9 + e * 3 + c

    def board10(self, s: int) -> int:
        return sum(
            self.cnt5[a] * self.cnt5[b] for a in range(27) for b in range(27) if self.add(a, b) == s
        )

    def rank(self, b: int) -> int:
        nib = [(b >> (4 * i)) & 15 for i in range(12)]
        l1, l2 = nib.index(LION1), nib.index(LION2)
        cls, mirror = self.lion[(l1, l2)]
        if mirror:
            b = mirror_board(b)
            nib = [(b >> (4 * i)) & 15 for i in range(12)]
            l1, l2 = mirror_square(l1), mirror_square(l2)
        rest = [CODES.index(nib[i]) for i in range(12) if i not in (l1, l2)]
        idx0 = sum(c * 9**i for i, c in enumerate(rest[:5]))
        idx1 = sum(c * 9**i for i, c in enumerate(rest[5:]))
        (s0, r0), (s1, r1) = self.half[idx0], self.half[idx1]
        s = self.add(s0, s1)
        pairoff = sum(
            self.cnt5[a] * self.cnt5[c] for a in range(s0) for c in range(27) if self.add(a, c) == s
        )
        board_rank = pairoff + r0 * self.cnt5[s1] + r1
        h = b >> 48
        hc, hg, he = h & 3, (h >> 2) & 3, (h >> 4) & 3
        hand = hc + (3 - s % 3) * (hg + (3 - s // 9) * he)
        return cls * self.per_class + self.sigbase[s] + board_rank * self.handcnt(s) + hand


@pytest.fixture(scope="module")
def naive() -> Naive:
    return Naive()


def random_board(rng: random.Random, lions: tuple[int, int] | None = None) -> int:
    """盤面として正しい乱数の盤 (正規化はしない)。ライオンは盤上に1頭ずつ, ほかは種類ごとに2枚。"""
    squares = list(range(12))
    l1, l2 = lions or tuple(rng.sample(squares, 2))
    free = [sq for sq in squares if sq not in (l1, l2)]
    rng.shuffle(free)
    b = (LION1 << (4 * l1)) | (LION2 << (4 * l2))
    hand = [[0, 0, 0], [0, 0, 0]]  # [持ち主][ひよこ, きりん, ぞう]
    for kind, (p1, p2) in enumerate(
        ((CHICK1, CHICK2), (GIRAFFE1, GIRAFFE2), (ELEPHANT1, ELEPHANT2))
    ):
        for _ in range(2):
            owner = rng.randrange(2)
            if free and rng.random() < 0.7:
                koma = (p1, p2)[owner]
                if kind == 0 and rng.random() < 0.3:
                    koma = (CHICKEN1, CHICKEN2)[owner]
                b |= koma << (4 * free.pop())
            else:
                hand[owner][kind] += 1
    for owner in range(2):
        for kind in range(3):
            b |= hand[owner][kind] << (48 + 6 * owner + 2 * kind)
    return b


@pytest.fixture(scope="module")
def lib(tmp_path_factory: pytest.TempPathFactory) -> Any:
    if shutil.which("gcc") is None or shutil.which("make") is None:
        pytest.skip("gcc か make が無い")
    so = make_so(IMPL_DIR, tmp_path_factory.mktemp("rank"))
    handle = ctypes.CDLL(str(so))
    handle.rankBoard.restype = ctypes.c_uint64
    handle.rankBoard.argtypes = [ctypes.c_uint64]
    handle.rankRange.restype = ctypes.c_uint64
    for name in ("seenInsert", "seenContains"):
        getattr(handle, name).restype = ctypes.c_int32
        getattr(handle, name).argtypes = [ctypes.c_uint64]
    handle.seenRehashes.restype = ctypes.c_uint64
    handle.seenCount.restype = ctypes.c_uint64
    return handle


# --------------------------------------------------------------------------
# 1変数であること (差分の範囲)
# --------------------------------------------------------------------------


def test_the_python_and_the_makefile_are_byte_identical_to_impl_28() -> None:
    """★`.py` と `Makefile` は #28 とバイト同一。ctypes から見える口は名前も型も同じ。"""
    for name in ("animal_shogi.py", "Makefile"):
        assert (IMPL_DIR / name).read_bytes() == (PREV_DIR / name).read_bytes(), name


def section(src: str, head: str, tail: str) -> tuple[str, str]:
    start = src.index(head)
    end = src.index(tail, start)
    return src[:start] + src[end:], src[start:end]


def test_only_the_seen_section_of_the_c_changed() -> None:
    """★`.c` で変わったのは発見済み集合の節だけ。ほかはコメントまでバイト同一。"""
    tail = "// ---- 前任リストの計数ソート (記録 #12)"
    old_rest, _ = section(
        text(PREV_DIR / "animal_shogi.c"), "// ---- 全探索の発見済み集合 (記録 #11)", tail
    )
    new_rest, new_sec = section(
        text(IMPL_DIR / "animal_shogi.c"), "// ---- 全探索の発見済み集合: ランクで引く", tail
    )
    assert new_rest == old_rest
    # ハッシュ表の名残が無い (作り直しも乗算ハッシュも使わない)
    code = "\n".join(code_only(new_sec))
    for word in ("seenGrow", "SEEN_SLOT", "INDEX_MULT", "SEEN_MIN_BITS"):
        assert word not in code, word


def test_only_the_seen_declarations_of_the_header_changed() -> None:
    """★`.h` で変わったのは発見済み集合の宣言の節だけ (と, ランクの口2つを足したこと)。"""
    tail = "// 盤面 b の後続を作り, すべて seen 表に登録し"
    old_rest, _ = section(
        text(PREV_DIR / "animal_shogi.h"), "// 全探索の「発見済み盤面」の集合", tail
    )
    new_rest, new_sec = section(
        text(IMPL_DIR / "animal_shogi.h"), "// 全探索の「発見済み盤面」の集合", tail
    )
    assert new_rest == old_rest
    assert "u_long rankBoard(u_long b);" in new_sec and "u_long rankRange(void);" in new_sec


def test_no_impl_env_needed() -> None:
    assert not (IMPL_DIR / "impl.env").exists()


# --------------------------------------------------------------------------
# ランク
# --------------------------------------------------------------------------


def test_the_range_is_counted_from_the_rules(lib: Any, naive: Naive) -> None:
    """★値域は 72 x 11,878,227 = 855,232,344。駒の数と盤の形だけから数えた値と一致する。

    ライオンの置き方 132 通りを鏡像どうしでまとめると 72 組 (60 対 + 中央の列どうしの 12)。
    ライオン以外は, きりん・ぞう・ひよこが各2枚で, 盤上の10マスに置くか持ち駒にする。
    """
    per_class = sum(
        math.comb(10, g + e + c)
        * math.factorial(g + e + c)
        // (math.factorial(g) * math.factorial(e) * math.factorial(c))
        * 2 ** (g + e + c)  # 持ち主
        * 2**c  # ひよこ・にわとり
        * (3 - g) * (3 - e) * (3 - c)  # 持ち駒を2人で分ける
        for g, e, c in itertools.product(range(3), repeat=3)
    )  # fmt: skip
    assert per_class == naive.per_class == 11_878_227
    assert naive.classes == 72
    assert lib.rankRange() == 72 * per_class == 855_232_344


def test_the_tables_agree_with_the_naive_rank(lib: Any, naive: Naive) -> None:
    """★C (前計算の表) のランクが素朴な実装と一致する。ライオンの組 132 通りすべてを含める。"""
    rng = random.Random(SEED)
    boards = [random_board(rng, lions) for lions in itertools.permutations(range(12), 2)]
    boards += [random_board(rng) for _ in range(3000)]
    boards = [normal_board(b) for b in boards]
    differ = [hex(b) for b in boards if lib.rankBoard(b) != naive.rank(b)]
    assert differ == [], differ[:5]


def test_the_rank_is_injective_on_normalized_boards(lib: Any) -> None:
    """★正規化した盤面どうしなら番号が重ならず, 値域の中に収まる。

    ライオンが2頭とも中央の列にない盤では, 鏡像どうしが同じ番号になる (鏡像をまとめたため)。
    2頭とも中央の列にある盤は反転せずに数えるので, 鏡像どうしは別の番号になるが,
    正規化した盤面には片方しか現れないので単射は崩れない。
    """
    rng = random.Random(SEED + 1)
    seen: dict[int, int] = {}
    for _ in range(200_000):
        b = normal_board(random_board(rng))
        r = lib.rankBoard(b)
        assert r < lib.rankRange()
        assert seen.setdefault(r, b) == b, (hex(b), hex(seen[r]))
        lions = [i for i in range(12) if (b >> (4 * i)) & 7 == LION1]
        if any(sq // 4 != 1 for sq in lions):
            assert lib.rankBoard(mirror_board(b)) == r


def test_invalid_boards_are_rejected(lib: Any) -> None:
    """★盤面として正しくない値は INDEX_EMPTY (rankBoard) と -4 (seenInsert) になる。"""
    rng = random.Random(SEED + 2)
    good = normal_board(random_board(rng))
    no_lion = good & ~(0xF << (4 * [(good >> (4 * i)) & 15 for i in range(12)].index(LION1)))
    extra_hand = good + (1 << 48) if (good >> 48) & 3 < 3 else good + (1 << 50)
    for bad in (INDEX_EMPTY, 0, no_lion, extra_hand, good | (1 << 60)):
        assert lib.rankBoard(bad) == INDEX_EMPTY, hex(bad)
        assert lib.seenInsert(bad) == -4, hex(bad)


def test_the_seen_table_never_rehashes(lib: Any) -> None:
    """★`seenRehashes` は常に 0 (forward.tsv の n_rehash の列は残す)。件数は立てたビットの数。"""
    rng = random.Random(SEED + 3)
    boards = {normal_board(random_board(rng)) for _ in range(5000)}
    for b in boards:
        assert lib.seenInsert(b) == 1
        assert lib.seenInsert(b) == 0
        assert lib.seenContains(b) == 1
    assert lib.seenCount() == len(boards)
    assert lib.seenRehashes() == 0


# --------------------------------------------------------------------------
# 走らせて impl/28 と突き合わせる (それぞれの Makefile の .so で)
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


def test_the_rounds_and_p0_agree_with_impl_28(runs: dict[str, dict[str, Any]]) -> None:
    """★ラウンドごとの件数と、P0 に渡る中身・P0 が詰めたバイト列が impl/28 と一致する。

    `n_rehash` だけは意味が変わる (ハッシュ表の作り直しの回数 → 常に 0) ので比べない。
    """
    a, b = runs[PREV], runs[IMPL]
    assert len(a["counts"]) > 10
    strip = [{k: v for k, v in r.items() if k != "n_rehash"} for r in a["counts"]]
    assert strip == [{k: v for k, v in r.items() if k != "n_rehash"} for r in b["counts"]]
    assert all(r.get("n_rehash", 0) == 0 for r in b["counts"])
    for key in ("queue", "uk_all", "catch_wins", "try_loses", "tbn", "packed", "n"):
        assert a[key] == b[key], key


def test_the_artifacts_are_byte_identical_to_impl_28(runs: dict[str, dict[str, Any]]) -> None:
    """★後退解析まで回した成果物が impl/28 とバイト一致する (初めて見た局面と順序が同じ)。"""
    da, db = runs[PREV]["work"] / "dat", runs[IMPL]["work"] / "dat"
    names = sorted(p.name for p in da.iterdir())
    assert names == sorted(p.name for p in db.iterdir()), "ファイルの顔ぶれが違う"
    assert len(names) > 3, f"成果物が少なすぎる (テストが空振り): {names}"
    differ = [n for n in names if (da / n).read_bytes() != (db / n).read_bytes()]
    assert differ == [], f"バイトが違うファイルがある: {differ[:5]}"
