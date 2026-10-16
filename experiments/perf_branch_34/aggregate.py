#!/usr/bin/python3
"""perf script の出力を分岐ごとに数える (実験 perf_branch_34。記録試行ではない)。run_one.sh が呼ぶ。

    perf script -F ip,sym,symoff,dso -i <perf.data> \
        | python3 aggregate.py pebs <-g の .so> > <ラベル>_<段>_misp.tsv
    perf script -F brstacksym -i <perf.data> \
        | python3 aggregate.py lbr <-g の .so> > <ラベル>_<段>_lbr.tsv

pebs: 予測ミスの標本 (br_misp_retired.all_branches_pebs:pp) を, branch_of() で分岐の番地に
  寄せて数える.
  animal_shogi.so の外の標本は dso の名前 (パスを除く) ごとに, カーネルは「[kernel]」にまとめる
  (カーネルの番地は残さない). 分岐に寄せられなかった .so の中の標本は「unmapped」に数える
lbr: lbr_counts() で, 分岐ごとに取られた回数・取られて外れた回数・取られなかった回数を数える
どちらも, 分岐の番地に関数 (外側の実体と, インライン展開された一番内側) と C のソース行
(addr2line -i の一番内側. impl/34_unmove/animal_shogi.c の行) を添える.
出力はタブ区切り. 先頭の # の行に合計
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections import Counter

from branches import branch_of, disasm, lbr_counts, resolve

PEBS = re.compile(r"^\s*([0-9a-f]+)\s+(\S+)\s+\((.*)\)\s*$")


def lines_of(so: str, addrs: list[int]) -> dict[int, tuple[str, str, int]]:
    """番地 → (外側の関数, 一番内側の関数, 一番内側のソース行)。"""
    if not addrs:
        return {}
    out = subprocess.run(
        ["addr2line", "-a", "-f", "-i", "-e", so, *[hex(a) for a in addrs]],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    res: dict[int, tuple[str, str, int]] = {}
    i = 0
    while i < len(out):
        a = int(out[i], 16)
        i += 1
        pairs = []
        while i + 1 < len(out) and not out[i].startswith("0x"):
            pairs.append((out[i], out[i + 1]))
            i += 2
        m = re.search(r":(\d+)", pairs[0][1])
        res[a] = (pairs[-1][0], pairs[0][0], int(m.group(1)) if m else -1)
    return res


def pebs(so: str) -> int:
    d = disasm(so)
    hit: Counter[int] = Counter()
    other: Counter[str] = Counter()
    total = 0
    for line in sys.stdin:
        m = PEBS.match(line)
        if not m:
            continue
        total += 1
        symoff, dso = m.group(2), m.group(3)
        base = dso.rsplit("/", 1)[-1]
        if base == "animal_shogi.so":
            a = resolve(d, symoff)
            b = branch_of(d, a) if a is not None else None
            if b is None:
                other["unmapped"] += 1
            else:
                hit[b] += 1
        elif "kernel" in base or base.startswith("[") or symoff.startswith("0xffffffff"):
            other["[kernel]"] += 1
        else:
            other[base] += 1
    src = lines_of(so, list(hit))
    print(f"# samples\t{total}")
    print("where\taddr\tfunc\tinline\tline\tsamples")
    for a, n in sorted(hit.items(), key=lambda x: -x[1]):
        f, g, ln = src[a]
        print(f"animal_shogi.so\t0x{a:x}\t{f}\t{g}\t{ln}\t{n}")
    for k, n in other.most_common():
        print(f"{k}\t-\t-\t-\t-\t{n}")
    return 0


def lbr(so: str) -> int:
    d = disasm(so)
    c = lbr_counts(d, sys.stdin.read().splitlines())
    print(f"# entries\t{c.entries}")
    print(f"# ranges\t{c.ranges}")
    addrs = sorted(set(c.taken) | set(c.not_taken))
    src = lines_of(so, addrs)
    print("addr\tfunc\tinline\tline\ttaken\ttaken_misp\tnot_taken")
    for a in addrs:
        f, g, ln = src[a]
        print(f"0x{a:x}\t{f}\t{g}\t{ln}\t{c.taken[a]}\t{c.taken_misp[a]}\t{c.not_taken[a]}")
    return 0


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] not in ("pebs", "lbr"):
        raise SystemExit(__doc__)
    return pebs(sys.argv[2]) if sys.argv[1] == "pebs" else lbr(sys.argv[2])


if __name__ == "__main__":
    sys.exit(main())
