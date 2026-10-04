#!/usr/bin/python3
"""詰め物の検査と命令の比較 (門番 #33。時間を測らずに, 番地で置き場所の固定を確かめる)。

    python3 experiments/gate_33_hot_layout/layout.py > experiments/gate_33_hot_layout/logs/layout.txt

1. 区画: 両腕の .so の .plt 〜 .text の並び (readelf -SW)
2. 熱い関数の番地: 両腕の番地と, 64 で割った余り, 4096 で割った余り
3. 詰め物の検査: .c に熱くない関数 (N バイトの nop を持つだけ) を足して, 両腕の Makefile でビルドし,
   熱い関数のうち番地が動いたものを数える。足す場所はファイルの頭・nextBoardSeenNormal の前・末尾,
   大きさは 8・24・40・100・1000 バイト。まだ使っていない libc の関数 (getpid) を呼ぶ関数を足した版も
4. 命令の比較: 両腕の全関数で, 命令の並びと命令ごとのバイト数 (番地の数値を除く。関数の大きさの範囲)

同じことを tests/test_impl_33_hot_layout.py が固定している (ここはその表を残すための写し)。
.so はこのスクリプトが一時ディレクトリでビルドする (build_arm.sh と同じく, 実装のディレクトリの
ファイルを写して make)。-march=native の解決先は logs/march.txt。
"""

from __future__ import annotations

import hashlib
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
ARMS = {"old": ROOT / "impl" / "32_inline_rank", "new": ROOT / "impl" / "33_hot_layout"}
LD = ARMS["new"] / "hot_layout.ld"
HOT = tuple(re.findall(r"\*\(\.text\.(\w+)\)", LD.read_text(encoding="utf-8")))
PAD_AT = {
    "top": '#include "animal_shogi.h"\n',
    "mid": "int nextBoardSeenNormal(u_long b, u_long *out) {",
}
PAD_SIZES = (8, 24, 40, 100, 1000)
WHERE = {"top": "ファイルの頭", "mid": "nextBoardSeenNormal の前", "end": "末尾"}


def make(src: pathlib.Path, work: pathlib.Path, c: str | None = None) -> pathlib.Path:
    work.mkdir(parents=True)
    for path in src.iterdir():
        if path.is_file() and path.suffix != ".py":
            shutil.copy(path, work / path.name)
    if c is not None:
        (work / "animal_shogi.c").write_text(c, encoding="utf-8")
    subprocess.run(["make", "--quiet", "animal_shogi.so"], cwd=work, check=True)
    return work / "animal_shogi.so"


def symbols(so: pathlib.Path) -> dict[str, tuple[int, int]]:
    out = subprocess.run(["nm", "-S", str(so)], capture_output=True, text=True, check=True).stdout
    table: dict[str, tuple[int, int]] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 4 and parts[2] in "tT" and not parts[3].endswith(".localalias"):
            table[parts[3]] = (int(parts[0], 16), int(parts[1], 16))
    return table


def bodies(so: pathlib.Path) -> dict[str, list[tuple[int, str]]]:
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
    return {fn: insns for fn, insns in table.items() if fn in size}


def padded(c: str, where: str, n: int) -> str:
    body = f'__asm__ volatile(".skip {n}, 0x90");'
    pad = f"__attribute__((used, noinline)) void layoutPad(void) {{ {body} }}\n"
    if where == "end":
        return c + pad
    anchor = PAD_AT[where]
    return c.replace(anchor, anchor + pad) if where == "top" else c.replace(anchor, pad + anchor)


def with_new_import(c: str) -> str:
    return (
        c
        + "#include <unistd.h>\n"
        + "__attribute__((used, noinline)) int layoutPadPid(void) { return (int)getpid(); }\n"
    )


def main() -> int:
    c = (ARMS["old"] / "animal_shogi.c").read_text(encoding="utf-8")
    assert c == (ARMS["new"] / "animal_shogi.c").read_text(encoding="utf-8"), "2腕の .c が違う"
    with tempfile.TemporaryDirectory() as tmp:
        work = pathlib.Path(tmp)
        base = {arm: make(src, work / arm) for arm, src in ARMS.items()}
        for arm, so in base.items():
            sha = hashlib.sha256(so.read_bytes()).hexdigest()[:12]
            print(f"- `{arm}`: {ARMS[arm].relative_to(ROOT)} (so sha256 {sha})")
        print()
        print("## 1. 区画（.init 〜 .fini）")
        for arm, so in base.items():
            out = subprocess.run(
                ["readelf", "-SW", str(so)], capture_output=True, text=True, check=True
            ).stdout
            print()
            print(f"`{arm}`:")
            print()
            print("```")
            started = False
            for line in out.splitlines():
                started = started or " .init " in line
                if started:
                    print(line.strip())
                if " .fini " in line:
                    break
            print("```")
        print()
        print("## 2. 熱い関数の番地")
        print()
        print("| 関数 | 大きさ | `old` 番地 | mod 64 | mod 4096 | `new` 番地 | mod 64 | mod 4096 |")
        print("|---|---|---|---|---|---|---|---|")
        syms = {arm: symbols(so) for arm, so in base.items()}
        for fn in HOT:
            (a, s), (b, _s2) = syms["old"][fn], syms["new"][fn]
            print(f"| `{fn}` | {s} | 0x{a:x} | {a % 64} | {a % 4096} | 0x{b:x} | {b % 64} | {b % 4096} |")
        print()
        print(f"## 3. 詰め物の検査（熱い関数 {len(HOT)} 個のうち、番地が動いた数）")
        print()
        heads = [f"{n} B" for n in PAD_SIZES]
        print("| 足した場所 | 腕 | " + " | ".join(heads) + " |")
        print("|---|---|" + "---|" * len(heads))
        hot0 = {arm: tuple(syms[arm][fn][0] for fn in HOT) for arm in ARMS}
        k = 0
        for where in ("top", "mid", "end"):
            for arm, src in ARMS.items():
                cells = []
                for n in PAD_SIZES:
                    k += 1
                    so = make(src, work / f"p{k}", padded(c, where, n))
                    got = symbols(so)
                    moved = sum(got[fn][0] != a for fn, a in zip(HOT, hot0[arm], strict=True))
                    shift = got[HOT[-1]][0] - hot0[arm][-1]
                    cells.append(f"{moved}（末尾の関数 {shift:+d}）")
                print(f"| {WHERE[where]} | `{arm}` | " + " | ".join(cells) + " |")
        print()
        for arm, src in ARMS.items():
            k += 1
            got = symbols(make(src, work / f"p{k}", with_new_import(c)))
            moved = sum(got[fn][0] != a for fn, a in zip(HOT, hot0[arm], strict=True))
            print(f"- 新しい libc の関数 (getpid) を呼ぶ関数を末尾に足した版, `{arm}`: {moved} 個が動いた")
        print()
        print("## 4. 命令の比較（全関数。番地の数値を除き、命令ごとのバイト数まで）")
        print()
        old, new = bodies(base["old"]), bodies(base["new"])
        same = [fn for fn in old if fn in new and old[fn] == new[fn]]
        differ = sorted(set(old) ^ set(new)) + [fn for fn in old if fn in new and old[fn] != new[fn]]
        n_insn = sum(len(old[fn]) for fn in same)
        print(f"関数 {len(old)} 個のうち、同じ {len(same)} 個（{n_insn} 命令）、違う {len(differ)} 個 {differ}")
        print(f"熱い関数 {len(HOT)} 個: {'全部同じ' if all(fn in same for fn in HOT) else '**違うものがある**'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
