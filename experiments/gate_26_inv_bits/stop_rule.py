#!/usr/bin/python3
"""本走に進むかを判定する (門番 #26。記録試行ではない)。

    python3 experiments/gate_26_inv_bits/stop_rule.py                       全12本で判定する
    python3 experiments/gate_26_inv_bits/stop_rule.py rounds <forward.tsv>   1本の件数の列を見る
    python3 experiments/gate_26_inv_bits/stop_rule.py huge   <ラベル>        1本の巨大ページを見る

測る前に決めた止める条件は3つ。どれかに掛かったら本走の前に止めて報告する。

  1. どれかの本の dat/ が #25 本走とバイト一致しない (md5 一覧の sha256 を
     results/25_huge_retreat/bytecompare.txt の値と照合)、件数の列が違う、
     またはオラクル174行で落ちた
  2. F1 か P2 の new − old の 95% 区間が 0 をまたがずに上 (遅くなった)
  3. どれかの本で /proc/vmstat の thp_fault_fallback の前後差が 0 でない、
     または巨大ページが表と配列の全部に付かない (HUGE_MIN の3つ。両腕とも)

件数の列は results/25_huge_retreat/forward.tsv と照合する。ほかに, 落ちた本 (開始したのに
完了していない本) が無いこと, 本数が各腕6本であることも見る。1 と 3 は
run_one.sh が毎本その場で見て, 掛かったら止まる (rounds と huge はそのための口)。
数字は gate_stats.py と同じ Welch の計算。比較は old 対 new の1本だけ。
"""

from __future__ import annotations

import csv
import pathlib
import re
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE.parent))

from gate_stats import collect, samples, welch  # noqa: E402

GATE = "gate_26_inv_bits"
LOGS = HERE / "logs"
REF = ROOT / "results" / "25_huge_retreat" / "forward.tsv"
# 巨大ページが付ききったときの量 (kB)。発見済み表は最終 4 GiB、索引の表は 8 GiB、
# 後退解析の4配列はそれぞれ 2 MiB に切り上げた和 (#25 の門番の12本と本走がどれもこの値以上)
HUGE_MIN = {
    ("forward_summary", "anonhuge_seen_kB"): 4_194_304,
    ("retreat_summary", "anonhuge_index_kB"): 8_388_608,
    ("retreat_summary", "anonhuge_loop_kB"): 4_972_544,
}
KEYS = ("n_in", "n_win", "n_lose", "n_uk", "n_new_post")
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
    print(f"{path.name}: {len(b)} ラウンド（#25 は {len(a)}）/ 件数の列 {verdict}")
    return ok


def fallback(label: str) -> int:
    rows = [ln.split("\t") for ln in (LOGS / f"{label}_vmstat.tsv").read_text().splitlines()]
    i = rows[0].index("thp_fault_fallback")
    return int(rows[2][i]) - int(rows[1][i])


def huge(label: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for (name, key), _ in HUGE_MIN.items():
        text = (LOGS / f"{label}_{name}.tsv").read_text(encoding="utf-8")
        values = [v for k, _, v in (ln.partition("\t") for ln in text.splitlines()) if k == key]
        if len(values) != 1:
            raise SystemExit(f"{label}_{name}.tsv に {key} が1行ない")
        out[key] = int(values[0])
    return out


def huge_ok(label: str) -> bool:
    got = huge(label)
    short = {k: v for (_, k), need in HUGE_MIN.items() if (v := got[k]) < need}
    print(f"{label}: " + " / ".join(f"{k} {v:,}" for k, v in got.items()))
    if short:
        print(f"**届かない: {short}**")
    return not short


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[1] == "rounds":
        return 0 if rounds_match(pathlib.Path(argv[2])) else 1
    if len(argv) == 3 and argv[1] == "huge":
        return 0 if huge_ok(argv[2]) else 1
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
    counts = {a: sum(1 for x in started.values() if x == a) for a in ("old", "new")}
    print("### 本数（落ちた本が無いか）")
    print()
    print(f"開始 {len(started)} 本 / 完了 {len(finished)} 本 / 腕ごと {counts}")
    if len(finished) != len(started) or any(c != RUNS_PER_ARM for c in counts.values()):
        print("**本数が合わない（落ちた本か、足りない本がある）**")
        stop = True
    print()
    print("### 1. 答え（オラクル174行と、#25 本走の dat/ とのバイト一致）")
    print()
    with (LOGS / "bytecompare.tsv").open(encoding="utf-8") as f:
        bc = {row["label"]: row for row in csv.DictReader(f, delimiter="\t")}
    bad = 0
    for label, arm in started.items():
        verify = [sys.executable, str(ROOT / "tools" / "verify_log.py")]
        oracle = subprocess.run(
            [*verify, str(LOGS / f"{label}_main.log")], capture_output=True, check=False
        ).returncode
        same = bc.get(label, {}).get("vs_record25") == "一致"
        if oracle != 0 or not same:
            bad += 1
            print(f"- {label} (`{arm}`): オラクル {'PASS' if oracle == 0 else '**FAIL**'} / "
                  f"バイト比較 {'一致' if same else '**不一致**'}")  # fmt: skip
    print(f"{len(started)} 本のうち、オラクル PASS かつバイト一致でないもの {bad} 本")
    stop = stop or bad > 0
    print()
    print("### 1. 件数の列（#25 本走の forward.tsv と照合）")
    print()
    for label in started:
        if not rounds_match(LOGS / f"{label}_forward.tsv"):
            stop = True
    print()
    print("### 2. F1 と P2 の new − old")
    print()
    for mode, name in (("forward", "F1 展開"), ("spans", "P2")):
        by_label, _order, rows = collect(GATE, mode)
        values = dict(rows)[name]
        d, _t, _df, p, lo, hi = welch(
            samples(values, by_label, "old"), samples(values, by_label, "new")
        )
        print(f"{name}: {d:+.2f} 秒（区間 {lo:+.2f} … {hi:+.2f}、p {p:.4g}）")
        if lo > 0:
            print(f"**{name} が遅くなった（止める）**")
            stop = True
    print()
    print("### 3. 巨大ページ（thp_fault_fallback の前後差と、表と配列に付いた量）")
    print()
    nonzero = {lb: v for lb in started if (v := fallback(lb)) != 0}
    print(f"thp_fault_fallback: {len(started)} 本のうち、0 でないもの {len(nonzero)} 本")
    if nonzero:
        print(nonzero)
    stop = stop or bool(nonzero)
    print()
    got = {lb: huge(lb) for lb in started}
    for (_, key), need in HUGE_MIN.items():
        vals = sorted({g[key] for g in got.values()})
        short = [lb for lb, g in got.items() if g[key] < need]
        seen = ", ".join(f"{v:,}" for v in vals)
        print(f"- {key}: {seen} kB（{need:,} に届かない本 {len(short)}）", short or "")
        stop = stop or bool(short)
    print()
    print("=> 止める: 本走に進まず報告する" if stop else "=> 止める条件に掛からない: 本走に進む")
    return 1 if stop else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
