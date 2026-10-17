#!/usr/bin/python3
"""完走の比較の検査と集計 (実験 mirror1_keep。記録試行ではない. 記録の門番でもない)。

    python3 experiments/mirror1_keep/compare_stats.py rounds <tsv>   1本の件数の列 (#36 本走と照合)
    python3 experiments/mirror1_keep/compare_stats.py huge <ラベル>   1本の巨大ページ
    python3 experiments/mirror1_keep/compare_stats.py                 18本の集計 → logs/compare_summary.txt

集計: 腕ごとの平均と範囲, 腕どうしの差 (mirror1_keep − base, mirror1 − base, mirror1 − mirror1_keep) の
Welch の 95% 区間 (gate_stats.welch. 比較は3本で多重比較未補正). 量は 完走 (/usr/bin/time -v の Elapsed)・
ユーザー時間・カーネル時間・minor fault・ピーク RSS, 全探索 (forward_total)・F1, 後退解析 (完走 − 全探索) と
段の合計 retreat_total, U_init・U_loop (と U_loop のユーザー時間とカーネル時間. 段の境界の累積の差)・U_draw・U_uk。
答えの検査 (毎本の answer.txt の最後の行) とオラクル174行も数え直す. 判定はしない。
"""

from __future__ import annotations

import csv
import pathlib
import re
import statistics
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
LOGS = HERE / "logs" / "compare"
sys.path.insert(0, str(HERE.parent))

from gate_stats import welch  # noqa: E402

REF = ROOT / "results" / "36_bb_unmove" / "forward.tsv"
# 巨大ページが付ききったときの量 (kB)。門番 #34 の new・門番 #35・#36 と同じ値 (配列は変わらない)
HUGE = {
    ("forward_summary", "anonhuge_seen_kB"): 104_448,
    ("retreat_summary", "anonhuge_init_kB"): 1_671_168,
    ("retreat_summary", "anonhuge_loop_kB"): 1_671_168,
}
KEYS = ("n_in", "n_win", "n_lose", "n_uk", "n_new_post")
ARMS = ("base", "mirror1", "mirror1_keep")
PAIRS = (("mirror1_keep", "base"), ("mirror1", "base"), ("mirror1", "mirror1_keep"))
RUNS_PER_ARM = 6
START = re.compile(r"^=== 開始 (?P<label>b\d\d_(?P<arm>\w+)) ")
DONE = re.compile(r"^=== 完了 (?P<label>b\d\d_\w+) ")
TIME = {
    "elapsed": re.compile(r"Elapsed \(wall clock\) time \(h:mm:ss or m:ss\): (?:(\d+):)?(\d+):([\d.]+)"),
    "user": re.compile(r"User time \(seconds\): ([\d.]+)"),
    "system": re.compile(r"System time \(seconds\): ([\d.]+)"),
    "minflt": re.compile(r"Minor \(reclaiming a frame\) page faults: (\d+)"),
    "rss_gb": re.compile(r"Maximum resident set size \(kbytes\): (\d+)"),
}
QUANTITIES = (
    "elapsed", "user", "system", "minflt", "rss_gb", "forward_total", "F1",
    "retreat_wall", "retreat_total", "U_init", "U_loop", "utime_U_loop_stage", "stime_U_loop_stage",
    "U_draw", "U_uk",
)  # fmt: skip


def table(path: pathlib.Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def rounds_match(path: pathlib.Path) -> bool:
    a, b = table(REF), table(path)
    ok = len(a) == len(b) and all(ra[k] == rb[k] for ra, rb in zip(a, b, strict=True) for k in KEYS)
    print(f"{path.name}: {len(b)} ラウンド（#36 は {len(a)}）/ 件数の列 {'一致' if ok else '**不一致**'}")
    return ok


def huge(label: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for name, key in HUGE:
        text = (LOGS / f"{label}_{name}.tsv").read_text(encoding="utf-8")
        values = [v for k, _, v in (ln.partition("\t") for ln in text.splitlines()) if k == key]
        if len(values) != 1:
            raise SystemExit(f"{label}_{name}.tsv に {key} が1行ない")
        out[key] = int(values[0])
    return out


def tsv(path: pathlib.Path) -> dict[str, float]:
    out: dict[str, float] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        k, _, v = line.partition("\t")
        try:
            out[k] = float(v)
        except ValueError:
            continue
    return out


def row(label: str) -> dict[str, float]:
    text = (LOGS / f"{label}_time.txt").read_text(encoding="utf-8")
    out: dict[str, float] = {}
    for key, pat in TIME.items():
        m = pat.search(text)
        if not m:
            raise SystemExit(f"{label}_time.txt に {key} が無い")
        if key == "elapsed":
            out[key] = int(m.group(1) or 0) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
        elif key == "rss_gb":
            out[key] = int(m.group(1)) * 1024 / 1e9
        else:
            out[key] = float(m.group(1))
    out.update(tsv(LOGS / f"{label}_forward_summary.tsv"))
    out.update(tsv(LOGS / f"{label}_retreat_summary.tsv"))
    out["retreat_wall"] = out["elapsed"] - out["forward_total"]
    for k in ("utime", "stime"):
        out[f"{k}_U_loop_stage"] = out[f"{k}_U_loop"] - out[f"{k}_U_init"]
    return out


def order_effect(rows: dict[str, list[dict[str, float]]]) -> str:
    """並びが変わった効果の見積もり ＝ (mirror1 − mirror1_keep) ＋ 並べ直しの費用 (回す前に決めた分け方)。
    並べ直しの費用は, ベンチ (logs/bench.tsv) の order の cycles の mirror1_keep − mirror1 (周ごとの差) を
    summary.py と同じ式で U_loop の秒に換算した値. 中央値と7周の最小〜最大を使う。"""
    if not (HERE / "logs" / "bench.tsv").exists():
        return ""
    import summary  # noqa: PLC0415

    brows = summary.table(summary.LOGS / "bench.tsv")
    ohr = summary.table(summary.LOGS / "bench_overhead.tsv")
    oh = {
        a: {e: statistics.median(float(r[e]) for r in ohr if r["arm"] == a) for e in summary.EVS}
        for a in ("mirror1", "mirror1_keep")
    }
    pp = summary.per_position([r for r in brows if r["arm"] in oh], oh)
    reps = sorted({r["rep"] for r in brows}, key=int)
    f = summary.freq_ghz()
    cost = [
        (pp[(r, "mirror1_keep", "order")]["cycles_u"] - pp[(r, "mirror1", "order")]["cycles_u"])
        * summary.N_ULOOP
        / (f * 1e9)
        for r in reps
    ]
    out = ["### 並びが変わった効果の見積もり（回す前に決めた分け方。見積もりで, 効果量ではない）", ""]
    for q in ("elapsed", "U_loop"):
        d, _t, _df, _p, lo, hi = welch([r[q] for r in rows["mirror1_keep"]], [r[q] for r in rows["mirror1"]])
        c = statistics.median(cost)
        out.append(
            f"- {q}: mirror1 − mirror1_keep {d:+.2f}（区間 {lo:+.2f}〜{hi:+.2f}） ＋ 並べ直しの費用 {c:+.2f}"
            f"（ベンチの換算。7周で {min(cost):+.2f}〜{max(cost):+.2f}） ＝ **{d + c:+.2f} 秒**"
            f"（区間の端と費用の端を足した幅 {lo + min(cost):+.2f}〜{hi + max(cost):+.2f}）"
        )
    out.append("")
    return "\n".join(out)


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[1] == "rounds":
        return 0 if rounds_match(pathlib.Path(argv[2])) else 1
    if len(argv) == 3 and argv[1] == "huge":
        got = huge(argv[2])
        short = {k: v for (_, k), need in HUGE.items() if (v := got[k]) < need}
        print(f"{argv[2]}: " + " / ".join(f"{k} {v:,}" for k, v in got.items()))
        if short:
            print(f"**届かない: {short}**")
        return 1 if short else 0
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    started: dict[str, str] = {}
    finished: set[str] = set()
    console = HERE / "logs" / "console_compare.log"
    for line in console.read_text(encoding="utf-8").splitlines():
        if m := START.match(line):
            started[m.group("label")] = m.group("arm")
        elif m := DONE.match(line):
            finished.add(m.group("label"))
    counts = {a: sum(1 for x in started.values() if x == a) for a in ARMS}
    print("## 完走の比較（3腕 × 6本。numactl でノード0に固定。判定はしない）")
    print()
    print(f"- 本数: 開始 {len(started)} / 完了 {len(finished)} / 腕ごと {counts}")
    bad = []
    for label in started:
        oracle = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "verify_log.py"), str(LOGS / f"{label}_main.log")],
            capture_output=True,
            check=False,
        ).returncode
        answer = (LOGS / f"{label}_answer.txt").read_text(encoding="utf-8").strip().splitlines()
        if oracle != 0 or answer[-1:] != ["答えの検査: PASS"]:
            bad.append(label)
    print(f"- オラクル174行と答えの検査が PASS でない本: {len(bad)} {bad}")
    ok = len(finished) == len(started) and all(c == RUNS_PER_ARM for c in counts.values()) and not bad
    print()
    rows = {a: [row(lb) for lb, x in started.items() if x == a and lb in finished] for a in ARMS}
    print("### 腕ごとの平均と範囲（秒。minor fault は回、ピーク RSS は GB）")
    print()
    print("| 量 | " + " | ".join(f"`{a}`" for a in ARMS) + " |")
    print("|---|" + "---|" * len(ARMS))
    for q in QUANTITIES:
        cells = []
        for a in ARMS:
            xs = [r[q] for r in rows[a]]
            fmt = ".0f" if q == "minflt" else ".3f" if q == "rss_gb" else ".2f"
            cells.append(f"{statistics.mean(xs):{fmt}}（{min(xs):{fmt}}〜{max(xs):{fmt}}）")
        print(f"| {q} | " + " | ".join(cells) + " |")
    print()
    print("### 腕どうしの差（平均の差と Welch の 95% 区間。3つの比較で多重比較未補正）")
    print()
    print("| 量 | " + " | ".join(f"{a} − {b}" for a, b in PAIRS) + " |")
    print("|---|" + "---|" * len(PAIRS))
    for q in QUANTITIES:
        cells = []
        for a, b in PAIRS:
            d, t, df, _p, lo, hi = welch([r[q] for r in rows[b]], [r[q] for r in rows[a]])
            fmt = "+.0f" if q == "minflt" else "+.3f" if q == "rss_gb" else "+.2f"
            cells.append(f"{d:{fmt}}（{lo:{fmt}}〜{hi:{fmt}}、t {t:.2f}、自由度 {df:.1f}）")
        print(f"| {q} | " + " | ".join(cells) + " |")
    print()
    est = order_effect(rows)
    if est:
        print(est)
    print("=> 検査: " + ("全本 PASS" if ok else "**外れた本か足りない本がある**"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
