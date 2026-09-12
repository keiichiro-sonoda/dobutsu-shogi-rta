#!/usr/bin/env python3
"""ベースライン実装のメインログを oracle/distribution.tsv と照合する。

使い方:
    python3 tools/verify_log.py <main_log>

終了コード 0 = 一致 / 1 = 不一致。
"""
from __future__ import annotations

import io
import pathlib
import re
import sys

ORACLE = pathlib.Path(__file__).resolve().parent.parent / "oracle" / "distribution.tsv"
LINE_RE = re.compile(r"\s*(\d+)手(勝ち|負け)盤面総数[^：]*：(\d+)")


def load_oracle() -> list[tuple[int, str, int]]:
    rows = []
    for line in ORACLE.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        d, r, c = line.split("\t")
        rows.append((int(d), r, int(c)))
    return rows


def parse_log(path: str) -> list[tuple[int, str, int]]:
    rows = []
    with io.open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = LINE_RE.match(line.strip())
            if m:
                rows.append(
                    (int(m.group(1)), "win" if m.group(2) == "勝ち" else "lose", int(m.group(3)))
                )
    return rows


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2

    expected = load_oracle()
    got = parse_log(sys.argv[1])

    # 同じログに再走が追記されている場合があるので先頭 len(expected) 行だけ見る
    got = got[: len(expected)]

    if len(got) != len(expected):
        print(f"FAIL: 行数が足りない (expected {len(expected)}, got {len(got)})")
        print("      → 完走していない可能性が高い")
        return 1

    bad = [(e, g) for e, g in zip(expected, got) if e != g]
    if bad:
        print(f"FAIL: {len(bad)} 行が不一致")
        for e, g in bad[:20]:
            print(f"  depth={e[0]:3d} {e[1]:4s}  expected={e[2]:<12d} got={g[2]}")
        if len(bad) > 20:
            print(f"  ... 他 {len(bad) - 20} 行")
        return 1

    print(f"PASS: {len(expected)} 行すべて一致")
    print(f"  手数別局面数の合計: {sum(r[2] for r in expected)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
