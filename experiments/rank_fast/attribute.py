#!/usr/bin/python3
"""perf record の標本を, イベントごとにインライン展開の鎖・ソースの行・読んだ表へ寄せて数える
(実験 rank_fast の段1。記録試行ではない)。

    perf script -F event,ip,sym,symoff,dso,addr -i <perf.data> \\
        | python3 attribute.py <-g なしの .so> <-g の .so> > <ラベル>_record_<区間>.tsv

experiments/perf_38/attribute.py を広げたもの。違いは2つ:
  1. 外側と一番内側の関数だけでなく, インライン展開の鎖を全部残す。rankFindKoma は rankOf の中の
     ほかに unmoveRaw とキャッチの先行判定でも展開されるので, 一番内側と外側の関数だけでは
     rankOf の中かを決められない
  2. ロードの標本 (perf record -d の番地) を, .so の中の静的な表 (nm の記号) に寄せる。
     .so を読み込んだ先頭は, 標本の命令の番地 − その命令のリンク時の番地 (perf_branch_34 の
     branches.py の resolve) で出す。.so の外 (巨大ページの配列・スタック・Python) は「-」
標本の番地は -g なしの .so の逆アセンブルでリンク時の番地に直し, -g の .so (.text の中身と
番地が同じ。build_arm.sh が確かめる) の addr2line -i で鎖と行に寄せる。animal_shogi.so の外の
標本は dso の名前 (パスを除く) ごとに, カーネルは「[kernel]」にまとめる (番地は残さない)。
出力はタブ区切り: event, where, chain, line, table, samples。chain は外側から内側へ「>」で
つないだ関数の名前, line は一番内側のソース行。先頭の # の行にイベントごとの標本の数。
"""

from __future__ import annotations

import bisect
import pathlib
import re
import subprocess
import sys
from collections import Counter

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "perf_branch_34"))
from branches import disasm, resolve  # noqa: E402

SAMPLE = re.compile(r"^\s*(\S+?):\s+([0-9a-f]+)\s+([0-9a-f]+)\s+(\S+)\s+\((.*)\)\s*$")
# cpu/<イベント>,period=<周期>/<修飾> の形のイベント名を <イベント>:<修飾> にそろえる
PMU = re.compile(r"^cpu/([^,/]+)(?:,[^/]*)?/(\w*)$")


def event_name(ev: str) -> str:
    m = PMU.match(ev)
    return f"{m.group(1)}:{m.group(2)}" if m else ev


def chains_of(so: str, addrs: list[int]) -> dict[int, tuple[str, int]]:
    """番地 → (外側から内側への関数の鎖, 一番内側のソース行)。"""
    if not addrs:
        return {}
    out = subprocess.run(
        ["addr2line", "-a", "-f", "-i", "-e", so, *[hex(a) for a in addrs]],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    res: dict[int, tuple[str, int]] = {}
    i = 0
    while i < len(out):
        a = int(out[i], 16)
        i += 1
        pairs = []
        while i + 1 < len(out) and not out[i].startswith("0x"):
            pairs.append((out[i], out[i + 1]))
            i += 2
        m = re.search(r":(\d+)", pairs[0][1])
        res[a] = (">".join(f for f, _ in reversed(pairs)), int(m.group(1)) if m else -1)
    return res


def data_symbols(so: str) -> tuple[list[int], list[tuple[int, str]]]:
    """.so の中のデータの記号 (bss と data). 先頭の番地の並びと (末尾, 名前)。"""
    out = subprocess.run(
        ["nm", "-S", "--defined-only", so], check=True, capture_output=True, text=True
    ).stdout.splitlines()
    syms = []
    for ln in out:
        p = ln.split()
        if len(p) == 4 and p[2] in "bBdDrR":
            lo = int(p[0], 16)
            syms.append((lo, lo + int(p[1], 16), p[3]))
    syms.sort()
    return [s[0] for s in syms], [(s[1], s[2]) for s in syms]


def table_of(starts: list[int], ends: list[tuple[int, str]], a: int) -> str:
    i = bisect.bisect_right(starts, a) - 1
    if i >= 0 and a < ends[i][0]:
        return ends[i][1]
    return "-"


def main(argv: list[str]) -> int:
    so, gso = argv[1], argv[2]
    d = disasm(so)
    starts, ends = data_symbols(so)
    hit: Counter[tuple[str, int, str]] = Counter()
    other: Counter[tuple[str, str]] = Counter()
    total: Counter[str] = Counter()
    for line in sys.stdin:
        m = SAMPLE.match(line)
        if not m:
            continue
        ev, daddr, ip, symoff, dso = (
            event_name(m.group(1)), int(m.group(2), 16), int(m.group(3), 16), m.group(4), m.group(5)
        )
        total[ev] += 1
        base = dso.rsplit("/", 1)[-1]
        if base == "animal_shogi.so":
            a = resolve(d, symoff)
            if a is None:
                other[(ev, "animal_shogi.so?")] += 1
                continue
            tbl = "-"
            if not ev.startswith("cycles") and daddr:
                tbl = table_of(starts, ends, daddr - (ip - a))
            hit[(ev, a, tbl)] += 1
        elif "kernel" in base or base.startswith("[") or symoff.startswith("0xffffffff"):
            other[(ev, "[kernel]")] += 1
        else:
            other[(ev, base)] += 1
    src = chains_of(gso, sorted({a for _, a, _ in hit}))
    rows: Counter[tuple[str, str, str, int, str]] = Counter()
    for (ev, a, tbl), n in hit.items():
        chain, ln = src[a]
        rows[(ev, "animal_shogi.so", chain, ln, tbl)] += n
    for ev, n in sorted(total.items()):
        print(f"# samples\t{ev}\t{n}")
    print("event\twhere\tchain\tline\ttable\tsamples")
    for (ev, where, chain, ln, tbl), n in sorted(rows.items(), key=lambda x: (x[0][0], -x[1])):
        print(f"{ev}\t{where}\t{chain}\t{ln}\t{tbl}\t{n}")
    for (ev, where), n in sorted(other.items(), key=lambda x: (x[0][0], -x[1])):
        print(f"{ev}\t{where}\t-\t-\t-\t{n}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
