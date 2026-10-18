#!/usr/bin/python3
"""perf record の標本を, イベントごとに関数とソースの行へ寄せて数える (実験 perf_38。記録試行ではない)。

    perf script -F event,ip,sym,symoff,dso -i <perf.data> \\
        | python3 attribute.py <-g なしの .so> <-g の .so> > <ラベル>_record.tsv

標本の番地 (関数+位置) を -g なしの .so の逆アセンブルでリンク時の番地に直し (perf_branch_34 の branches.py の
resolve), -g の .so の addr2line -i で, 外側の関数・一番内側の (インライン展開された) 関数・一番内側のソース行に寄せる
(perf_branch_34 の aggregate.py の lines_of)。-g の .so は .text の中身と番地が -g なしと同じ (build_arm.sh が確かめる)。
分岐に寄せることはしない (cycles と LLC のロードミスの標本は, その命令そのものに付く)。
animal_shogi.so の外の標本は dso の名前 (パスを除く) ごとに, カーネルは「[kernel]」にまとめる (番地は残さない)。
出力はタブ区切り: event, where, func, inline, line, samples。先頭の # の行にイベントごとの標本の数。
"""

from __future__ import annotations

import pathlib
import re
import sys
from collections import Counter

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "perf_branch_34"))
from aggregate import lines_of  # noqa: E402
from branches import disasm, resolve  # noqa: E402

SAMPLE = re.compile(r"^\s*(\S+?):\s+([0-9a-f]+)\s+(\S+)\s+\((.*)\)\s*$")
# cpu/<イベント>,period=<周期>/<修飾> の形のイベント名を <イベント>:<修飾> にそろえる
PMU = re.compile(r"^cpu/([^,/]+)(?:,[^/]*)?/(\w*)$")


def event_name(ev: str) -> str:
    m = PMU.match(ev)
    return f"{m.group(1)}:{m.group(2)}" if m else ev


def main(argv: list[str]) -> int:
    so, gso = argv[1], argv[2]
    d = disasm(so)
    hit: Counter[tuple[str, int]] = Counter()
    other: Counter[tuple[str, str]] = Counter()
    total: Counter[str] = Counter()
    for line in sys.stdin:
        m = SAMPLE.match(line)
        if not m:
            continue
        ev, symoff, dso = event_name(m.group(1)), m.group(3), m.group(4)
        total[ev] += 1
        base = dso.rsplit("/", 1)[-1]
        if base == "animal_shogi.so":
            a = resolve(d, symoff)
            if a is None:
                other[(ev, "animal_shogi.so?")] += 1
            else:
                hit[(ev, a)] += 1
        elif "kernel" in base or base.startswith("[") or symoff.startswith("0xffffffff"):
            other[(ev, "[kernel]")] += 1
        else:
            other[(ev, base)] += 1
    src = lines_of(gso, sorted({a for _, a in hit}))
    rows: Counter[tuple[str, str, str, str, int]] = Counter()
    for (ev, a), n in hit.items():
        f, g, ln = src[a]
        rows[(ev, "animal_shogi.so", f, g, ln)] += n
    for ev, n in sorted(total.items()):
        print(f"# samples\t{ev}\t{n}")
    print("event\twhere\tfunc\tinline\tline\tsamples")
    for (ev, where, f, g, ln), n in sorted(rows.items(), key=lambda x: (x[0][0], -x[1])):
        print(f"{ev}\t{where}\t{f}\t{g}\t{ln}\t{n}")
    for (ev, where), n in sorted(other.items(), key=lambda x: (x[0][0], -x[1])):
        print(f"{ev}\t{where}\t-\t-\t-\t{n}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
