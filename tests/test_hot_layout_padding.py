"""熱い関数の置き場所の固定 (#33 から) の詰め物の検査を、リンカースクリプトの中身ごとに1回だけ回す。

詰め物の検査は、熱くない関数をファイルの頭・熱い関数の間・末尾に足したり `.plt` を伸ばしたりして
`.so` を 17 回作り直し、熱い関数の番地が動かないことを見る。番地が動かないことを約束しているのは
リンカースクリプト `hot_layout.ld` で、#34 から先はその中身がバイト同一のまま版を重ねてきた。
#38 までは版ごとのテストに検査を写していて、同じリンカースクリプトを版の数だけ確かめていた
(1本 約 14 秒)。そこで、`hot_layout.ld` を持つ実装を中身の sha256 で組に分け、組ごとに一番新しい
実装で1回だけ回す。リンカースクリプトの違う版が足されれば、組が1つ増えて検査も1回増える。

版ごとに違いうるもの (その版の熱い関数が区画に入り、一覧の順で並ぶか) は、各版のテストの
`test_the_hot_functions_sit_in_their_own_section_before_text` が、その版をビルドして見ている
(1本 約 1 秒)。下の `test_every_grouped_impl_checks_its_own_section` が、その検査が版ごとに
あることを固定する。

#33 は除く。リンカースクリプトが #34 から先と違い (熱い関数の一覧が違う),
`tests/test_impl_33_hot_layout.py` の #32 との対比の検査が #33 の詰め物の検査を兼ねている。
"""

from __future__ import annotations

import hashlib
import pathlib
import re
import shutil

import pytest
from conftest import ROOT
from test_impl_33_hot_layout import make, symbols
from test_impl_34_unmove import PAD_SIZES, padded

LD = "hot_layout.ld"
# 詰め物の検査を自前で持つ実装 (上の説明)
OWN_CHECK = {"33_hot_layout"}


def hot_layout_groups() -> dict[str, list[str]]:
    """`hot_layout.ld` の中身の sha256 → それを持つ実装の名前 (番号順)。#33 は除く。"""
    groups: dict[str, list[str]] = {}
    for d in sorted((ROOT / "impl").iterdir()):
        ld = d / LD
        if d.is_dir() and ld.is_file() and d.name not in OWN_CHECK:
            groups.setdefault(hashlib.sha256(ld.read_bytes()).hexdigest(), []).append(d.name)
    return groups


GROUPS = hot_layout_groups()
# 組ごとの代表: 組の中で一番新しい実装
REPRESENTATIVES = sorted(members[-1] for members in GROUPS.values())


def hot_names(impl: str) -> tuple[str, ...]:
    """その実装のリンカースクリプトに並んだ熱い関数の名前 (順番どおり)。"""
    text = (ROOT / "impl" / impl / LD).read_text(encoding="utf-8")
    return tuple(re.findall(r"\*\(\.text\.(\w+)\)", text))


def addresses(so: pathlib.Path, names: tuple[str, ...]) -> tuple[int, ...]:
    table = symbols(so)
    return tuple(table[fn][0] for fn in names)


@pytest.fixture(scope="module")
def tools() -> None:
    for tool in ("gcc", "make", "nm"):
        if shutil.which(tool) is None:
            pytest.skip(f"{tool} が無い")


def test_there_is_at_least_one_group() -> None:
    """空振りしていないこと (impl/ の並びが変わって組が0になれば、この検査は何も守っていない)。"""
    assert GROUPS, "hot_layout.ld を持つ実装が見つからない"
    assert all(hot_names(impl) for impl in REPRESENTATIVES)


def test_every_grouped_impl_checks_its_own_section() -> None:
    """★組に入る実装はどれも、版ごとのテストで「熱い関数が区画に入り、一覧の順で並ぶ」を見ている。
    詰め物の検査を組ごとに1回にしたぶん、版ごとの違いはこの軽い検査が受け持つ。"""
    missing = []
    for members in GROUPS.values():
        for impl in members:
            test = ROOT / "tests" / f"test_impl_{impl}.py"
            body = test.read_text(encoding="utf-8") if test.is_file() else ""
            if "def test_the_hot_functions_sit_in_their_own_section_before_text(" not in body:
                missing.append(impl)
    assert not missing, f"区画の検査が版ごとのテストに無い: {missing}"


@pytest.mark.parametrize("impl", REPRESENTATIVES)
def test_padding_does_not_move_the_hot_functions(
    impl: str, tools: None, tmp_path: pathlib.Path
) -> None:
    """★詰め物の検査 (#33 から)。熱くない関数をファイルの頭・熱い関数の間・末尾に足しても、
    熱い関数の番地は1つも動かない。まだ使っていない libc の関数を呼んで `.plt` を伸ばしても、
    熱い関数のページの中の位置は動かない。同じ `hot_layout.ld` を持つ組の中で,
    一番新しい実装で回す。"""
    src = ROOT / "impl" / impl
    names = hot_names(impl)
    c = (src / "animal_shogi.c").read_text(encoding="utf-8")
    base = addresses(make(src, tmp_path / "base"), names)
    for where in ("top", "mid", "end"):
        for n in PAD_SIZES:
            got = addresses(make(src, tmp_path / f"{where}-{n}", padded(c, where, n)), names)
            assert got == base, (where, n)
    # `.plt` を伸ばすと, 区画の前の区画が 4 KiB の区切りをまたぐことがある (#34 ではまたいで,
    # 区画ごと1ページ後ろへずれる). リンカースクリプトが約束しているのは「ページの中の位置」なので,
    # 区画の先頭からの位置と, 先頭が 4 KiB の区切りであることを見る
    plt = (
        c
        + "#include <unistd.h>\n"
        + "__attribute__((used, noinline)) int layoutPadPid(void) { return (int)getpid(); }\n"
    )
    got = addresses(make(src, tmp_path / "plt", plt), names)
    assert got[0] % 4096 == 0
    assert [a - got[0] for a in got] == [a - base[0] for a in base]
