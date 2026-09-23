#!/usr/bin/python3
"""巨大ページが付いたことの証拠を、全本ぶん表にする (実験 lever_scan)。

    python3 experiments/lever_scan/hugecheck.py

頼んだことと付いたことは別。直接と間接の証拠を並べる:

  AnonHugePages   driver が表を捨てる直前に /proc/self/smaps_rollup から読んだ値
                  (全探索は seenFree の直前, 後退解析は indexFree の直前)
  索引の fault    後退解析の min_P1 − min_P0 (索引を作る段の minor fault).
                  4 KiB ページなら 8 GiB ÷ 4 KiB = 2,097,152 前後, 2 MiB なら 4,096 前後
  minor fault     全探索は time.txt の Minor page faults (発見済み表を倍々に作り直すので,
                  触る総量は最終の 4.29 GB の約2倍)
  thp_fault_*     /proc/vmstat の前後差. fallback は「頼んだが付かなかった」.
                  ⚠️ マシン全体の累積値の差なので, このプロセス以外のぶんも入りうる

base で AnonHugePages が 0 であることが対照になる (頼まなくても付いていたら,
huge はきれいなレバーにならない)。
"""

from __future__ import annotations

import pathlib
import re
import sys

LOGS = pathlib.Path(__file__).resolve().parent / "logs"
START = re.compile(r"^=== 開始 (?P<label>\S+) \((?P<arm>[^:]+):")


def labels(console: pathlib.Path) -> list[tuple[str, str]]:
    out = []
    for line in console.read_text(encoding="utf-8").splitlines():
        m = START.match(line)
        if m:
            out.append((m.group("label"), m.group("arm")))
    return out


def huge_kb(label: str) -> tuple[int, int]:
    line = (LOGS / f"{label}_huge.txt").read_text(encoding="utf-8").splitlines()[0]
    f = line.split("\t")
    return int(f[2]), int(f[4])


def vmstat_delta(label: str, key: str) -> int:
    rows = [ln.split("\t") for ln in (LOGS / f"{label}_vmstat.tsv").read_text().splitlines()]
    i = rows[0].index(key)
    return int(rows[2][i]) - int(rows[1][i])


def minor(label: str) -> int:
    for line in (LOGS / f"{label}_time.txt").read_text(encoding="utf-8").splitlines():
        if "Minor (reclaiming a frame) page faults" in line:
            return int(line.rsplit(":", 1)[1])
    raise SystemExit(f"{label}_time.txt に Minor page faults が無い")


def tsv(label: str) -> dict[str, str]:
    path = LOGS / f"{label}_retreat_summary.tsv"
    return dict(ln.split("\t", 1) for ln in path.read_text(encoding="utf-8").splitlines())


def main() -> int:
    for mode in ("forward", "retreat"):
        con = LOGS / f"console_{mode}.log"
        if not con.exists():
            continue
        print(f"### {mode}")
        print()
        if mode == "forward":
            print("| 本 | 腕 | Rss (MiB) | AnonHugePages (MiB) | minor fault "
                  "| thp_fault_alloc | thp_fault_fallback |")
            print("|---|---|---|---|---|---|---|")
        else:
            print("| 本 | 腕 | Rss (MiB) | AnonHugePages (MiB) | 索引の fault (P0→P1) "
                  "| thp_fault_alloc | thp_fault_fallback |")
            print("|---|---|---|---|---|---|---|")
        for label, arm in labels(con):
            if not (LOGS / f"{label}_huge.txt").exists():
                continue
            rss, ahp = huge_kb(label)
            if mode == "forward":
                mid = f"{minor(label):,}"
            else:
                t = tsv(label)
                mid = f"{int(t['min_P1']) - int(t['min_P0']):,}"
            print(
                f"| {label} | `{arm}` | {rss / 1024:,.0f} | {ahp / 1024:,.0f} | {mid} "
                f"| {vmstat_delta(label, 'thp_fault_alloc'):,} "
                f"| {vmstat_delta(label, 'thp_fault_fallback'):,} |"
            )
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
