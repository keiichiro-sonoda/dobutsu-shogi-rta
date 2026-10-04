#!/usr/bin/python3
"""2腕の .so で, 関数ごとの命令を数える (門番 #31。記録試行ではない)。

    python3 experiments/gate_31_rank_index/insns.py <old の .so> <new の .so>

`objdump -d` の命令の名前を関数ごとに数え, 次の2つの表を出す。

1. x86-64 のベースラインに無い命令 (BMI・BMI2・LZCNT・POPCNT・MOVBE と, `v` で始まる AVX 系) が,
   どの関数に何か所入ったか
2. 関数ごとの命令の総数 (`old` → `new`。変わったものだけ)

.so は門番の本が作ったもの (runs/exp_g31_<ラベル>/animal_shogi.so) を渡す。
⚠️ -march=native の中身は CPU で決まる。計測機で何に解決されたかは logs/march.txt (march.sh)。
"""

from __future__ import annotations

import collections
import hashlib
import pathlib
import re
import subprocess
import sys

HEAD = re.compile(r"^[0-9a-f]+ <(\S+)>:$")
INSN = re.compile(r"^\s+[0-9a-f]+:\t(\S+)")
# x86-64 のベースラインに無い命令 (BMI / BMI2 / LZCNT / POPCNT / MOVBE)。AVX 系は v で始まるもの
EXTRA = {
    "andn", "bextr", "blsi", "blsmsk", "blsr", "tzcnt",
    "bzhi", "mulx", "pdep", "pext", "rorx", "sarx", "shlx", "shrx",
    "lzcnt", "popcnt", "movbe",
}  # fmt: skip


def is_extra(m: str) -> bool:
    return m in EXTRA or m.startswith("v")


def mnemonics(so: pathlib.Path) -> dict[str, collections.Counter[str]]:
    out = subprocess.run(
        ["objdump", "-d", "--no-show-raw-insn", str(so)], capture_output=True, text=True, check=True
    ).stdout
    table: dict[str, collections.Counter[str]] = {}
    fn = ""
    for line in out.splitlines():
        if m := HEAD.match(line):
            fn = m.group(1)
            table.setdefault(fn, collections.Counter())
        elif fn and (m := INSN.match(line)):
            table[fn][m.group(1)] += 1
    return table


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    old_so, new_so = pathlib.Path(argv[1]), pathlib.Path(argv[2])
    for arm, so in (("old", old_so), ("new", new_so)):
        print(f"- `{arm}`: so sha256 {hashlib.sha256(so.read_bytes()).hexdigest()[:12]}")
    old, new = mnemonics(old_so), mnemonics(new_so)
    print()
    print("### ベースラインに無い命令（関数ごと）")
    print()
    print("| 関数 | `old` | `new` | `new` の内訳 |")
    print("|---|---|---|---|")
    total = {"old": 0, "new": 0}
    for fn in sorted(set(old) | set(new)):
        a = {m: n for m, n in old.get(fn, {}).items() if is_extra(m)}
        b = {m: n for m, n in new.get(fn, {}).items() if is_extra(m)}
        total["old"] += sum(a.values())
        total["new"] += sum(b.values())
        if a or b:
            parts = ", ".join(
                f"`{m}` {n}" for m, n in sorted(b.items(), key=lambda x: (-x[1], x[0]))
            )
            print(f"| `{fn}` | {sum(a.values())} | {sum(b.values())} | {parts} |")
    print(f"| 合計 | {total['old']} | {total['new']} | |")
    print()
    print("### 命令の総数（変わった関数だけ）")
    print()
    print("| 関数 | `old` | `new` | 差 |")
    print("|---|---|---|---|")
    for fn in sorted(set(old) | set(new)):
        a, b = sum(old.get(fn, {}).values()), sum(new.get(fn, {}).values())
        if a != b:
            print(f"| `{fn}` | {a} | {b} | {b - a:+d} |")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
