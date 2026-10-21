#!/usr/bin/python3
"""実験 prep_ahead の集計 (記録試行ではない)。手で書かず, 生ログからこれで作る。

    python3 experiments/prep_ahead/summary.py > experiments/prep_ahead/logs/summary.txt

1. 一致の検査の完走 (logs/verify/): 答えの検査・diff -rq・オラクル
2. 完走の比較 (logs/compare/。base 6本・prep1 6本): 量ごとに腕の平均と範囲 (最小〜最大), prep1 − base の
   平均の差と Welch の 95% 区間 (gate_stats.welch)。**判定の量は U_loop の秒の差の区間** (README の「推し方」)
3. perf (logs/perf/。腕ごとに T1・M1・FB・cycles を1本ずつ): U_loop のフロンティア1局面あたり (分母は main.log の
   「展開した局面 (perf_34)」), T1 の topdown の一部 (retiring・frontend bound), M1 の stalls_mem_any・stalls_total・
   resource_stalls.sb, FB のフィルバッファの指標。cycles の標本は区分 (bucket()) に寄せ, 割合 × その腕の T1 の cycles / フロンティアにする。
   区分の行は腕のソース (prep1 はパッチを当てたもの) の目印から決める (行番号は腕ごとに違う)
"""

from __future__ import annotations

import csv
import os
import pathlib
import re
import statistics
import subprocess
import sys
import tempfile
from collections import defaultdict

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE.parent))
from gate_stats import welch  # noqa: E402

LOGS = pathlib.Path(os.environ.get("LOGS", HERE / "logs"))  # 集計を試すときだけ別の置き場所を渡す
ARMS = ("base", "prep1")
IMPL_C = ROOT / "impl" / "40_dtm_ahead" / "animal_shogi.c"
GENERATOR = ("unmoveCandidates", "invBoard", "normalBoard", "unmoveMirror")
START = re.compile(r"^=== 開始 (?P<label>\S+) \(")
DONE = re.compile(r"^=== 完了 (?P<label>\S+) ")
COMPARE = re.compile(r"^c(?P<block>\d)(?P<pos>[a-d])_(?P<arm>base|prep1)$")
PERF = re.compile(r"^p_(?P<arm>base|prep1)_(?P<kind>T1|M1|FB|cyc)$")
TIME = {
    "elapsed": re.compile(r"Elapsed \(wall clock\) time \(h:mm:ss or m:ss\): (?:(\d+):)?(\d+):([\d.]+)"),
    "user": re.compile(r"User time \(seconds\): ([\d.]+)"),
    "system": re.compile(r"System time \(seconds\): ([\d.]+)"),
    "minflt": re.compile(r"Minor \(reclaiming a frame\) page faults: (\d+)"),
    "rss_gb": re.compile(r"Maximum resident set size \(kbytes\): (\d+)"),
}
QUANTITIES = (
    ("U_loop", "**`U_loop`**（判定の量）"),
    ("utime_U_loop_stage", "`U_loop` のユーザー時間"),
    ("stime_U_loop_stage", "`U_loop` のカーネル時間"),
    ("elapsed", "完走"),
    ("user", "ユーザー時間"),
    ("system", "カーネル時間"),
    ("forward_total", "全探索"),
    ("F1", "F1"),
    ("retreat_wall", "後退解析（完走 − 全探索）"),
    ("retreat_total", "段の合計 `retreat_total`"),
    ("U_init", "`U_init`"),
    ("U_draw", "`U_draw`"),
    ("U_uk", "`U_uk`"),
    ("minflt", "minor fault"),
    ("rss_gb", "ピーク RSS（GB）"),
)


def sources() -> dict[str, list[str]]:
    """腕 → animal_shogi.c の行。prep1 は #40 の C に patches/prep1.patch を当てたもの。"""
    with tempfile.TemporaryDirectory() as t:
        (pathlib.Path(t) / "animal_shogi.c").write_bytes(IMPL_C.read_bytes())
        subprocess.run(
            ["patch", "--quiet", "--fuzz=0", "-p1", "-d", t, "-i", str(HERE / "patches" / "prep1.patch")],
            check=True,
        )
        patched = (pathlib.Path(t) / "animal_shogi.c").read_text(encoding="utf-8").splitlines()
    return {"base": IMPL_C.read_text(encoding="utf-8").splitlines(), "prep1": patched}


SRC = sources()


def line_of(arm: str, text: str, start: int = 0) -> int:
    """腕のソースで text を含む最初の行 (1始まり。start 行より後ろ)。"""
    src = SRC[arm]
    return next(i + 1 for i in range(start, len(src)) if text in src[i])


def marks(arm: str) -> dict[str, object]:
    """区分の行 (perf_39/summary.py の L_* と同じ目印。g_dtm の先読みは腕に2行ありうる)。"""
    step = line_of(arm, "int unmoveStep(")
    end = line_of(arm, "out[0] = nf;", step)
    sieve = line_of(arm, "if (g_dtm[r[j]] != DTM_UNDECIDED) continue;", step)
    kept = line_of(arm, "n_kept += (uint64_t)m;", sieve)
    decide = (line_of(arm, "for (int j = 0; j < m; j++) {", kept), line_of(arm, "found[nf++] = cand[j];", kept))
    pref = {i + 1 for i in range(step, end) if "__builtin_prefetch(&g_dtm[" in SRC[arm][i]}
    ppref = {i + 1 for i in range(step, end) if "__builtin_prefetch(&g_prep[" in SRC[arm][i]}
    prep = line_of(arm, "if (g_prep[rr] == 0) return -4;", kept)
    return {"sieve_line": sieve, "prep_line": prep, "sieve": (sieve - 1, kept), "decide": decide, "pref": pref, "ppref": ppref}


MARKS = {a: marks(a) for a in ARMS}


def bucket(arm: str, where: str, chain: str, line: str) -> str:
    """U_loop の標本の区分 (perf_39/summary.py の bucket_u() を腕の行に向けたもの)。"""
    if where == "[kernel]":
        return "カーネル"
    if where.startswith(("python", "libpython")):
        return "Python"
    if where.startswith("libc"):
        return "libc"
    if where != "animal_shogi.so":
        return f"そのほか（{where}）"
    fs = chain.split(">")
    ln = int(line)
    m = MARKS[arm]
    if fs[0] in GENERATOR:
        return "逆向きの生成器"
    if fs[0] != "unmoveStep":
        return f".so のほかの関数（{fs[0]}）"
    if "rankOf" in fs:
        return "rankOf"
    if ln in m["pref"]:  # type: ignore[operator]
        return "g_dtm の先読み"
    if ln in m["ppref"]:  # type: ignore[operator]
        return "g_prep の先読み"
    lo, hi = m["sieve"]  # type: ignore[misc]
    if lo <= ln <= hi:
        return "未定の候補をふるう"
    lo, hi = m["decide"]  # type: ignore[misc]
    if lo <= ln <= hi:
        return "決める"
    return "unmoveStep のそのほか"


def tsv(path: pathlib.Path) -> dict[str, float]:
    out: dict[str, float] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        k, _, v = line.partition("\t")
        try:
            out[k] = float(v)
        except ValueError:
            continue
    return out


def row(d: pathlib.Path, label: str) -> dict[str, float]:
    text = (d / f"{label}_time.txt").read_text(encoding="utf-8")
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
    out.update(tsv(d / f"{label}_forward_summary.tsv"))
    out.update(tsv(d / f"{label}_retreat_summary.tsv"))
    for k in ("utime", "stime"):
        out[f"{k}_U_loop_stage"] = out[f"{k}_U_loop"] - out[f"{k}_U_init"]
    out["retreat_wall"] = out["elapsed"] - out["forward_total"]
    return out


def span(xs: list[float], fmt: str) -> str:
    return f"{statistics.mean(xs):{fmt}}（{min(xs):{fmt}}〜{max(xs):{fmt}}）"


def front_count(d: pathlib.Path, label: str) -> int:
    m = re.search(r"展開した局面 \(perf_34\)：(\d+)", (d / f"{label}_main.log").read_text(encoding="utf-8"))
    assert m, f"{label}_main.log に展開した局面の行が無い"
    return int(m.group(1))


def stat(d: pathlib.Path, label: str) -> tuple[dict[str, float], float]:
    """U_loop の (イベント → 値, 多重化の最小の比率 %)。"""
    out: dict[str, float] = {}
    pct = 100.0
    for line in (d / f"{label}_stat_U_loop.csv").read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        cols = line.split(",")
        if cols[0].startswith("<"):
            raise SystemExit(f"{label}: {cols[2]} が数えられていない")
        out[cols[2]] = float(cols[0])
        pct = min(pct, float(cols[4]))
    return out, pct


def record(d: pathlib.Path, label: str) -> list[dict[str, str]]:
    with (d / f"{label}_record_U_loop.tsv").open(encoding="utf-8") as f:
        return list(csv.DictReader((ln for ln in f if not ln.startswith("#")), delimiter="\t"))


def started(path: pathlib.Path) -> tuple[list[str], set[str]]:
    labels, done = [], set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if m := START.match(line):
            labels.append(m.group("label"))
        elif m := DONE.match(line):
            done.add(m.group("label"))
    return labels, done


def verify_section(labels: list[str], done: set[str]) -> None:
    print("## 1. 一致の検査の完走（計時に使わない）")
    print()
    d = LOGS / "verify"
    for lb in (x for x in labels if x.startswith("v_")):
        ans = (d / f"{lb}_answer.txt").read_text(encoding="utf-8").strip().splitlines()
        diff = (d / f"{lb}_diff.txt").read_text(encoding="utf-8").strip().splitlines()
        print(f"- {lb}: 完了 {'する' if lb in done else '**しない**'} / {ans[0]} / {ans[-1]}")
        print(f"- {lb}: {diff[-1]}")
    print()


def compare_section(labels: list[str], done: set[str]) -> None:
    d = LOGS / "compare"
    runs = {a: [lb for lb in labels if (m := COMPARE.match(lb)) and m.group("arm") == a] for a in ARMS}
    print("## 2. 完走の比較（`base prep1 prep1 base` × 3）")
    print()
    print(f"- 本数: base {len(runs['base'])} / prep1 {len(runs['prep1'])}（完了 "
          f"{sum(1 for a in ARMS for lb in runs[a] if lb in done)}）")  # fmt: skip
    bad = [lb for a in ARMS for lb in runs[a]
           if not (d / f"{lb}_answer.txt").read_text(encoding="utf-8").strip().endswith("PASS")]  # fmt: skip
    print(f"- 答えの検査が PASS でない本: {len(bad)} {bad if bad else ''}")
    rows = {a: [row(d, lb) for lb in runs[a]] for a in ARMS}
    print()
    print("| 量 | `base`（平均と範囲） | `prep1`（平均と範囲） | prep1 − base | 95% 区間 | t・自由度 |")
    print("|---|---|---|---|---|---|")
    for key, name in QUANTITIES:
        fmt = ".0f" if key == "minflt" else ".3f" if key == "rss_gb" else ".2f"
        a, b = [r[key] for r in rows["base"]], [r[key] for r in rows["prep1"]]
        diff, t, df, _, lo, hi = welch(a, b)
        print(f"| {name} | {span(a, fmt)} | {span(b, fmt)} | {diff:+{fmt}} | {lo:+{fmt}} … {hi:+{fmt}} | "
              f"{t:.2f}・{df:.2f} |")  # fmt: skip
    a, b = [r["U_loop"] for r in rows["base"]], [r["U_loop"] for r in rows["prep1"]]
    _, _, _, _, lo, hi = welch(a, b)
    print()
    verdict = (
        "区間の上端が 0 より下 → #41 として記録の門番にかける候補として推す"
        if hi < 0
        else "区間が 0 をまたぐか上 → 推さない"
    )
    print(f"- 推し方（`U_loop` の秒の差の区間 {lo:+.2f} … {hi:+.2f}）: {verdict}")
    print()


def perf_section(labels: list[str]) -> None:  # noqa: PLR0915
    d = LOGS / "perf"
    print("## 3. perf（`U_loop` の区間。腕ごとに T1・M1・FB・cycles を1本ずつ）")
    print()
    lbs = {(m.group("arm"), m.group("kind")): lb for lb in labels if (m := PERF.match(lb))}
    front = {k: front_count(d, lb) for k, lb in lbs.items()}
    print(f"- 分母（展開した局面）: {sorted(set(front.values()))}（全本で同じなら1つ）")
    per: dict[str, dict[str, float]] = {}
    for arm in ARMS:
        t1, p1 = stat(d, lbs[(arm, "T1")])
        m1, p2 = stat(d, lbs[(arm, "M1")])
        fb, p3 = stat(d, lbs[(arm, "FB")])
        ff = front[(arm, "FB")]
        f = front[(arm, "T1")]
        u = tsv(d / f"{lbs[(arm, 'T1')]}_retreat_summary.tsv")["U_loop"]
        per[arm] = {
            "多重化の最小（%）": min(p1, p2, p3),
            "U_loop の秒（T1 の本）": u,
            "cycles / フロンティア（T1）": t1["cycles"] / f,
            "instructions / フロンティア（T1）": t1["instructions"] / f,
            "IPC（T1）": t1["instructions"] / t1["cycles"],
            "retiring（T1）": t1["uops_retired.retire_slots"] / t1["cycles"] / 4,
            "frontend bound（T1）": t1["idq_uops_not_delivered.core"] / t1["cycles"] / 4,
            "cycles / フロンティア（M1）": m1["cycles"] / front[(arm, "M1")],
            "`stalls_mem_any` / フロンティア（M1）": m1["cycle_activity.stalls_mem_any"] / front[(arm, "M1")],
            "`stalls_mem_any` / cycles（M1）": m1["cycle_activity.stalls_mem_any"] / m1["cycles"],
            "`stalls_total` / cycles（M1）": m1["cycle_activity.stalls_total"] / m1["cycles"],
            "`resource_stalls.sb` / cycles（M1）": m1["resource_stalls.sb"] / m1["cycles"],
            "cycles / フロンティア（FB）": fb["cycles"] / ff,
            "`l1d_pend_miss.fb_full` / フロンティア（FB）": fb["l1d_pend_miss.fb_full"] / ff,
            "`l1d_pend_miss.fb_full` / cycles（FB）": fb["l1d_pend_miss.fb_full"] / fb["cycles"],
            "`load_hit_pre.sw_pf` / フロンティア（FB）": fb["load_hit_pre.sw_pf"] / ff,
            "`mem_load_uops_retired.hit_lfb` / フロンティア（FB）": fb["mem_load_uops_retired.hit_lfb"] / ff,
        }
    print()
    print("| 量 | `base` | `prep1` | prep1 − base |")
    print("|---|---|---|---|")
    for key in per["base"]:
        a, b = per["base"][key], per["prep1"][key]
        pct = "/ cycles" in key or key.startswith(("retiring", "frontend"))
        if pct:
            print(f"| {key} | {100 * a:.1f}% | {100 * b:.1f}% | {100 * (b - a):+.1f} pt |")
        else:
            print(f"| {key} | {a:,.2f} | {b:,.2f} | {b - a:+,.2f} |")
    print()
    print("### cycles の標本の区分（`U_loop`。割合 × その腕の T1 の cycles / フロンティア）")
    print()
    share: dict[str, dict[str, float]] = {}
    sieve_line: dict[str, float] = {}
    prep_line: dict[str, float] = {}
    total: dict[str, int] = {}
    for arm in ARMS:
        rows = record(d, lbs[(arm, "cyc")])
        n = sum(int(r["samples"]) for r in rows)
        total[arm] = n
        acc: dict[str, int] = defaultdict(int)
        for r in rows:
            acc[bucket(arm, r["where"], r["chain"], r["line"])] += int(r["samples"])
        share[arm] = {k: v / n for k, v in acc.items()}
        step = [r for r in rows if r["where"] == "animal_shogi.so" and r["chain"] == "unmoveStep"]
        for key, out in (("sieve_line", sieve_line), ("prep_line", prep_line)):
            ln = str(MARKS[arm][key])
            out[arm] = sum(int(r["samples"]) for r in step if r["line"] == ln) / n
        stats = (d / f"{lbs[(arm, 'cyc')]}_record_stats_U_loop.txt").read_text(encoding="utf-8")
        thr = re.findall(r"^\s*(\w*THROTTLE|LOST\w*) events:\s+(\d+)", stats, re.M)
        print(f"- {arm}: 標本 {n:,}、ふるいの読みの行は {MARKS[arm]['sieve_line']} 行、g_prep の読みの行は {MARKS[arm]['prep_line']} 行、"
              f"THROTTLE・LOST {', '.join(f'{k} {v}' for k, v in thr) or 'の行なし（0 回）'}")  # fmt: skip
    print()
    cyc = {a: per[a]["cycles / フロンティア（T1）"] for a in ARMS}
    sec = {a: per[a]["U_loop の秒（T1 の本）"] for a in ARMS}
    keys = sorted(set(share["base"]) | set(share["prep1"]), key=lambda k: -share["base"].get(k, 0.0))
    print("| 区分 | `base` の割合 | `prep1` の割合 | `base` cycles / フロンティア | `prep1` | 差 | 差（秒） |")
    print("|---|---|---|---|---|---|---|")
    lines = {
        "（ふるいの g_dtm の読みの1行）": sieve_line,
        "（決めるの g_prep の読みの1行）": prep_line,
    }
    for k in [*keys, *lines]:
        a = lines[k]["base"] if k in lines else share["base"].get(k, 0.0)
        b = lines[k]["prep1"] if k in lines else share["prep1"].get(k, 0.0)
        ca, cb = a * cyc["base"], b * cyc["prep1"]
        print(f"| {k} | {100 * a:.1f}% | {100 * b:.1f}% | {ca:.1f} | {cb:.1f} | {cb - ca:+.1f} | "
              f"{b * sec['prep1'] - a * sec['base']:+.2f} |")  # fmt: skip
    print(f"| 計 | 100% | 100% | {cyc['base']:.1f} | {cyc['prep1']:.1f} | {cyc['prep1'] - cyc['base']:+.1f} | "
          f"{sec['prep1'] - sec['base']:+.2f} |")  # fmt: skip
    print()
    print("- 区分の秒は 割合 × その腕の T1 の本の `U_loop` の秒（1本ずつなので幅は無い）")


def main() -> int:
    labels, done = started(LOGS / "console.log")
    print(f"本数: 開始 {len(labels)} / 完了 {len(done)}")
    print()
    verify_section(labels, done)
    compare_section(labels, done)
    perf_section(labels)
    return 0


if __name__ == "__main__":
    sys.exit(main())
