#!/usr/bin/python3
"""止める条件を判定する (実験 lever_scan_2。記録試行ではない)。

    python3 experiments/lever_scan_2/stop_rule.py                      全36本で判定する
    python3 experiments/lever_scan_2/stop_rule.py rounds <forward.tsv>  1本の件数の列を照合する

測る前に決めた止める条件は3つ。どれかに掛かったら, 結果の解釈に進まずに止めて報告する。

  1. どれかの本の dat/ の md5 一覧の sha256 が results/22_in_memory/bytecompare.txt の #22 の値と
     一致しない。またはオラクル174行で落ちた
  2. どれかの本の forward.tsv の件数の列 (n_in・n_win・n_lose・n_uk・n_new_post) が
     results/22_in_memory/forward.tsv と違う
  3. 途中で落ちた本がある (再開しない)
  4. どれかの本で /proc/vmstat の thp_fault_fallback の前後差が 0 でない
     (巨大ページが頼んだぶん付かない)。
     1回目の起動で, ノード0のメモリが断片化していて付かなかったので, 止めたあとに足した (README)

run_one.sh が毎本その場で 1〜3 を見て, 掛かったら止まる (rounds はそのための口)。
ここでは全36本がそろったあとに, もう一度まとめて見る。
"""

from __future__ import annotations

import csv
import pathlib
import re
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
LOGS = HERE / "logs"
REF = ROOT / "results" / "22_in_memory" / "forward.tsv"
KEYS = ("n_in", "n_win", "n_lose", "n_uk", "n_new_post")
ARMS = ("base", "pf2", "pf3", "hugeR", "reuse", "all")
RUNS_PER_ARM = 6
START = re.compile(r"^=== 開始 (?P<label>\S+) \((?P<arm>[^\s:)]+)[:\s)]")
DONE = re.compile(r"^=== 完了 (?P<label>\S+) ")


def table(path: pathlib.Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def rounds_match(path: pathlib.Path) -> bool:
    a, b = table(REF), table(path)
    ok = len(a) == len(b) and all(ra[k] == rb[k] for ra, rb in zip(a, b, strict=True) for k in KEYS)
    verdict = "一致" if ok else "**不一致**"
    print(f"{path.name}: {len(b)} ラウンド（#22 は {len(a)}）/ 件数の列 {verdict}")
    return ok


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[1] == "rounds":
        return 0 if rounds_match(pathlib.Path(argv[2])) else 1
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2

    stop = False
    started: dict[str, str] = {}
    finished: set[str] = set()
    for line in (LOGS / "console.log").read_text(encoding="utf-8").splitlines():
        if m := START.match(line):
            started[m.group("label")] = m.group("arm")
        elif m := DONE.match(line):
            finished.add(m.group("label"))
    counts = {a: sum(1 for x in started.values() if x == a) for a in ARMS}
    print("### 3. 本数（途中で落ちた本が無いか）")
    print()
    print(f"開始 {len(started)} 本 / 完了 {len(finished)} 本 / 腕ごと {counts}")
    if len(finished) != len(started) or any(counts[a] != RUNS_PER_ARM for a in ARMS):
        print("**本数が合わない（落ちた本か、足りない本がある）**")
        stop = True
    print()
    print("### 1. 答え（オラクル174行と、#22 本走の dat/ とのバイト一致）")
    print()
    with (LOGS / "bytecompare.tsv").open(encoding="utf-8") as f:
        bc = {row["label"]: row for row in csv.DictReader(f, delimiter="\t")}
    bad = 0
    for label, arm in started.items():
        verify = [sys.executable, str(ROOT / "tools" / "verify_log.py")]
        oracle = subprocess.run(
            [*verify, str(LOGS / f"{label}_main.log")], capture_output=True, check=False
        ).returncode
        same = bc.get(label, {}).get("vs_record22") == "一致"
        if oracle != 0 or not same:
            bad += 1
            print(f"- {label} (`{arm}`): オラクル {'PASS' if oracle == 0 else '**FAIL**'} / "
                  f"バイト比較 {'一致' if same else '**不一致**'}")  # fmt: skip
    print(f"{len(started)} 本のうち、オラクル PASS かつバイト一致でないもの {bad} 本")
    stop = stop or bad > 0
    print()
    print("### 2. 件数の列（#22 本走の forward.tsv と照合）")
    print()
    for label in started:
        if not rounds_match(LOGS / f"{label}_forward.tsv"):
            stop = True
    print()
    print("### 4. 巨大ページ（thp_fault_fallback の前後差）")
    print()
    fallback = {}
    for label in started:
        rows = [ln.split("\t") for ln in (LOGS / f"{label}_vmstat.tsv").read_text().splitlines()]
        i = rows[0].index("thp_fault_fallback")
        fallback[label] = int(rows[2][i]) - int(rows[1][i])
    nonzero = {lb: v for lb, v in fallback.items() if v != 0}
    print(f"{len(fallback)} 本のうち、0 でないもの {len(nonzero)} 本 {nonzero or ''}")
    stop = stop or bool(nonzero)
    print()
    print("=> 止める: 結果の解釈に進まず報告する" if stop else "=> 止める条件に掛からない")
    return 1 if stop else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
