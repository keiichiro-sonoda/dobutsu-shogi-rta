#!/usr/bin/python3
"""logs/compare.tsv を集計する (記録試行ではない)。

    python3 experiments/sorted_compare_34/summary.py \
        > experiments/sorted_compare_34/logs/summary.txt
"""

from __future__ import annotations

import csv
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent


def main() -> int:
    with (HERE / "logs/compare.tsv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    for side in ("forward", "retreat", None):
        rs = [r for r in rows if side is None or r["side"] == side]
        label = {"forward": "全探索の側", "retreat": "後退解析の側", None: "合計"}[side]
        n33 = sum(int(r["n33"]) for r in rs)
        n34 = sum(int(r["n34"]) for r in rs)
        print(f"{label}: {len(rs)} ファイル / 件数 #33 {n33:,} / #34 {n34:,}")
        print(f"  件数の違うファイル: {sum(r['n33'] != r['n34'] for r in rs)}")
        print(f"  並べ替えた sha256 が一致: {sum(r['sorted_same'] == 'True' for r in rs)}")
        print(f"  元の並びでバイト一致: {sum(r['raw_same'] == 'True' for r in rs)}")
        dup33 = sum(int(r["dup33"]) for r in rs)
        dup34 = sum(int(r["dup34"]) for r in rs)
        print(f"  重複の数の合計: #33 {dup33} / #34 {dup34}")
    raw_retreat = [r["name"] for r in rows if r["side"] == "retreat" and r["raw_same"] == "True"]
    print(f"後退解析の側で元の並びのままバイト一致したファイル: {raw_retreat}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
