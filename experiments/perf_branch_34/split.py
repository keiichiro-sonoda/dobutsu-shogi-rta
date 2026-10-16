#!/usr/bin/python3
"""F1 のブロックを, キャッチ局面だけ / それ以外だけに分ける (実験 perf_branch_34)。

    python3 split.py <bench.so> <ブロックのディレクトリ> <出力先> > logs/split.txt

記録試行ではない. ブロックは experiments/perf_34 の dump の本が書き出した f1_*.bin
(F1 の各ラウンドの入力の真ん中の連続した 4,096 局面. 並びは本物のまま). 各局面を生成器
(nextBoardInvNormalNC。bench.so は impl/34_unmove の animal_shogi.c を取り込んだもの) に通し,
戻り値 0 (キャッチ局面) か, それ以外かで2つのファイルに分ける.
並びは保つ. 出力先に catch/f1_*.bin と other/f1_*.bin と, 件数の表 split_index.tsv を書く.
"""

from __future__ import annotations

import ctypes
import pathlib
import sys
from array import array


def main() -> int:
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    lib = ctypes.CDLL(sys.argv[1])
    gen = lib.nextBoardInvNormalNC
    gen.restype = ctypes.c_int
    gen.argtypes = [ctypes.c_uint64, ctypes.POINTER(ctypes.c_uint64), ctypes.POINTER(ctypes.c_int)]
    src, dst = pathlib.Path(sys.argv[2]), pathlib.Path(sys.argv[3])
    (dst / "catch").mkdir(parents=True, exist_ok=True)
    (dst / "other").mkdir(parents=True, exist_ok=True)
    nbs = (ctypes.c_uint64 * 64)()
    nc = ctypes.c_int()
    rows = []
    for p in sorted(src.glob("f1_*.bin")):
        a = array("Q")
        a.frombytes(p.read_bytes())
        c, o = array("Q"), array("Q")
        for b in a:
            (c if gen(b, nbs, ctypes.byref(nc)) == 0 else o).append(b)
        (dst / "catch" / p.name).write_bytes(c.tobytes())
        (dst / "other" / p.name).write_bytes(o.tobytes())
        rows.append(f"{p.stem}\t{len(a)}\t{len(c)}\t{len(o)}")
    (dst / "split_index.tsv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    n = sum(int(r.split("\t")[1]) for r in rows)
    k = sum(int(r.split("\t")[2]) for r in rows)
    print(f"ブロック {len(rows)} 個 / 局面 {n} / キャッチ局面 {k} ({k / n:.1%})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
