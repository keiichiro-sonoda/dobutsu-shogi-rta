#!/usr/bin/env python3
"""forward_profile.tsv と forward_profile_summary.tsv から報告の表を作る.

    python3 experiments/forward_profile/report.py <kaiseki_log ディレクトリ>

区分の秒数は float のまま足す (切り捨てない). 表示だけ小数2桁.
"""

from __future__ import annotations

import csv
import pathlib
import sys

F = ("F0", "F1", "F2", "F3", "S", "F4", "F5")
NAMES = {
    "F0": "F0 未探索チャンクの読み込み",
    "F1": "F1 展開 (pop・FFI・振り分け・+= nbl)",
    "F2": "F2 未知盤面の書き出し (updateUKFile)",
    "F3": "F3 集合化 (set)",
    "S": "S  初回の buildSeenBoards",
    "F4": "F4 重複排除 (-= seen / |= new)",
    "F5": "F5 未探索チャンクの書き出し",
    "F6": "F6 終端の書き出し (writeWLFilesForDepth ×2)",
    "release_wl": "解放: 終端リスト (catch_wins / try_loses)",
    "release_seen": "解放: seen_boards",
}
GIB = 2**30


def load(d: pathlib.Path) -> tuple[list[dict], dict]:
    rows = list(csv.DictReader((d / "forward_profile.tsv").open(encoding="utf-8"), delimiter="\t"))
    summary = {}
    for line in (d / "forward_profile_summary.tsv").read_text(encoding="utf-8").splitlines():
        k, v = line.split("\t")
        summary[k] = float(v) if "." in v else int(v)
    return rows, summary


def breakdown(rows: list[dict], s: dict) -> None:
    total = s["forward_total"]
    n = s["rounds"]
    print(f"全探索の実時間 {total:.2f} 秒 / {n} ラウンド\n")
    print(f"| 区分 | 秒 | 全探索比 | ラウンドあたり平均 |")
    print(f"|---|---|---|---|")
    acc = 0.0
    for k in F:
        v = s[k]
        acc += v
        per = f"{v / n:.2f}" if k != "S" else "(初回のみ)"
        print(f"| {NAMES[k]} | {v:,.2f} | {v / total * 100:.1f}% | {per} |")
    for k in ("F6", "release_wl", "release_seen"):
        v = s[k]
        acc += v
        print(f"| {NAMES[k]} | {v:,.2f} | {v / total * 100:.1f}% | (最後に1回) |")
    resid = s["residual_total"]
    print(f"| **残差** (区分に入れていない処理・端数) | **{resid:,.2f}** | **{resid / total * 100:.1f}%** | {s['residual_in_rounds'] / n:.2f} (ラウンド内ぶん) |")
    print(f"| **合計** | **{acc + resid:,.2f}** | 100% | |")
    assert abs(acc + resid - total) < 1e-3, "合計が実時間と合わない"
    print()
    print(f"残差の内訳: ラウンド内 {s['residual_in_rounds']:.2f} 秒 (区分の隙間: ファイル探索・ログ・catch_wins += 等) "
          f"/ ラウンド外 {resid - s['residual_in_rounds']:.2f} 秒 (searchAll のループ・行の書き出し・端数)")


def trend(rows: list[dict]) -> None:
    n = len(rows)
    thirds = [rows[: n // 3], rows[n // 3 : 2 * n // 3], rows[2 * n // 3 :]]
    b1, b2 = n // 3, 2 * n // 3
    print(f"\n### ラウンドごとの推移 (序盤 1〜{b1} / 中盤 {b1 + 1}〜{b2} / 終盤 {b2 + 1}〜{n}, 各区分の1ラウンド平均・秒)")
    print("(⚠️ 3 で割れない本数のときは境界を明記して読むこと)\n")
    print("| 区分 | 序盤 | 中盤 | 終盤 | 終盤/序盤 |")
    print("|---|---|---|---|---|")
    for k in F:
        if k == "S":
            continue
        m = [sum(float(r[k]) for r in t) / len(t) for t in thirds]
        ratio = f"{m[2] / m[0]:.2f}×" if m[0] > 0 else "—"
        print(f"| {k} | {m[0]:.2f} | {m[1]:.2f} | {m[2]:.2f} | {ratio} |")
    m = [sum(float(r["residual"]) for r in t) / len(t) for t in thirds]
    print(f"| 残差 | {m[0]:.2f} | {m[1]:.2f} | {m[2]:.2f} | {m[2] / m[0]:.2f}× |")
    seen = [sum(int(r["n_seen"]) for r in t) / len(t) for t in thirds]
    nin = [sum(int(r["n_in"]) for r in t) / len(t) for t in thirds]
    pre = [sum(int(r["n_new_pre"]) for r in t) / len(t) for t in thirds]
    post = [sum(int(r["n_new_post"]) for r in t) / len(t) for t in thirds]
    print(f"| (参考) n_seen 平均 | {seen[0]:,.0f} | {seen[1]:,.0f} | {seen[2]:,.0f} | |")
    print(f"| (参考) 入力 n_in 平均 | {nin[0]:,.0f} | {nin[1]:,.0f} | {nin[2]:,.0f} | |")
    print(f"| (参考) 生成 (重複排除前 / 後) | {pre[0]:,.0f} / {post[0]:,.0f} | {pre[1]:,.0f} / {post[1]:,.0f} | {pre[2]:,.0f} / {post[2]:,.0f} | |")


def per_item(rows: list[dict]) -> None:
    """件数あたりの単価. 序盤・終盤で比べると「発見済み集合の大きさに比例して伸びる」区分が見える"""
    print("\n### 件数あたりの単価 (µs). F1 は入力1局面あたり, F3 は生成1要素あたり, F4 は生成1要素あたり\n")
    n = len(rows)
    thirds = [rows[: n // 3], rows[n // 3 : 2 * n // 3], rows[2 * n // 3 :]]
    print("| 区分 / 分母 | 序盤 | 中盤 | 終盤 |")
    print("|---|---|---|---|")
    for k, denom, label in (("F1", "n_in", "F1 / 入力局面"), ("F3", "n_new_pre", "F3 / 生成要素"),
                            ("F4", "n_new_pre", "F4 / 生成要素"), ("F2", "n_uk", "F2 / 未知盤面"),
                            ("F5", "n_new_post", "F5 / 重複排除後の要素")):
        u = []
        for t in thirds:
            num = sum(float(r[k]) for r in t)
            den = sum(int(r[denom]) for r in t)
            u.append(num / den * 1e6 if den else 0.0)
        print(f"| {label} | {u[0]:.3f} | {u[1]:.3f} | {u[2]:.3f} |")


def memory(rows: list[dict], s: dict) -> None:
    print("\n### RSS の推移とピーク\n")
    keys = ("start", "F0_begin", "F0", "F1_begin", "F1", "F2_begin", "F2",
            "F3_begin", "F3", "F4_begin", "F4", "F5_begin", "F5")
    peak_hwm, peak_at = 0, None
    prev_hwm = 0
    jumps = []  # (round, boundary, delta)
    for r in rows:
        for k in keys:
            h = int(r["hwm_" + k])
            if h > prev_hwm:
                jumps.append((int(r["round"]), k, h - prev_hwm, h))
                prev_hwm = h
            if h > peak_hwm:
                peak_hwm, peak_at = h, (int(r["round"]), k)
    for k in ("hwm_before_F6", "hwm_after_F6", "hwm_after_release_wl", "hwm_after_release"):
        if s[k] > peak_hwm:
            peak_hwm, peak_at = s[k], (None, k)
    print(f"高水位 (VmHWM) の最大 {peak_hwm / GIB:.2f} GiB. 最後に更新された境界: ラウンド {peak_at[0]} の {peak_at[1]}")
    # ⚠️ 「最大の跳ね」と「最高の水位」は別物. ラウンド内の最高水位とその初出も出す
    # 高水位は単調なので最大値は後ろの行にも並ぶ. 初出 (最初にその値に達した境界) を取る
    in_round_max_val = max(int(r["hwm_" + k]) for r in rows for k in keys)
    in_round_max = next((in_round_max_val, int(r["round"]), k) for r in rows for k in keys
                        if int(r["hwm_" + k]) == in_round_max_val)
    print(f"ラウンド内の高水位の最高 {in_round_max[0] / GIB:.2f} GiB (初出: ラウンド {in_round_max[1]} の {in_round_max[2]})")
    biggest = max(jumps, key=lambda x: x[2]) if jumps else None
    if biggest:
        print(f"最大の跳ね: ラウンド {biggest[0]} の {biggest[1]} で +{biggest[2] / 2**20:,.0f} MiB "
              f"({(biggest[3] - biggest[2]) / GIB:.2f} → {biggest[3] / GIB:.2f} GiB)")
    # ピークを更新した境界のうち, 大きい跳ねの上位
    print("\n高水位が跳ねた境界 (大きい順に 8 つ). 「境界」はその区分の終わり (F1 = 展開の終わり) を意味し,")
    print("_begin は区分の始まり. 跳ねが F3 に付けば集合化の中で, F4 なら重複排除 (集合のリサイズ) の中で立った\n")
    print("| ラウンド | 境界 | 跳ね (MiB) | 高水位 (GiB) |")
    print("|---|---|---|---|")
    for rd, k, d, h in sorted(jumps, key=lambda x: -x[2])[:8]:
        print(f"| {rd} | {k} | {d / 2**20:,.0f} | {h / GIB:.2f} |")
    # 境界ごとに「跳ねを担った回数と合計」
    by = {}
    for rd, k, d, h in jumps:
        by.setdefault(k, [0, 0])
        by[k][0] += 1
        by[k][1] += d
    print("\n| 境界 | 高水位を更新した回数 | 合計 (GiB) |")
    print("|---|---|---|")
    for k, (c, d) in sorted(by.items(), key=lambda x: -x[1][1]):
        print(f"| {k} | {c} | {d / GIB:.2f} |")
    last = rows[-1]
    print(f"\n最終ラウンド後: RSS {int(last['rss_F5']) / GIB:.2f} GiB / F6 前 {s['rss_before_F6'] / GIB:.2f} / F6 後 {s['rss_after_F6'] / GIB:.2f} "
          f"/ 終端リスト解放後 {s['rss_after_release_wl'] / GIB:.2f} / seen_boards 解放後 {s['rss_after_release'] / GIB:.2f} GiB")
    # ラウンド内の典型的な動き (終盤の平均)
    n = len(rows)
    tail = rows[2 * n // 3 :]
    print("\n終盤のラウンド内での RSS の動き (平均, 各境界の rss - ラウンド開始時の rss, GiB):")
    print("| 境界 | " + " | ".join(keys[1:]) + " |")
    print("|---|" + "---|" * (len(keys) - 1))
    deltas = []
    for k in keys[1:]:
        deltas.append(sum((int(r["rss_" + k]) - int(r["rss_start"])) for r in tail) / len(tail) / GIB)
    print("| Δrss | " + " | ".join(f"{d:+.2f}" for d in deltas) + " |")


def sizes(rows: list[dict], s: dict) -> None:
    """ピーク時点の主要オブジェクトの実寸見積もり (CPython の実装から計算)"""
    print("\n### 主要オブジェクトの実寸見積もり (CPython 3.12, 64bit)\n")
    last = rows[-1]
    n_seen = int(last["n_seen"])
    n_wl = int(last["n_catch_total"]) + int(last["n_try_total"])
    # seen_boards の表の大きさを, CPython (Objects/setobject.c) の set_merge (|=) の規則で辿る:
    #   (fill + other.used) * 5 >= mask * 3 なら, (used + other.used) * 2 を超える最小の 2 の冪へ
    #   (|= は常に *2. 要素を1つずつ足すときの *4 規則とは別). 1 スロット 16 B (hash + key ポインタ).
    #   削除は無いので fill == used. 初回の buildSeenBoards() で初期局面 1 個が入った状態から始める
    slots, used, last_resize = 8, 1, None
    for r in rows:
        other = int(r["n_new_post"])
        if (used + other) * 5 >= (slots - 1) * 3:
            want = (used + other) * 2
            ns = 8
            while ns <= want:
                ns <<= 1
            slots, last_resize = ns, (int(r["round"]), ns)
        used += other
    assert used == n_seen, f"|= の件数の合計 {used:,} が n_seen {n_seen:,} と合わない"
    print(f"seen_boards の表は最後にラウンド {last_resize[0]} で {last_resize[1]:,} スロットへリサイズ "
          f"(その境界 F4 で高水位が跳ねているはず. 旧表と新表が同時に在る瞬間がある)\n")
    int_b = 32  # sys.getsizeof(2**59)
    seen_table = slots * 16
    seen_ints = n_seen * int_b
    wl = n_wl * (8 + int_b)  # リストのポインタ + int (pickle 由来で seen_boards とは別物)
    print(f"| 構造 | 件数 | 見積もり | 根拠 |")
    print(f"|---|---|---|---|")
    print(f"| seen_boards の表 | {slots:,} スロット | {seen_table / GIB:.2f} GiB | 16 B × 2^{slots.bit_length() - 1} |")
    print(f"| seen_boards の int | {n_seen:,} | {seen_ints / GIB:.2f} GiB | 32 B × 件数 |")
    print(f"| catch_wins + try_loses | {n_wl:,} | {wl / GIB:.2f} GiB | (8 + 32) B × 件数 |")
    print(f"| **合計 (常駐)** | | **{(seen_table + seen_ints + wl) / GIB:.2f} GiB** | |")
    # ラウンド内の一時物: 生成リスト (pre) と集合化後の set.
    # set(list) は要素を1つずつ足すので規則が違う: 追加後に used*5 >= mask*3 なら
    # (used > 50,000 ? used*2 : used*4) を超える最小の 2 の冪へ. 表の大きさは
    # 重複を除いた要素数 d で決まるが d は記録していない (n_new_post <= d <= n_new_pre) ので上下限で出す
    def add_table(d: int) -> int:
        slots, used = 8, 0
        while used < d:
            need = -(-3 * (slots - 1) // 5)  # ceil(0.6 * mask): ここで次のリサイズが起きる
            if need > d:
                break
            used = need
            want = used * 2 if used > 50000 else used * 4
            ns = 8
            while ns <= want:
                ns <<= 1
            slots = ns
        return slots
    big = max(rows, key=lambda r: int(r["n_new_pre"]))
    pre, post = int(big["n_new_pre"]), int(big["n_new_post"])
    lo, hi = add_table(post), add_table(pre)
    print(f"| 1ラウンドの生成リスト (最大 {pre:,} 要素, ラウンド {big['round']}) | | {pre * 40 / GIB:.2f} GiB | (8 + 32) B × 要素 |")
    print(f"| その集合化 (set) の表 | {lo:,}〜{hi:,} スロット | {lo * 16 / GIB:.2f}〜{hi * 16 / GIB:.2f} GiB | 16 B × 2 の冪 (重複除去後の要素数で決まる) |")
    print(f"\n実測の高水位との比較は本文で行う (常駐 + 一時物 ≒ ピークになるはず)")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    d = pathlib.Path(argv[1])
    rows, s = load(d)
    breakdown(rows, s)
    trend(rows)
    per_item(rows)
    memory(rows, s)
    sizes(rows, s)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
