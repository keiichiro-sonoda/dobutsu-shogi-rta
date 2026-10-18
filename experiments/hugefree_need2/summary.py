#!/usr/bin/python3
"""実験 hugefree_need2 の集計と, 新しい基準の計算 (記録試行ではない)。手で書かず, 生ログからこれで作る。

    python3 experiments/hugefree_need2/summary.py > experiments/hugefree_need2/logs/summary.txt

experiments/hugefree_need/summary.py を, 2回目の定義 (README の登録の節) に替えたもの。本ごとに (logs/<ラベル>_*):
- **消費量** ＝ 走る前の空き − 走っているあいだのその最小 (GiB)。空きは**全部の大きさ (order 0〜10) の空きブロックの合計**。
  走る前は before.txt の /proc/buddyinfo の写し, 走っているあいだは samples.tsv の node*_all_gib。
  pin はノード0, free はノード0・ノード1・両ノードの合計 (合計は読みごとに足してから最小を取る)
- 参考: 2 MiB 以上 (order 9 以上) の空きの減り (1回目の定義), 持ち越し (走る前 − dat/ を消したあと. 全部の大きさと 2 MiB 以上),
  最小が起きた段, AnonHugePages と Rss の最大, vmstat の前後差, thp_fault_alloc × 2 MiB (延べ), ピーク RSS, 段ごとの秒
段の当て方は 1回目と同じ近似 (AnonHugePages が 0 を超えた読みを全探索の始まり, 0.95 GiB を超えた読みを後退解析の始まりとして
段の秒を積む. 境目の前後 0.2〜0.4 秒は取り違えうる)。

新しい基準 (回す前に決めた):
  基準 ＝ ceil(pin 3本のノード0の消費量の最大 × 1.5) GiB。free 2本のどちらかのノードの消費量がそれ (pin の最大) を
  超えたら, free の最大で同じ計算をする。
  止める: 新しい基準が 16 GiB 以上 / 消費量が本ごとに大きく違う (5本の「その本の消費量」の最大が最小の2倍を超える。
  その本の消費量は, pin はノード0, free は両ノードの合計)。
走る前の判定 (2 MiB 以上の空きを基準と比べる) は変えないので, 5本続けたあとで走れたかは 2 MiB 以上の空きで見る。
"""

from __future__ import annotations

import csv
import math
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
LOGS = HERE / "logs"
RUNS = (
    ("p1_pin", "pin"), ("f2_free", "free"), ("p3_pin", "pin"), ("f4_free", "free"), ("p5_pin", "pin"),
)  # fmt: skip
FACTOR = 1.5
OLD_GIB = 16
FWD = ("F0", "F1", "F2", "F3", "F4", "F5", "F6")
RET = ("U_init", "U_loop", "U_draw", "U_uk")
ELAPSED = re.compile(r"Elapsed \(wall clock\) time \(h:mm:ss or m:ss\): (?:(\d+):)?(\d+):([\d.]+)")
RSS = re.compile(r"Maximum resident set size \(kbytes\): (\d+)")
NODES = ("0", "1")


def snapshots(path: pathlib.Path) -> list[dict[str, list[int]]]:
    """ファイルの中の /proc/buddyinfo の写し (見出しの行ごとに1つ) → ノード → order ごとの個数 (zone を足す)。"""
    out: list[dict[str, list[int]]] = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        if ln.startswith("#"):
            out.append({})
            continue
        c = ln.split()
        if not c or c[0] != "Node" or not out:
            continue
        counts = [int(x) for x in c[4:]]
        acc = out[-1].setdefault(c[1].rstrip(","), [0] * len(counts))
        for i, n in enumerate(counts):
            acc[i] += n
    return out


def gib(counts: list[int], lo: int) -> float:
    return sum(n * 4 * 2**o for o, n in enumerate(counts) if o >= lo) / 1048576


def free_of(snap: dict[str, list[int]], lo: int) -> dict[str, float]:
    d = {n: gib(snap.get(n, [0]), lo) for n in NODES}
    d["total"] = d["0"] + d["1"]
    return d


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


def consumption(
    before: dict[str, float], samples: list[dict[str, str]], col: str
) -> tuple[dict[str, float], dict[str, float]]:
    """(消費量, 最小の時刻)。col は all (全部の大きさ) か ge2m (2 MiB 以上)。"""
    key = {"all": "node{}_all_gib", "ge2m": "node{}_gib"}[col]
    series = {n: [(float(r[key.format(n)]), float(r["t"])) for r in samples] for n in NODES}
    series["total"] = [
        (float(r[key.format(0)]) + float(r[key.format(1)]), float(r["t"])) for r in samples
    ]
    use, when = {}, {}
    for n, s in series.items():
        v, t = min(s)
        use[n], when[n] = before[n] - v, t
    return use, when


def one(label: str, mode: str) -> dict[str, object]:
    snap_b = snapshots(LOGS / f"{label}_before.txt")[0]
    snaps_a = snapshots(LOGS / f"{label}_after.txt")
    with (LOGS / f"{label}_samples.tsv").open(encoding="utf-8") as f:
        samples = list(csv.DictReader(f, delimiter="\t"))
    fs = tsv(LOGS / f"{label}_forward_summary.tsv")
    rs = tsv(LOGS / f"{label}_retreat_summary.tsv")
    b_all, b_big = free_of(snap_b, 0), free_of(snap_b, 9)
    use, when = consumption(b_all, samples, "all")
    use_big, _ = consumption(b_big, samples, "ge2m")
    clean = snaps_a[-1]
    time_txt = (LOGS / f"{label}_time.txt").read_text(encoding="utf-8")
    e, rss = ELAPSED.search(time_txt), RSS.search(time_txt)
    assert e and rss
    ah = [int(r["anonhuge_kB"]) for r in samples if r["anonhuge_kB"]]
    rk = [int(r["rss_kB"]) for r in samples if r["rss_kB"]]
    return {
        "label": label,
        "mode": mode,
        "b_all": b_all,
        "b_big": b_big,
        "use": use,
        "use_big": use_big,
        "own": use["0"] if mode == "pin" else use["total"],
        "when": when,
        "stage": {n: stage_at(t, samples, fs, rs) for n, t in when.items()},
        "carry_all": {n: b_all[n] - v for n, v in free_of(clean, 0).items()},
        "carry_big": {n: b_big[n] - v for n, v in free_of(clean, 9).items()},
        "after_big": free_of(clean, 9),
        "n_samples": len(samples),
        "ah_max_gib": max(ah) / 1048576 if ah else 0.0,
        "rss_max_gib": max(rk) / 1048576 if rk else 0.0,
        "vm": vmdiff(label),
        "elapsed": int(e.group(1) or 0) * 3600 + int(e.group(2)) * 60 + float(e.group(3)),
        "peak_rss_gib": int(rss.group(1)) / 1048576,
        "fs": fs,
        "rs": rs,
    }


def trio(d: dict[str, float], fmt: str = ".2f") -> str:
    return f"{d['0']:{fmt}} / {d['1']:{fmt}} / {d['total']:{fmt}}"


def main() -> int:  # noqa: C901, PLR0915
    rows = [one(lb, m) for lb, m in RUNS if (LOGS / f"{lb}_samples.tsv").exists()]
    print(f"## 本ごと（{len(rows)} 本。GiB。n0 / n1 / 両ノードの合計）")
    print()
    print("| 本 | 走る前の空き（全部の大きさ） | **消費量**（全部の大きさ） | 最小の段 | 参考: 2 MiB 以上の減り | 持ち越し（全部 / 2 MiB 以上） |")
    print("|---|---|---|---|---|---|")
    for r in rows:
        st = r["stage"]
        ca, cb = r["carry_all"], r["carry_big"]
        print(
            f"| {r['label']} | {trio(r['b_all'])} | **{trio(r['use'])}** | {st['0']} / {st['1']} / {st['total']} "
            f"| {trio(r['use_big'])} | {trio(ca, '+.2f')}  /  {trio(cb, '+.2f')} |"
        )
    print()
    print("| 本 | 最小の時刻（秒） | AnonHugePages の最大 | Rss の最大（読み） | ピーク RSS（time） | thp_fault_alloc（× 2 MiB） | thp_fault_fallback | compact_stall | 読みの数 | 完走（参考） |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        vm, w = r["vm"], r["when"]
        print(
            f"| {r['label']} | {w['0']:.1f} / {w['1']:.1f} / {w['total']:.1f} | {r['ah_max_gib']:.3f} GiB "
            f"| {r['rss_max_gib']:.2f} GiB | {r['peak_rss_gib']:.2f} GiB "
            f"| {vm['thp_fault_alloc']}（{vm['thp_fault_alloc'] * 2 / 1024:.3f} GiB） | {vm['thp_fault_fallback']} "
            f"| {vm['compact_stall']} | {r['n_samples']} | {r['elapsed']:.2f} 秒 |"
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
    m_pin = max(r["use"]["0"] for r in pins) if pins else 0.0
    m_free = max(max(r["use"]["0"], r["use"]["1"]) for r in frees) if frees else 0.0
    print(f"- pin 3本のノード0の消費量の最大: {m_pin:.2f} GiB（"
          + "、".join(f"{r['label']} {r['use']['0']:.2f}" for r in pins) + "）")  # fmt: skip
    print(f"- free 2本の、どちらかのノードの消費量の最大: {m_free:.2f} GiB（"
          + "、".join(f"{r['label']} n0 {r['use']['0']:.2f} / n1 {r['use']['1']:.2f}" for r in frees) + "）")  # fmt: skip
    base = m_pin
    if m_free > m_pin:
        base = m_free
        print("- free のほうが大きいので, free の最大で計算する")
    new = math.ceil(base * FACTOR)
    print(f"- **新しい基準 ＝ ceil({base:.2f} × {FACTOR}) ＝ ceil({base * FACTOR:.2f}) ＝ {new} GiB**")
    owns = [r["own"] for r in rows]
    ratio = max(owns) / min(owns) if owns and min(owns) > 0 else math.inf
    print("- 本ごとの消費量（pin はノード0、free は両ノードの合計）: "
          + "、".join(f"{r['label']} {r['own']:.2f}" for r in rows) + f"。最大 ÷ 最小 ＝ {ratio:.2f}")  # fmt: skip
    if new >= OLD_GIB:
        stop.append(f"新しい基準が {OLD_GIB} GiB 以上（{new} GiB）")
    if ratio > 2:
        stop.append(f"消費量が本ごとに大きく違う（最大 ÷ 最小 ＝ {ratio:.2f} > 2）")
    fb = {r["label"]: r["vm"]["thp_fault_fallback"] for r in rows if r["vm"]["thp_fault_fallback"]}
    if fb:
        stop.append(f"thp_fault_fallback が 0 でない本がある: {fb}")
    print()
    print("### 本ごとのあとで、新しい基準で走れたか（走る前の判定は 2 MiB 以上の空き。キャッシュは落としていない）")
    print()
    for r in rows:
        a = r["after_big"]
        g = "走れる" if a["0"] >= new else "**走れない**"
        t = "走れる" if a["total"] >= new else "**走れない**"
        print(f"- {r['label']} のあと: ノード0 {a['0']:.2f} GiB（門番の判定） → {g} / "
              f"両ノードの合計 {a['total']:.2f} GiB（tools/run.sh の判定） → {t}")  # fmt: skip
    print()
    if stop:
        print("=> 止める: " + "; ".join(stop))
    else:
        print(f"=> 止める条件に掛からない: 新しい基準は {new} GiB")
    return 1 if stop else 0


if __name__ == "__main__":
    sys.exit(main())
