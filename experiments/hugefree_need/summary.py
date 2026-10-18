#!/usr/bin/python3
"""実験 hugefree_need の集計と, 新しい基準の計算 (記録試行ではない)。手で書かず, 生ログからこれで作る。

    python3 experiments/hugefree_need/summary.py > experiments/hugefree_need/logs/summary.txt

本ごとに (logs/<ラベル>_*):
- 走る前の 2 MiB 以上の空き (before.txt の1行目), 走っているあいだの最小 (samples.tsv), 走り終わった直後と
  dat/ を消したあと (after.txt)
- 消費量 ＝ 走る前 − 走っているあいだの最小 (GiB)。pin はノード0, free はノード0・ノード1・両ノードの合計
  (合計は 0.2 秒おきの読みごとに2つのノードを足してから最小を取る)
- 持ち越し ＝ 走る前 − dat/ を消したあと (次の本が走る前に見る値との差に近い)
- 最小が起きた時刻と段 (下の段の当て方), AnonHugePages と Rss の最大, vmstat の前後差,
  thp_fault_alloc × 2 MiB (延べ), ピーク RSS, 段ごとの秒 (参考)
段の当て方 (近似): AnonHugePages が初めて 0 より大きくなった読み (発見済み表を確保した直後) を全探索の始まりとし,
F0〜F6 の秒を順に積む. AnonHugePages が初めて 0.95 GiB を超えた読み (後退解析の手数の配列を確保した直後) を後退解析の
始まりとし, U_init〜U_uk の秒を順に積む. どちらにも入らない時刻は「起動」「全探索と後退解析のあいだ」「後退解析のあと」。
読みの間隔 (0.2 秒) と, 確保から最初の読みまでの遅れのぶん, 境目の前後 0.2〜0.4 秒は取り違えうる。

新しい基準 (回す前に決めた。README の登録の節):
  基準 ＝ ceil(pin 3本のノード0の消費量の最大 × 1.5) GiB。free 2本のどちらかのノードの消費量がそれ (pin の最大) を
  超えたら, free の最大で同じ計算をする。
  止める: 新しい基準が 16 GiB 以上 / 消費量が本ごとに大きく違う (5本の「その本の消費量」の最大が最小の2倍を超える。
  その本の消費量は, pin はノード0, free は両ノードの合計)。
"""

from __future__ import annotations

import csv
import math
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
LOGS = HERE / "logs"
RUNS = (("p1_pin", "pin"), ("f2_free", "free"), ("p3_pin", "pin"), ("f4_free", "free"), ("p5_pin", "pin"))
FACTOR = 1.5
OLD_GIB = 16
FWD = ("F0", "F1", "F2", "F3", "F4", "F5", "F6")
RET = ("U_init", "U_loop", "U_draw", "U_uk")
HEAD = re.compile(r"node0 ([\d.]+) / node1 ([\d.]+) / 合計 ([\d.]+) GiB")
ELAPSED = re.compile(r"Elapsed \(wall clock\) time \(h:mm:ss or m:ss\): (?:(\d+):)?(\d+):([\d.]+)")
RSS = re.compile(r"Maximum resident set size \(kbytes\): (\d+)")


def heads(path: pathlib.Path) -> list[tuple[float, float, float]]:
    return [
        (float(m.group(1)), float(m.group(2)), float(m.group(3)))
        for ln in path.read_text(encoding="utf-8").splitlines()
        if ln.startswith("#") and (m := HEAD.search(ln))
    ]


def tsv(path: pathlib.Path) -> dict[str, float]:
    out: dict[str, float] = {}
    for ln in path.read_text(encoding="utf-8").splitlines():
        k, _, v = ln.partition("\t")
        try:
            out[k] = float(v)
        except ValueError:
            continue
    return out


def vmdiff(label: str) -> dict[str, int]:
    rows = [ln.split("\t") for ln in (LOGS / f"{label}_vmstat.tsv").read_text().splitlines()]
    return {k: int(rows[2][i]) - int(rows[1][i]) for i, k in enumerate(rows[0]) if i > 0}


def stage_at(t: float, samples: list[dict[str, str]], fs: dict[str, float], rs: dict[str, float]) -> str:
    ah = [(float(r["t"]), int(r["anonhuge_kB"])) for r in samples if r["anonhuge_kB"]]
    f0 = next((tt for tt, a in ah if a > 0), None)
    r0 = next((tt for tt, a in ah if a > 0.95 * 1048576), None)
    if f0 is None or t < f0:
        return "起動"
    acc = f0
    for k in FWD:
        if t < acc + fs.get(k, 0.0):
            return k
        acc += fs.get(k, 0.0)
    if r0 is None or t < r0:
        return "全探索と後退解析のあいだ"
    acc = r0
    for k in RET:
        if t < acc + rs.get(k, 0.0):
            return k
        acc += rs.get(k, 0.0)
    return "後退解析のあと"


def one(label: str, mode: str) -> dict[str, object]:
    before = heads(LOGS / f"{label}_before.txt")[0]
    after = heads(LOGS / f"{label}_after.txt")
    with (LOGS / f"{label}_samples.tsv").open(encoding="utf-8") as f:
        samples = list(csv.DictReader(f, delimiter="\t"))
    fs, rs = tsv(LOGS / f"{label}_forward_summary.tsv"), tsv(LOGS / f"{label}_retreat_summary.tsv")
    n0 = [(float(r["node0_gib"]), float(r["t"])) for r in samples]
    n1 = [(float(r["node1_gib"]), float(r["t"])) for r in samples]
    tot = [(float(r["node0_gib"]) + float(r["node1_gib"]), float(r["t"])) for r in samples]
    m0, m1, mt = min(n0), min(n1), min(tot)
    time_txt = (LOGS / f"{label}_time.txt").read_text(encoding="utf-8")
    e = ELAPSED.search(time_txt)
    rss = RSS.search(time_txt)
    assert e and rss
    vm = vmdiff(label)
    ah = [int(r["anonhuge_kB"]) for r in samples if r["anonhuge_kB"]]
    rk = [int(r["rss_kB"]) for r in samples if r["rss_kB"]]
    use = {"node0": before[0] - m0[0], "node1": before[1] - m1[0], "total": before[2] - mt[0]}
    return {
        "label": label,
        "mode": mode,
        "before": before,
        "after_exit": after[0],
        "after_clean": after[1] if len(after) > 1 else after[0],
        "use": use,
        "own": use["node0"] if mode == "pin" else use["total"],
        "min_t": {"node0": m0[1], "node1": m1[1], "total": mt[1]},
        "min_stage": {
            k: stage_at(t, samples, fs, rs) for k, t in (("node0", m0[1]), ("node1", m1[1]), ("total", mt[1]))
        },
        "n_samples": len(samples),
        "gap_max": max(float(b["t"]) - float(a["t"]) for a, b in zip(samples, samples[1:], strict=False)),
        "ah_max_gib": max(ah) / 1048576 if ah else 0.0,
        "rss_max_gib": max(rk) / 1048576 if rk else 0.0,
        "vm": vm,
        "elapsed": int(e.group(1) or 0) * 3600 + int(e.group(2)) * 60 + float(e.group(3)),
        "peak_rss_gib": int(rss.group(1)) / 1048576,
        "fs": fs,
        "rs": rs,
    }


def main() -> int:
    rows = [one(lb, m) for lb, m in RUNS if (LOGS / f"{lb}_samples.tsv").exists()]
    print(f"## 本ごと（{len(rows)} 本。GiB は 2 MiB 以上の空きブロック）")
    print()
    print("| 本 | 走る前 n0 / n1 / 計 | 最小 n0 / n1 / 計 | **消費量** n0 / n1 / 計 | 最小の段（n0 / n1 / 計） | 直後 n0 / n1 / 計 | dat/ を消したあと n0 / n1 / 計 | **持ち越し** n0 / n1 / 計 |")
    print("|---|---|---|---|---|---|---|---|")
    for r in rows:
        b, a1, a2, u = r["before"], r["after_exit"], r["after_clean"], r["use"]
        mins = (b[0] - u["node0"], b[1] - u["node1"], b[2] - u["total"])
        st = r["min_stage"]
        print(
            f"| {r['label']} | {b[0]:.2f} / {b[1]:.2f} / {b[2]:.2f} | {mins[0]:.2f} / {mins[1]:.2f} / {mins[2]:.2f} "
            f"| **{u['node0']:.2f} / {u['node1']:.2f} / {u['total']:.2f}** | {st['node0']} / {st['node1']} / {st['total']} "
            f"| {a1[0]:.2f} / {a1[1]:.2f} / {a1[2]:.2f} | {a2[0]:.2f} / {a2[1]:.2f} / {a2[2]:.2f} "
            f"| **{b[0] - a2[0]:+.2f} / {b[1] - a2[1]:+.2f} / {b[2] - a2[2]:+.2f}** |"
        )
    print()
    print("| 本 | 最小の時刻（秒。n0 / n1 / 計） | AnonHugePages の最大 | Rss の最大（読み） | ピーク RSS（time） | thp_fault_alloc（× 2 MiB） | thp_fault_fallback | thp_collapse_alloc | compact_stall | 読みの数・最大の間隔 | 完走（参考） |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        vm, mt = r["vm"], r["min_t"]
        print(
            f"| {r['label']} | {mt['node0']:.1f} / {mt['node1']:.1f} / {mt['total']:.1f} | {r['ah_max_gib']:.3f} GiB "
            f"| {r['rss_max_gib']:.2f} GiB | {r['peak_rss_gib']:.2f} GiB "
            f"| {vm['thp_fault_alloc']}（{vm['thp_fault_alloc'] * 2 / 1024:.3f} GiB） | {vm['thp_fault_fallback']} "
            f"| {vm['thp_collapse_alloc']} | {vm['compact_stall']} | {r['n_samples']}・{r['gap_max']:.2f} 秒 | {r['elapsed']:.2f} 秒 |"
        )
    print()
    print("段ごとの秒（参考。速さの比較には使わない）:")
    print()
    for r in rows:
        fs, rs = r["fs"], r["rs"]
        print(f"- {r['label']}: " + " / ".join(f"{k} {fs.get(k, 0):.2f}" for k in FWD) + " / "
              + " / ".join(f"{k} {rs.get(k, 0):.2f}" for k in RET))  # fmt: skip
    print()

    print("## 新しい基準（回す前に決めた式）")
    print()
    pins = [r for r in rows if r["mode"] == "pin"]
    frees = [r for r in rows if r["mode"] == "free"]
    stop = []
    if len(pins) != 3 or len(frees) != 2:
        stop.append(f"本数が足りない（pin {len(pins)}・free {len(frees)}）")
    m_pin = max(r["use"]["node0"] for r in pins) if pins else 0.0
    m_free = max(max(r["use"]["node0"], r["use"]["node1"]) for r in frees) if frees else 0.0
    base = m_pin
    print(f"- pin 3本のノード0の消費量の最大: {m_pin:.2f} GiB（" + "、".join(f"{r['label']} {r['use']['node0']:.2f}" for r in pins) + "）")
    print(f"- free 2本の、どちらかのノードの消費量の最大: {m_free:.2f} GiB（" + "、".join(
        f"{r['label']} n0 {r['use']['node0']:.2f} / n1 {r['use']['node1']:.2f}" for r in frees) + "）")  # fmt: skip
    if m_free > m_pin:
        base = m_free
        print("- free のほうが大きいので, free の最大で計算する")
    new = math.ceil(base * FACTOR)
    print(f"- **新しい基準 ＝ ceil({base:.2f} × {FACTOR}) ＝ ceil({base * FACTOR:.2f}) ＝ {new} GiB**")
    owns = [r["own"] for r in rows]
    ratio = max(owns) / min(owns) if owns and min(owns) > 0 else math.inf
    print(f"- 本ごとの消費量（pin はノード0、free は両ノードの合計）: " + "、".join(f"{r['label']} {r['own']:.2f}" for r in rows)
          + f"。最大 ÷ 最小 ＝ {ratio:.2f}")  # fmt: skip
    if new >= OLD_GIB:
        stop.append(f"新しい基準が {OLD_GIB} GiB 以上（{new} GiB）")
    if ratio > 2:
        stop.append(f"消費量が本ごとに大きく違う（最大 ÷ 最小 ＝ {ratio:.2f} > 2）")
    fb = {r["label"]: r["vm"]["thp_fault_fallback"] for r in rows if r["vm"]["thp_fault_fallback"] != 0}
    if fb:
        stop.append(f"thp_fault_fallback が 0 でない本がある: {fb}")
    print()
    print("### 5本続けたあとで、新しい基準で走れたか（キャッシュは落としていない）")
    print()
    for r in rows:
        a = r["after_clean"]
        print(f"- {r['label']} のあと: ノード0 {a[0]:.2f} GiB（門番の判定） → {'走れる' if a[0] >= new else '**走れない**'} / "
              f"両ノードの合計 {a[2]:.2f} GiB（tools/run.sh の判定） → {'走れる' if a[2] >= new else '**走れない**'}")  # fmt: skip
    print()
    print("=> 止める: " + "; ".join(stop) if stop else f"=> 止める条件に掛からない: 新しい基準は {new} GiB")
    return 1 if stop else 0


if __name__ == "__main__":
    sys.exit(main())
