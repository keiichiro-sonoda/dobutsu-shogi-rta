#!/usr/bin/python3
"""回す前の静的な確かめ (門番 #40。記録試行ではない)。

    python3 static_check.py <old の animal_shogi.so> <new の animal_shogi.so> <ahead1 の animal_shogi.so>

- new (impl/40_dtm_ahead) の .so が, 実験 dtm_ahead の腕 ahead1 の .so とバイト一致するか
  (一致すれば dtm_ahead の一致の検査と, 完走 19 本の dat/ のバイト一致がそのまま当たる)
- 関数の記号 (nm の t / T) が old と同じか
- 置き場所のずれ (nm -S): 大きさか番地が変わった関数と, .bss の記号
- unmoveStep の機械語の命令・prefetchw・unmoveCandidates の呼び出しの数 (objdump -d)
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


def step_asm(so: pathlib.Path) -> dict[str, int]:
    """unmoveStep の機械語の (命令, prefetchw, unmoveCandidates の呼び出し) の数。"""
    out = subprocess.run(["objdump", "-d", "--no-show-raw-insn", str(so)], check=True, capture_output=True, text=True)
    lines, on = [], False
    for line in out.stdout.splitlines():
        if re.match(r"^[0-9a-f]+ <unmoveStep>:$", line):
            on = True
        elif on and not line.strip():
            break
        elif on:
            lines.append(line)
    return {
        "命令": len(lines),
        "prefetchw": sum("prefetchw" in ln for ln in lines),
        "unmoveCandidates の呼び出し": sum(bool(re.search(r"call.*<unmoveCandidates", ln)) for ln in lines),
    }


def sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str]) -> int:
    old, new, ahead1 = (pathlib.Path(p) for p in argv[1:4])
    ok = True
    print(f"old の .so sha256 {sha(old)}")
    print(f"new の .so sha256 {sha(new)}")
    same = new.read_bytes() == ahead1.read_bytes()
    print(f"ahead1 の .so sha256 {sha(ahead1)} => new と{'バイト一致' if same else '**不一致**'}")
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
    print("## unmoveStep の機械語")
    print()
    print(f"old: {step_asm(old)}")
    print(f"new: {step_asm(new)}")
    print()
    print("静的な確かめ: " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
