#!/usr/bin/python3
"""本走に進むかを判定する (門番 #22)。

    python3 experiments/gate_22_in_memory/stop_rule.py                      全18本で判定する
    python3 experiments/gate_22_in_memory/stop_rule.py rounds <forward.tsv>  chunk の1本を照合する

測る前に決めた止める条件は3つ。どれかに掛かったら本走の前に止めて報告する。

  1. どれかの本の dat/ が記録 #21 本走の dat/ とバイト一致しない。オラクルで落ちた本も同じ扱い
     (P0 の詰め方・初期局面・F6 の順のどれかを取り違えている)
  2. chunk の forward.tsv の件数の列 (n_in・n_win・n_lose・n_uk・n_new_post) が
     results/21_hugepages/forward.tsv と1ラウンドでも違う (chunk が「#21 と同じラウンドの分け方」に
     なっていない)
  3. 採った腕が old より遅い (J ＝ forward_total ＋ P0 の区間が 0 をまたがずに上)

1 と 2 は run_one.sh が毎本その場で見て, 掛かったら止まる (rounds はそのための口)。
ここでは全18本がそろったあとに, もう一度まとめて見る。
"""

from __future__ import annotations

import csv
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from gate_stats import samples, welch  # noqa: E402
from judge import ARMS, J, collect, decide  # noqa: E402

LOGS = HERE / "logs"
REF = ROOT / "results" / "21_hugepages" / "forward.tsv"
KEYS = ("n_in", "n_win", "n_lose", "n_uk", "n_new_post")
# 止める条件には入れないが, 一致するはずなので情報として出す
INFO = ("n_seen", "n_rehash", "n_new_pre")
RUNS_PER_ARM = 6


def table(path: pathlib.Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def rounds_match(path: pathlib.Path) -> bool:
    a, b = table(REF), table(path)

    def same(keys: tuple[str, ...]) -> bool:
        return len(a) == len(b) and all(
            ra[k] == rb[k] for ra, rb in zip(a, b, strict=True) for k in keys
        )

    ok = same(KEYS)
    verdict = "一致" if ok else "**不一致**"
    print(f"{path.name}: {len(b)} ラウンド（#21 は {len(a)}）/ 件数の列 {verdict}")
    for k in INFO:
        print(f"  （情報）{k}: {'一致' if same((k,)) else '違う'}")
    return ok


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[1] == "rounds":
        return 0 if rounds_match(pathlib.Path(argv[2])) else 1
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2

    stop = False
    by_label, values = collect()
    print("### 1. 答え（オラクル174行と、#21 本走の dat/ とのバイト一致）")
    print()
    with (LOGS / "bytecompare.tsv").open(encoding="utf-8") as f:
        bc = {row["label"]: row for row in csv.DictReader(f, delimiter="\t")}
    counts = {a: sum(1 for x in by_label.values() if x == a) for a in ARMS}
    if any(counts[a] != RUNS_PER_ARM for a in ARMS):
        print(f"**本数が足りない**: {counts}")
        stop = True
    for label, arm in by_label.items():
        verify = [sys.executable, str(ROOT / "tools" / "verify_log.py")]
        oracle = subprocess.run(
            [*verify, str(LOGS / f"{label}_main.log")], capture_output=True, check=False
        ).returncode
        same = bc.get(label, {}).get("vs_record21") == "一致"
        if oracle != 0 or not same:
            stop = True
            print(f"- {label} (`{arm}`): オラクル {'PASS' if oracle == 0 else '**FAIL**'} / "
                  f"バイト比較 {'一致' if same else '**不一致**'}")  # fmt: skip
    print(f"{len(by_label)} 本" + ("" if stop else " すべて、オラクル PASS・バイト一致"))
    print()
    print("### 2. chunk のラウンドの分け方（件数の列を #21 本走と照合）")
    print()
    for label, arm in by_label.items():
        if arm == "chunk" and not rounds_match(LOGS / f"{label}_forward.tsv"):
            stop = True
    print()
    adopted, _w = decide(by_label, values[J])
    d, _t, _df, p, lo, hi = welch(
        samples(values[J], by_label, "old"), samples(values[J], by_label, adopted)
    )
    print(f"### 3. 採った腕（{adopted}）と old の {J}")
    print()
    print(f"{adopted} − old: {d:+.2f} 秒（区間 {lo:+.2f} … {hi:+.2f}、p {p:.4g}）")
    if lo > 0:
        print("**遅くなった（止める）**")
        stop = True
    print()
    print("=> 止める: 本走に進まず報告する" if stop else "=> 止める条件に掛からない: 本走に進む")
    return 1 if stop else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
