#!/usr/bin/python3
"""回す前の静的な確かめ (門番 #39。記録試行ではない)。

    python3 static_check.py <old の animal_shogi.so> <new の animal_shogi.so> <lean の animal_shogi.so>

- new (impl/39_rank_lean) の .so が, 実験 rank_fast の腕 lean の .so とバイト一致するか
  (一致すれば rank_fast の一致の検査がそのまま当たる)
- 関数の記号 (nm の t / T) が old と同じか
- 置き場所のずれ (nm -S): 大きさか番地が変わった関数と, .bss の記号
- pext (BMI2) を持つ関数と, その数 (objdump -d)
"""

from __future__ import annotations

import hashlib
import pathlib
import re
import subprocess
import sys


def nm(so: pathlib.Path) -> dict[str, tuple[int, int, str]]:
    out = subprocess.run(["nm", "-S", str(so)], check=True, capture_output=True, text=True).stdout
    table = {}
    for line in out.splitlines():
        c = line.split()
        if len(c) == 4:
            table[c[3]] = (int(c[0], 16), int(c[1], 16), c[2])
    return table


def section(so: pathlib.Path, name: str) -> tuple[int, int]:
    out = subprocess.run(["readelf", "-SW", str(so)], check=True, capture_output=True, text=True)
    m = re.search(rf"\]\s+{re.escape(name)}\s+\S+\s+([0-9a-f]+)\s+[0-9a-f]+\s+([0-9a-f]+)", out.stdout)
    if not m:
        raise SystemExit(f"{so}: {name} が無い")
    return int(m.group(1), 16), int(m.group(2), 16)


def pext(so: pathlib.Path) -> dict[str, int]:
    out = subprocess.run(["objdump", "-d", str(so)], check=True, capture_output=True, text=True)
    count: dict[str, int] = {}
    fn = ""
    for line in out.stdout.splitlines():
        if m := re.match(r"^[0-9a-f]+ <(.+)>:$", line):
            fn = m.group(1)
        elif "\tpext " in line:
            count[fn] = count.get(fn, 0) + 1
    return count


def sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str]) -> int:
    old, new, lean = (pathlib.Path(p) for p in argv[1:4])
    ok = True
    print(f"old の .so sha256 {sha(old)}")
    print(f"new の .so sha256 {sha(new)}")
    same = new.read_bytes() == lean.read_bytes()
    print(f"lean の .so sha256 {sha(lean)} => new と{'バイト一致' if same else '**不一致**'}")
    ok &= same
    a, b = nm(old), nm(new)
    fa = sorted(k for k, v in a.items() if v[2] in "tT")
    fb = sorted(k for k, v in b.items() if v[2] in "tT")
    print(f"関数の記号: old {len(fa)} / new {len(fb)} => {'同じ' if fa == fb else '**違う**'}")
    ok &= fa == fb
    for name in (".text.hot_layout", ".text", ".bss"):
        (sa, za), (sb, zb) = section(old, name), section(new, name)
        print(f"{name}: old {sa:#x}（{za:#x} バイト） / new {sb:#x}（{zb:#x} バイト）")
    print()
    print("## 大きさか番地が変わった記号（関数と .bss。番地の順）")
    print()
    print("| 記号 | 種類 | old の番地（大きさ） | new の番地（大きさ） | 番地のずれ | 大きさの差 |")
    print("|---|---|---|---|---|---|")
    keys = sorted(set(a) | set(b), key=lambda k: (b.get(k) or a[k])[0])
    for k in keys:
        x, y = a.get(k), b.get(k)
        if x is not None and y is not None and x[:2] == y[:2]:
            continue
        if (x or y)[2] not in "tTbB":  # type: ignore[index]
            continue
        xs = f"{x[0]:#x}（{x[1]:#x}）" if x else "-"
        ys = f"{y[0]:#x}（{y[1]:#x}）" if y else "-"
        shift = f"{y[0] - x[0]:+d}" if x and y else "-"
        grow = f"{y[1] - x[1]:+d}" if x and y else "-"
        print(f"| `{k}` | {(y or x)[2]} | {xs} | {ys} | {shift} | {grow} |")  # type: ignore[index]
    print()
    print("## pext（BMI2）を持つ関数")
    print()
    po, pn = pext(old), pext(new)
    print(f"old: {sum(po.values())} 個 {po}")
    print(f"new: {sum(pn.values())} 個 {pn}")
    ok &= sum(po.values()) == 0 and sum(pn.values()) > 0
    print()
    print("静的な確かめ: " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
