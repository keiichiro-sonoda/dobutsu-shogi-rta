#!/usr/bin/python3
"""記録 #21 の全探索が中間ファイルに書いた量を、forward.tsv の件数から数え直す (門番 #22)。

    python3 experiments/gate_22_in_memory/io_volume.py

#21 はファイルの大きさを記録していないので、ラウンドごとの件数 (n_in・n_uk・n_new_post) から
ファイルの状態をなぞって数える。
- unexplored###.bin: 先頭のファイルを読み (F0)、末尾のファイルを読み直して継ぎ足して書く (F5)
- unknown###.bin: 末尾のファイルを読み直して継ぎ足して書く (F2)

どちらも、末尾以外のファイルは BOARD_NUM_MAX ちょうどで、末尾だけが半端になる。
⚠️ 先頭のファイルの大きさが min(BOARD_NUM_MAX, 待ち行列の長さ) であることを全ラウンドで
   確かめながら数える (chunk 腕の定義が #21 のラウンド分けと同じになることの検算も兼ねる)。
"""

from __future__ import annotations

import csv
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
FORWARD = ROOT / "results" / "21_hugepages" / "forward.tsv"
M = 5_000_000
GIB = 2**30


def main() -> int:
    with FORWARD.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    queue, u = 1, 0
    read_f0 = read_f5 = read_f2 = write_f5 = write_f2 = 0
    for row in rows:
        n, uk, new = int(row["n_in"]), int(row["n_uk"]), int(row["n_new_post"])
        if n != min(M, queue):
            raise SystemExit(f"ラウンド {row['round']}: n_in {n} ≠ min(M, 待ち行列 {queue})")
        read_f0 += n
        tail = 0 if u == 0 else (u % M or M)
        read_f2 += tail
        write_f2 += tail + uk
        u += uk
        rest = queue - n
        if new == 0:
            queue = rest
            continue
        tail = 0 if rest == 0 else (rest % M or M)
        read_f5 += tail
        write_f5 += tail + new
        queue = rest + new
    print(f"{len(rows)} ラウンドとも n_in ＝ min({M:,}, 待ち行列の長さ)")
    print(f"書いた量: F2 {write_f2 * 8 / GIB:.2f} GiB ＋ F5 {write_f5 * 8 / GIB:.2f} GiB "
          f"＝ {(write_f2 + write_f5) * 8 / GIB:.2f} GiB")  # fmt: skip
    print(f"読んだ量: F0 {read_f0 * 8 / GIB:.2f} GiB、F2 の読み直し {read_f2 * 8 / GIB:.2f} GiB、"
          f"F5 の読み直し {read_f5 * 8 / GIB:.2f} GiB")  # fmt: skip
    print(f"全探索の未知 (P0 が読み戻していた) {u * 8 / GIB:.2f} GiB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
