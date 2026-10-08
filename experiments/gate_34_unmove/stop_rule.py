#!/usr/bin/python3
"""本走に進むかを判定する (門番 #34。記録試行ではない)。

    python3 experiments/gate_34_unmove/stop_rule.py                   全12本で判定する
    python3 experiments/gate_34_unmove/stop_rule.py rounds <tsv>       1本の件数の列
    python3 experiments/gate_34_unmove/stop_rule.py huge <ラベル> <腕>  1本の巨大ページ

判定の量は**完走の秒** (/usr/bin/time の Elapsed。空の dat/ から Python の起動を含めて終わるまで)。
後退解析の段の顔ぶれが変わるので, 段ごとではなく合計で比べる。

測る前に決めた止める条件。どれかに掛かったら本走の前に止めて報告する。

  1. どれかの本の答えが外れた: オラクル174行, 答えの検査 (check_answer.py。old は #33 本走との
     バイト比較, new は全探索の側のバイト比較・ファイルの名前と件数・指紋), 件数の列
     (results/33_hot_layout/forward.tsv と照合)
  2. 完走の new − old の 95% 区間の下端が 0 より上 (遅くなった)
  3. どれかの本で thp_fault_fallback の前後差が 0 でない, または巨大ページが表と配列の全部に付かない
  (巨大ページに使える空きが下限に満たないときは, run_one.sh が走らせずに止める)

区間の上端が 0 より下 (速くなった), または区間が 0 をまたぐなら本走して記録にする。
ほかに, 落ちた本が無いこと, 本数が各腕6本であることも見る。1 と 3 は run_one.sh が毎本その場で見て,
掛かったら止まる (rounds と huge はそのための口)。数字は gate_stats.py と同じ Welch の計算。
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

from gate_stats import welch  # noqa: E402

LOGS = HERE / "logs"
REF = ROOT / "results" / "33_hot_layout" / "forward.tsv"
# 巨大ページが付ききったときの量 (kB)。発見済み表は 855,232,344 ビットを 2 MiB に切り上げた
# 51 枚 (両腕)。old (#33) は索引 8 GiB と後退解析の4配列 (gate_33_hot_layout と同じ値)。
# new (#34) は準備の配列と手数の配列で, どちらも 855,232,344 バイトを 2 MiB に切り上げた
# 408 枚 (835,584 kB) の和
HUGE = {
    "old": {
        ("forward_summary", "anonhuge_seen_kB"): 104_448,
        ("retreat_summary", "anonhuge_index_kB"): 8_388_608,
        ("retreat_summary", "anonhuge_loop_kB"): 4_972_544,
    },
    "new": {
        ("forward_summary", "anonhuge_seen_kB"): 104_448,
        ("retreat_summary", "anonhuge_init_kB"): 1_671_168,
        ("retreat_summary", "anonhuge_loop_kB"): 1_671_168,
    },
}
KEYS = ("n_in", "n_win", "n_lose", "n_uk", "n_new_post")
RUNS_PER_ARM = 6
START = re.compile(r"^=== 開始 (?P<label>\S+) \((?P<arm>[^\s:)]+)[:\s)]")
DONE = re.compile(r"^=== 完了 (?P<label>\S+) ")
ELAPSED = re.compile(r"Elapsed \(wall clock\) time \(h:mm:ss or m:ss\): (?:(\d+):)?(\d+):([\d.]+)")


def table(path: pathlib.Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def rounds_match(path: pathlib.Path) -> bool:
    a, b = table(REF), table(path)
    ok = len(a) == len(b) and all(ra[k] == rb[k] for ra, rb in zip(a, b, strict=True) for k in KEYS)
    verdict = "一致" if ok else "**不一致**"
    print(f"{path.name}: {len(b)} ラウンド（#33 は {len(a)}）/ 件数の列 {verdict}")
    return ok


def fallback(label: str) -> int:
    rows = [ln.split("\t") for ln in (LOGS / f"{label}_vmstat.tsv").read_text().splitlines()]
    i = rows[0].index("thp_fault_fallback")
    return int(rows[2][i]) - int(rows[1][i])


def huge(label: str, arm: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for name, key in HUGE[arm]:
        text = (LOGS / f"{label}_{name}.tsv").read_text(encoding="utf-8")
        values = [v for k, _, v in (ln.partition("\t") for ln in text.splitlines()) if k == key]
        if len(values) != 1:
            raise SystemExit(f"{label}_{name}.tsv に {key} が1行ない")
        out[key] = int(values[0])
    return out


def short_of(label: str, arm: str) -> dict[str, int]:
    got = huge(label, arm)
    return {k: v for (_, k), need in HUGE[arm].items() if (v := got[k]) < need}


def elapsed(label: str) -> float:
    m = ELAPSED.search((LOGS / f"{label}_time.txt").read_text(encoding="utf-8"))
    if not m:
        raise SystemExit(f"{label}_time.txt に Elapsed が無い")
    return int(m.group(1) or 0) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[1] == "rounds":
        return 0 if rounds_match(pathlib.Path(argv[2])) else 1
    if len(argv) == 4 and argv[1] == "huge":
        got, short = huge(argv[2], argv[3]), short_of(argv[2], argv[3])
        print(f"{argv[2]} ({argv[3]}): " + " / ".join(f"{k} {v:,}" for k, v in got.items()))
        if short:
            print(f"**届かない: {short}**")
        return 1 if short else 0
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
    print("### 1. 答え（オラクル174行と、答えの検査）")
    print()
    bad = 0
    for label, arm in started.items():
        verify = [sys.executable, str(ROOT / "tools" / "verify_log.py")]
        oracle = subprocess.run(
            [*verify, str(LOGS / f"{label}_main.log")], capture_output=True, check=False
        ).returncode
        answer = (LOGS / f"{label}_answer.txt").read_text(encoding="utf-8").strip().splitlines()
        ok = answer[-1:] == ["答えの検査: PASS"]
        if oracle != 0 or not ok:
            bad += 1
            print(f"- {label} (`{arm}`): オラクル {'PASS' if oracle == 0 else '**FAIL**'} / "
                  f"答えの検査 {'PASS' if ok else '**FAIL**'}")  # fmt: skip
    print(f"{len(started)} 本のうち、オラクル PASS かつ答えの検査 PASS でないもの {bad} 本")
    stop = stop or bad > 0
    print()
    print("### 1. 件数の列（#33 本走の forward.tsv と照合）")
    print()
    for label in started:
        if not rounds_match(LOGS / f"{label}_forward.tsv"):
            stop = True
    print()
    print("### 2. 完走の秒: new − old（区間の下端が 0 より上なら止める）")
    print()
    old = [elapsed(lb) for lb, a in started.items() if a == "old"]
    new = [elapsed(lb) for lb, a in started.items() if a == "new"]
    d, t, df, p, lo, hi = welch(old, new)
    mo, mn = sum(old) / len(old), sum(new) / len(new)
    print(f"- old {mo:.2f} 秒 / new {mn:.2f} 秒（各 {len(old)}・{len(new)} 本）")
    print(f"- 差 {d:+.2f} 秒（t {t:.2f}、自由度 {df:.2f}、p {p:.4g}、"
          f"95% 区間 {lo:+.2f} … {hi:+.2f}）")  # fmt: skip
    slower = lo > 0
    if slower:
        print("- **遅くなった（本走の前に止めて報告する）**")
    elif hi < 0:
        print("- 速くなった（本走して記録にする）")
    else:
        print("- 区間が 0 をまたぐ（本走して記録にする。作りの変更として）")
    stop = stop or slower
    print()
    print("### 3. 巨大ページ（thp_fault_fallback の前後差と、表と配列に付いた量）")
    print()
    nonzero = {lb: v for lb in started if (v := fallback(lb)) != 0}
    print(f"thp_fault_fallback: {len(started)} 本のうち、0 でないもの {len(nonzero)} 本")
    if nonzero:
        print(nonzero)
    stop = stop or bool(nonzero)
    for arm in ("old", "new"):
        labels = [lb for lb, a in started.items() if a == arm]
        got = {lb: huge(lb, arm) for lb in labels}
        for (_, key), need in HUGE[arm].items():
            vals = sorted({g[key] for g in got.values()})
            short = [lb for lb in labels if got[lb][key] < need]
            seen = ", ".join(f"{v:,}" for v in vals)
            print(f"- `{arm}` {key}: {seen} kB（{need:,} に届かない本 {len(short)}）", short or "")
            stop = stop or bool(short)
    print()
    print("=> 止める: 本走に進まず報告する" if stop else "=> 止める条件に掛からない: 本走に進む")
    return 1 if stop else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
