#!/usr/bin/python3
"""標本の帰属を確かめる (実験 perf_branch_34。記録試行ではない)。probe/run_probe.sh が呼ぶ。

    python3 check_attr.py <attr のバイナリ> <事象名> <perf script -F ip,sym,symoff の出力>
    python3 check_attr.py <attr のバイナリ> lbr <perf script -F brstacksym の出力>

attr.c の分岐 probe_jz (test と融合した jz) について:
- PEBS: 標本の番地を「分岐そのもの」「融合した直前の比較」「次の命令 (probe_next)」
  「飛び先 (probe_target)」「ほか」に分けて数え, branch_of() が probe_jz に対応づけた割合を出す
- LBR: lbr_counts() で組み立てた probe_jz の「取られた」「取られなかった」と, ループの戻りの分岐の
  回数を並べる (どちらも1周に1回実行されるので, probe_jz の計 ≒ ループの戻りの計になるはず)
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys
from collections import Counter

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from branches import branch_of, disasm, lbr_counts, resolve


def syms(binary: str) -> dict[str, int]:
    out = subprocess.run(["nm", binary], check=True, capture_output=True, text=True).stdout
    return {p[2]: int(p[0], 16) for p in (ln.split() for ln in out.splitlines()) if len(p) == 3}


def main() -> int:
    binary, event, path = sys.argv[1:4]
    d = disasm(binary)
    s = syms(binary)
    jz, nxt, tgt = s["probe_jz"], s["probe_next"], s["probe_target"]
    lines = pathlib.Path(path).read_text(encoding="utf-8").splitlines()
    if event == "lbr":
        c = lbr_counts(d, lines)
        # ループの戻り: probe_target の後ろの最初の条件分岐
        back = next(a for a in d.addrs if a > tgt and d.is_cond(a))
        t, n, m = c.taken[jz], c.not_taken[jz], c.taken_misp[jz]
        lb = c.taken[back] + c.not_taken[back]
        print(f"LBR: 記録 {c.entries} / 組み立てた区間 {c.ranges}")
        print(f"probe_jz: 取られた {t} (うち外れ {m}) / 取られなかった {n} / 計 {t + n}")
        print(f"ループの戻り (0x{back:x}): 計 {lb}")
        print(f"probe_jz の計 ÷ ループの戻りの計: {(t + n) / lb:.3f}")
        return 0
    cnt: Counter[str] = Counter()
    mapped = 0
    total = 0
    for ln in lines:
        m = re.search(r"(\S+\+0x[0-9a-f]+)", ln)
        if not m:
            continue
        a = resolve(d, m.group(1))
        if a is None:
            cnt["ほか (関数の外)"] += 1
            total += 1
            continue
        total += 1
        if a == jz:
            cnt["分岐そのもの (probe_jz)"] += 1
        elif d.next_addr(a) == jz:
            cnt["融合した直前の比較"] += 1
        elif a == nxt:
            cnt["次の命令 (probe_next)"] += 1
        elif a == tgt:
            cnt["飛び先 (probe_target)"] += 1
        else:
            cnt[f"ほか ({d.insn.get(a, ('?', ''))[0]} @0x{a:x})"] += 1
        if branch_of(d, a) == jz:
            mapped += 1
    print(f"事象 {event}: 標本 {total}")
    for k, v in cnt.most_common():
        print(f"  {k}: {v} ({v / total:.1%})")
    print(f"branch_of() が probe_jz に対応づけた割合: {mapped / total:.1%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
