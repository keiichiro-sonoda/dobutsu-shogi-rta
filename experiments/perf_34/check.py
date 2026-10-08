#!/usr/bin/python3
"""1本ごとの検査 (実験 perf_34。記録試行ではない)。run_one.sh が呼ぶ。

    python3 check.py huge <ラベル>
        thp_fault_fallback の前後差が 0 で, 巨大ページが表と配列の全部に付いた
    python3 check.py rounds <ラベル>
        forward.tsv の件数の列が results/34_unmove/forward.tsv と同じ

巨大ページのしきい値は experiments/gate_34_unmove/stop_rule.py の new の腕と同じ値
(impl/34_unmove)。
"""

from __future__ import annotations

import csv
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
LOGS = HERE / "logs"
REF = ROOT / "results" / "34_unmove" / "forward.tsv"
# 発見済み表は 855,232,344 ビットを 2 MiB に切り上げた 51 枚。準備の配列と手数の配列は,
# どちらも 855,232,344 バイトを 2 MiB に切り上げた 408 枚 (835,584 kB) の和
HUGE = {
    ("forward_summary", "anonhuge_seen_kB"): 104_448,
    ("retreat_summary", "anonhuge_init_kB"): 1_671_168,
    ("retreat_summary", "anonhuge_loop_kB"): 1_671_168,
}
KEYS = ("n_in", "n_win", "n_lose", "n_uk", "n_new_post")


def value(label: str, name: str, key: str) -> int:
    text = (LOGS / f"{label}_{name}.tsv").read_text(encoding="utf-8")
    values = [v for k, _, v in (ln.partition("\t") for ln in text.splitlines()) if k == key]
    if len(values) != 1:
        raise SystemExit(f"{label}_{name}.tsv に {key} が1行ない")
    return int(values[0])


def huge(label: str) -> bool:
    rows = [ln.split("\t") for ln in (LOGS / f"{label}_vmstat.tsv").read_text().splitlines()]
    i = rows[0].index("thp_fault_fallback")
    fb = int(rows[2][i]) - int(rows[1][i])
    print(f"thp_fault_fallback の前後差: {fb}")
    ok = fb == 0
    for (name, key), need in HUGE.items():
        got = value(label, name, key)
        print(f"{key}: {got} kB (要 {need} kB 以上)")
        ok &= got >= need
    return ok


def table(path: pathlib.Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def rounds(label: str) -> bool:
    a, b = table(REF), table(LOGS / f"{label}_forward.tsv")
    ok = len(a) == len(b) and all(ra[k] == rb[k] for ra, rb in zip(a, b, strict=True) for k in KEYS)
    print(f"{len(b)} ラウンド（#34 は {len(a)}）/ 件数の列 {'一致' if ok else '**不一致**'}")
    return ok


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] not in ("huge", "rounds"):
        raise SystemExit(__doc__)
    ok = huge(sys.argv[2]) if sys.argv[1] == "huge" else rounds(sys.argv[2])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
