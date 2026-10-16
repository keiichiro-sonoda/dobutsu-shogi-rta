#!/usr/bin/python3
"""-g の .so で, 熱い関数の条件分岐がどのソース行から来ているかを洗い出す (実験 perf_branch_34)。

    python3 experiments/perf_branch_34/list_branches.py <-g の animal_shogi.so> \
        > experiments/perf_branch_34/logs/branch_lines.txt

回す前に数えるもの (本物のデータは使わない)。categories.tsv がこの行を全部覆っているかも見る。
出力: 関数 / 行 (addr2line -i の一番内側) / その行の条件分岐の数 / 束, 最後に覆えていない行
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys
from collections import defaultdict

from branches import disasm

HERE = pathlib.Path(__file__).resolve().parent
HOT = (
    "invBoard",
    "nextBoardInvNormalNC",
    "nextBoardSeenNormal",
    "expandRound",
    "unmoveCandidates",
    "unmoveStep",
)


def categories() -> dict[int, tuple[str, str]]:
    out = {}
    for ln in (HERE / "categories.tsv").read_text(encoding="utf-8").splitlines():
        if ln[:1].isdigit():
            line, bundle, what = ln.split("\t")
            out[int(line)] = (bundle, what)
    return out


def main() -> int:
    so = sys.argv[1]
    d = disasm(so)
    starts = sorted((a, n) for n, a in d.funcs.items())

    def fn_of(a: int) -> str:
        best = ""
        for s, n in starts:
            if s > a:
                break
            best = n
        return best

    addrs = [a for a in d.addrs if d.is_cond(a) and fn_of(a) in HOT]
    out = subprocess.run(
        ["addr2line", "-a", "-i", "-e", so, *[hex(a) for a in addrs]],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    inner: dict[int, int] = {}
    cur = None
    for ln in out.splitlines():
        if ln.startswith("0x"):
            cur = int(ln, 16)
        elif cur is not None and cur not in inner:
            m = re.search(r":(\d+)", ln)
            inner[cur] = int(m.group(1)) if m else -1
    by: dict[tuple[str, int], int] = defaultdict(int)
    for a in addrs:
        by[(fn_of(a), inner[a])] += 1
    cats = categories()
    print(f"# 熱い関数の条件分岐 {len(addrs)} 個, 行 {len({k[1] for k in by})} 個")
    for (f, line), n in sorted(by.items()):
        print(f"{f}\t{line}\t{n}\t{cats.get(line, ('対応表に無い行', ''))[0]}")
    missing = sorted({k[1] for k in by} - set(cats))
    extra = sorted(set(cats) - {k[1] for k in by})
    print(f"# categories.tsv に無い行: {missing} / categories.tsv にだけある行: {extra}")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
