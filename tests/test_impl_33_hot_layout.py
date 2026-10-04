"""impl/33_hot_layout — 熱い関数の置き場所を固定する。

#32 の門番で、実行する命令が同じ P2 が、関数の番地がずれただけで +0.63 秒動いた。C を1か所
変えるたびに後ろの関数がずれると、小さいレバーの効果と置き場所のぶんを分けられない。

C は #32 とバイト同一。`Makefile` の `gcc` 行に `-ffunction-sections` (関数ごとに `.text.<名前>`
の区画を作る) と `-Wl,-T,hot_layout.ld` を足し、リンカースクリプトで熱い関数だけを `.text` の前の
専用の区画 `.text.hot_layout` に並べる。区画の先頭は 4 KiB、熱い関数の先頭は 64 バイトの区切り。

ここで固定するもの:

- 差分の範囲 (`.c` / `.h` / `.py` は #32 とバイト同一。`gcc` 行は2つ足しただけ)
- 一覧の熱い関数が全部、一覧の順で専用の区画にあり、区切りに揃っていること
- 命令の並びが #32 と同じこと (全関数。番地の数値を除き、命令ごとのバイト数まで)
- **詰め物の検査**: 熱くない場所に大きさの違う関数を足しても、熱い関数の番地が1つも動かないこと
  (#32 の作り方では動く。問題の再現も一緒に見る)
- 打ち切って後退解析まで回した成果物が #32 とバイト一致すること (それぞれの Makefile の .so で)

⚠️ 熱い関数を足したのに `hot_layout.ld` に書き漏らすと、その関数は `.text` に入って置き場所が
固定されない。テストは「一覧の関数が区画にあるか」しか見られないので、一覧は人が保つ。
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
from typing import Any

import conftest
import pytest
from conftest import ROOT, load_impl
from test_impl_22_in_memory import limited_run

IMPL = "33_hot_layout"
PREV = "32_inline_rank"
IMPL_DIR = ROOT / "impl" / IMPL
PREV_DIR = ROOT / "impl" / PREV
LD = "hot_layout.ld"
SECTION = ".text.hot_layout"
ADDED_FLAGS = ("-ffunction-sections", f"-Wl,-T,{LD}")

# 熱い関数 (F1・P1・P2・P4・174段ループで実行される C の関数)。並びは #32 の .so と同じ。
# normalBoard は呼び出し元に全部インライン展開されていて、外の実体は実行されない (perf で標本 0)
HOT = (
    "invBoard",
    "nextBoardInvNormal",
    "indexBuild",
    "nextBoardIndexNormal",
    "nextBoardSeenNormal",
    "predCount",
    "predScatter",
    "expandRound",
    "retreatStep",
    "buildSuccRange",
    "gatherPacked",
    "gatherDraws",
)

# 詰め物を入れる場所: ファイルの頭 (#32 では熱い関数が全部動く)、熱い関数の間、末尾
PAD_AT = {
    "top": '#include "animal_shogi.h"\n',
    "mid": "int nextBoardSeenNormal(u_long b, u_long *out) {",
}
PAD_SIZES = (8, 24, 40, 100, 1000)


def text(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def gcc_line(impl_dir: pathlib.Path) -> list[str]:
    lines = [ln.strip() for ln in text(impl_dir / "Makefile").splitlines() if "gcc" in ln]
    assert len(lines) == 1, lines
    return lines[0].split()


def make(src: pathlib.Path, work: pathlib.Path, c: str | None = None) -> pathlib.Path:
    """その実装の `Makefile` で `.so` を作る。`c` を渡すと `.c` をそれに差し替える。"""
    work.mkdir(parents=True, exist_ok=True)
    for path in src.iterdir():
        if path.is_file() and path.suffix != ".py":
            shutil.copy(path, work / path.name)
    if c is not None:
        (work / "animal_shogi.c").write_text(c, encoding="utf-8")
    done = subprocess.run(
        ["make", "animal_shogi.so"], cwd=work, capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, f"make が失敗した:\n{done.stdout}\n{done.stderr}"
    assert "warning" not in done.stderr.lower(), f"警告が出ている:\n{done.stderr}"
    return work / "animal_shogi.so"


def symbols(so: pathlib.Path) -> dict[str, tuple[int, int]]:
    """関数の (番地, 大きさ)。`nm -S` で大きさのある関数だけ。"""
    out = subprocess.run(["nm", "-S", str(so)], capture_output=True, text=True, check=True).stdout
    table: dict[str, tuple[int, int]] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 4 and parts[2] in "tT":
            table[parts[3]] = (int(parts[0], 16), int(parts[1], 16))
    return table


def sections(so: pathlib.Path) -> dict[str, tuple[int, int, int]]:
    """区画の (番地, 大きさ, 揃え)。`readelf -SW`。"""
    out = subprocess.run(
        ["readelf", "-SW", str(so)], capture_output=True, text=True, check=True
    ).stdout
    table: dict[str, tuple[int, int, int]] = {}
    for m in re.finditer(
        r"\]\s+(\S+)\s+\S+\s+([0-9a-f]{16})\s+[0-9a-f]+\s+([0-9a-f]+)\s.*\s(\d+)$", out, re.M
    ):
        table[m.group(1)] = (int(m.group(2), 16), int(m.group(3), 16), int(m.group(4)))
    return table


def bodies(so: pathlib.Path) -> dict[str, list[tuple[int, str]]]:
    """関数ごとの命令の並び。(命令のバイト数, 命令) を、関数の大きさの範囲だけ。

    番地の数値は落とす (分岐の行き先は `<関数+オフセット>` の記号で残し、`%rip` からの相対の
    数値とコメントの番地は消す)。関数の後ろの詰め物 (次の関数の区切りまでの `nop`) は
    関数の大きさの外なので入らない。
    """
    out = subprocess.run(
        ["objdump", "-d", "-w", str(so)], capture_output=True, text=True, check=True
    ).stdout
    size = {fn: s for fn, (_a, s) in symbols(so).items()}
    table: dict[str, list[tuple[int, str]]] = {}
    used: dict[str, int] = {}
    fn = ""
    for line in out.splitlines():
        if m := re.match(r"^[0-9a-f]+ <(\S+)>:$", line):
            fn = m.group(1)
            table[fn], used[fn] = [], 0
        elif fn in size and (m := re.match(r"^\s+[0-9a-f]+:\t([0-9a-f ]+?)\s*\t(.*)$", line)):
            if used[fn] >= size[fn]:
                continue
            n = len(m.group(1).split())
            insn = re.sub(r"#.*$", "", m.group(2)).strip()
            insn = re.sub(r"^(\S+\s+)[0-9a-f]+ (<[^>]+>)", r"\1\2", insn)
            insn = re.sub(r"-?0x[0-9a-f]+\(%rip\)", "REL(%rip)", insn)
            table[fn].append((n, insn))
            used[fn] += n
    for fn, n in used.items():
        if fn in size:
            assert n == size[fn], f"{fn}: 命令を足すと {n} バイト、nm では {size[fn]} バイト"
    return {fn: insns for fn, insns in table.items() if fn in size}


def padded(c: str, where: str, n: int) -> str:
    """熱くない関数 (`n` バイトの `nop` を持つだけ) を1つ足した `.c`。"""
    body = f'__asm__ volatile(".skip {n}, 0x90");'
    pad = f"__attribute__((used, noinline)) void layoutPad(void) {{ {body} }}\n"
    if where == "end":
        return c + pad
    anchor = PAD_AT[where]
    assert c.count(anchor) == 1, anchor
    if where == "top":
        return c.replace(anchor, anchor + pad)
    return c.replace(anchor, pad + anchor)


def with_new_import(c: str) -> str:
    """熱くない関数から、まだ使っていない libc の関数を呼ぶ `.c` (`.plt` が伸びる)。"""
    return (
        c
        + "#include <unistd.h>\n"
        + "__attribute__((used, noinline)) int layoutPadPid(void) { return (int)getpid(); }\n"
    )


def hot_addresses(so: pathlib.Path) -> tuple[int, ...]:
    table = symbols(so)
    return tuple(table[fn][0] for fn in HOT)


@pytest.fixture(scope="module")
def tools() -> None:
    for tool in ("gcc", "make", "nm", "objdump", "readelf"):
        if shutil.which(tool) is None:
            pytest.skip(f"{tool} が無い")


@pytest.fixture(scope="module")
def built(tools: None, tmp_path_factory: pytest.TempPathFactory) -> dict[str, pathlib.Path]:
    root = tmp_path_factory.mktemp("make")
    return {impl: make(ROOT / "impl" / impl, root / impl) for impl in (PREV, IMPL)}


# --------------------------------------------------------------------------
# 差分の範囲
# --------------------------------------------------------------------------


def test_the_sources_are_byte_identical_to_impl_32() -> None:
    """★`.c` / `.h` / `.py` は #32 とバイト同一。

    命令が変わりうるのは `gcc` 行とリンカースクリプトだけ。
    """
    for name in ("animal_shogi.c", "animal_shogi.h", "animal_shogi.py"):
        assert (IMPL_DIR / name).read_bytes() == (PREV_DIR / name).read_bytes(), name


def test_the_gcc_line_only_adds_function_sections_and_the_linker_script() -> None:
    """★`gcc` 行は #32 の行に2つ足しただけ。最適化の指定は変えていない。"""
    old, new = gcc_line(PREV_DIR), gcc_line(IMPL_DIR)
    assert [w for w in new if w not in ADDED_FLAGS] == old
    assert all(new.count(flag) == 1 for flag in ADDED_FLAGS)
    assert LD in text(IMPL_DIR / "Makefile").splitlines()[0], "依存に hot_layout.ld が無い"


def test_the_files_are_the_four_of_impl_32_and_the_linker_script() -> None:
    names = sorted(p.name for p in IMPL_DIR.iterdir() if p.name != "__pycache__")
    assert names == sorted(["Makefile", "animal_shogi.c", "animal_shogi.h", "animal_shogi.py", LD])


def test_the_linker_script_lists_the_hot_functions_in_order() -> None:
    """★リンカースクリプトの一覧とこのテストの `HOT` が同じ (どちらかだけ直すと落ちる)。"""
    listed = re.findall(r"\*\(\.text\.(\w+)\)", text(IMPL_DIR / LD))
    assert tuple(listed) == HOT


def test_every_hot_function_is_defined_in_the_c() -> None:
    """一覧の名前が C にある (名前を間違えると、区画が空振りしてもリンクは通る)。"""
    c = text(IMPL_DIR / "animal_shogi.c")
    for fn in HOT:
        assert re.search(rf"^\S[^;]*\b{fn}\(", c, re.M), fn


# --------------------------------------------------------------------------
# 置き場所 (それぞれの Makefile でビルドして見る)
# --------------------------------------------------------------------------


def test_the_hot_functions_sit_in_their_own_section_before_text(
    built: dict[str, pathlib.Path],
) -> None:
    """★熱い関数は全部 `.text.hot_layout` の中に一覧の順で並び、区画は `.text` の前にある。

    区画の先頭は 4 KiB、熱い関数の先頭は 64 バイトの区切り。
    """
    secs, syms = sections(built[IMPL]), symbols(built[IMPL])
    start, size, align = secs[SECTION]
    assert align == 4096 and start % 4096 == 0
    assert start + size <= secs[".text"][0], "区画が .text の後ろにある"
    addrs = [syms[fn][0] for fn in HOT]
    assert addrs == sorted(addrs), "並びが一覧の順でない"
    assert addrs[0] == start
    for fn in HOT:
        a, s = syms[fn]
        assert start <= a and a + s <= start + size, f"{fn} が区画の外にある"
        assert a % 64 == 0, f"{fn} の先頭が 64 バイトの区切りでない: {a:#x}"
    # `.localalias` は同じ番地の別名 (-fno-semantic-interposition が作る)
    inside = {
        fn.removesuffix(".localalias") for fn, (a, _s) in syms.items() if start <= a < start + size
    }
    assert sorted(inside) == sorted(HOT), "区画に一覧の外の関数がある"


def test_the_instructions_are_the_same_as_impl_32(built: dict[str, pathlib.Path]) -> None:
    """★全関数で、命令の並びと命令ごとのバイト数が #32 と同じ (番地の数値を除く)。"""
    old, new = bodies(built[PREV]), bodies(built[IMPL])
    assert sorted(old) == sorted(new)
    assert set(HOT) <= set(new)
    differ = [fn for fn in old if old[fn] != new[fn]]
    assert differ == [], f"命令が違う関数: {differ}"


def test_padding_moves_the_hot_functions_in_impl_32_but_not_in_impl_33(
    tools: None, tmp_path: pathlib.Path
) -> None:
    """★詰め物の検査。熱くない関数を足すと、#32 の作り方では熱い関数が動き、#33 では1つも動かない。

    足す場所はファイルの頭・熱い関数の間 (`nextBoardSeenNormal` の前)・末尾、大きさは5通り。
    #32 では、頭なら全部、間なら後ろの関数が動く (末尾なら #32 でも動かない)。
    まだ使っていない libc の関数を呼ぶと `.plt` が伸びて、#32 では全部動く。
    """
    c = text(IMPL_DIR / "animal_shogi.c")
    base = {
        impl: hot_addresses(make(ROOT / "impl" / impl, tmp_path / impl)) for impl in (PREV, IMPL)
    }
    later = HOT.index("nextBoardSeenNormal")
    cases = [(w, n) for w in ("top", "mid", "end") for n in PAD_SIZES]
    for where, n in cases:
        for impl in (PREV, IMPL):
            got = hot_addresses(
                make(ROOT / "impl" / impl, tmp_path / f"{impl}-{where}-{n}", padded(c, where, n))
            )
            moved = [fn for fn, a, b in zip(HOT, base[impl], got, strict=True) if a != b]
            if impl == IMPL or where == "end":
                assert moved == [], (impl, where, n, moved)
            elif where == "top":
                assert moved == list(HOT), (impl, where, n, moved)
            else:
                after = [
                    fn for fn, a in zip(HOT, base[impl], strict=True) if a >= base[impl][later]
                ]
                assert moved == after, (impl, where, n, moved)
    for impl in (PREV, IMPL):
        got = hot_addresses(
            make(ROOT / "impl" / impl, tmp_path / f"{impl}-plt", with_new_import(c))
        )
        moved = [fn for fn, a, b in zip(HOT, base[impl], got, strict=True) if a != b]
        assert moved == ([] if impl == IMPL else list(HOT)), (impl, "plt", moved)


# --------------------------------------------------------------------------
# 走らせて impl/32 と突き合わせる (それぞれの Makefile の .so で)
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def runs(
    built: dict[str, pathlib.Path], tmp_path_factory: pytest.TempPathFactory
) -> dict[str, dict[str, Any]]:
    """⚠️ `load_impl()` は自前の C を持つ実装に `conftest.impl_library()` (-O0 の自前の gcc 行) の
    `.so` を差し込むので、ここだけそれを Makefile で作った `.so` に差し替える。"""
    out: dict[str, dict[str, Any]] = {}
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(conftest, "impl_library", lambda impl: built[impl])
        for impl in (PREV, IMPL):
            work = tmp_path_factory.mktemp(impl)
            module = load_impl(impl, work, built[impl])
            assert (work / "animal_shogi.so").read_bytes() == built[impl].read_bytes()
            out[impl] = limited_run(module, work)
    return out


def test_the_rounds_and_p0_agree_with_impl_32(runs: dict[str, dict[str, Any]]) -> None:
    """★ラウンドごとの件数と、P0 に渡る中身・P0 が詰めたバイト列が impl/32 と一致する。"""
    a, b = runs[PREV], runs[IMPL]
    assert len(a["counts"]) > 10
    for key in ("counts", "queue", "uk_all", "catch_wins", "try_loses", "tbn", "packed", "n"):
        assert a[key] == b[key], key


def test_the_artifacts_are_byte_identical_to_impl_32(runs: dict[str, dict[str, Any]]) -> None:
    """★後退解析まで回した成果物が impl/32 とバイト一致する。"""
    da, db = runs[PREV]["work"] / "dat", runs[IMPL]["work"] / "dat"
    names = sorted(p.name for p in da.iterdir())
    assert names == sorted(p.name for p in db.iterdir()), "ファイルの顔ぶれが違う"
    assert len(names) > 3, f"成果物が少なすぎる (テストが空振り): {names}"
    differ = [n for n in names if (da / n).read_bytes() != (db / n).read_bytes()]
    assert differ == [], f"バイトが違うファイルがある: {differ[:5]}"
