#!/usr/bin/python3
"""ベンチの入力を #34 本走の dat/ から抜き出す (実験 perf_34。記録試行ではない)。

    python3 experiments/perf_34/sample.py <#34 本走の dat/> <出力先ディレクトリ> \
        > experiments/perf_34/logs/sample.txt

dat/ は読むだけ (パスを外から渡し, 中へ cd しない)。固定シードで, 種類ごとに一様に
262,144 局面を抜く (抜いた順は dat/ のファイル名の順と, ファイルの中の順。
本物の展開の並びではない)。
- sample_fwd.bin: F1 の入力と同じ母集団。到達可能な全局面 (213 ファイル全部)。
  F1 は全局面を1回ずつ展開する
- sample_unmove.bin: U_loop のフロンティアと同じ母集団。決まった局面のうち, キャッチ局面
  (全探索の側の win001te_000〜028) と引き分け (unknown*) を除いたもの。
  U_loop はこれを1回ずつ展開する
"""

from __future__ import annotations

import hashlib
import pathlib
import random
import sys
from array import array

SEED = 20261008
K = 262_144
FORWARD_WIN001 = 29


def is_catch(name: str) -> bool:
    return name.startswith("win001te_") and int(name[9:12]) < FORWARD_WIN001


def pick(files: list[pathlib.Path], rng: random.Random) -> array:
    sizes = [p.stat().st_size // 8 for p in files]
    total = sum(sizes)
    want = sorted(rng.sample(range(total), K))
    out = array("Q")
    base = 0
    j = 0
    for p, n in zip(files, sizes, strict=True):
        if j < len(want) and want[j] < base + n:
            a = array("Q")
            a.frombytes(p.read_bytes())
            while j < len(want) and want[j] < base + n:
                out.append(a[want[j] - base])
                j += 1
        base += n
    print(f"  母集団 {total:,} 局面 ({len(files)} ファイル) から {len(out):,} 局面")
    return out


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    dat, dst = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
    dst.mkdir(parents=True, exist_ok=True)
    files = sorted(dat.iterdir(), key=lambda p: p.name)
    sets = {
        "fwd": files,
        "unmove": [p for p in files if not is_catch(p.name) and not p.name.startswith("unknown")],
    }
    rng = random.Random(SEED)
    print(f"シード {SEED}, 1組 {K:,} 局面")
    for name, fs in sets.items():
        print(f"sample_{name}.bin:")
        a = pick(fs, rng)
        raw = a.tobytes()
        (dst / f"sample_{name}.bin").write_bytes(raw)
        print(f"  sha256 {hashlib.sha256(raw).hexdigest()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
