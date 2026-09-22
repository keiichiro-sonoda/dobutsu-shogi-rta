#!/usr/bin/env python3
"""pickle の往復が set の反復順を保つかどうかを、条件を変えて確かめる。

CLAUDE.md と記録 #16 のノートは「pickle の往復は set の反復順を保たない」と
書いているが、これは**集合の疎密に依存する**。`range(1_000_000)` のような密な
連番集合では、内部の開番地法ハッシュ表の配置が pickle の生成順と読み込み順で
偶然そろい、まったく動かない (0.0%)。盤面番号のように疎な整数の集合では、
配置が変わって大半の位置が動く。

盤面はどうぶつしょうぎの局面を詰めた整数で、INITIAL_BOARD の bit_length() は
48。ここでは 48 ビットの一様乱数で近似し、実際の後退解析の入力規模
(BOARD_NUM_MAX = 5,000,000) に対して 1,000,000 要素で確かめる。

固定シードで決定的に再現できる。
"""

from __future__ import annotations

import pickle
import random


def moved_fraction(s: set[int]) -> tuple[int, int]:
    back = pickle.loads(pickle.dumps(s))
    moved = sum(1 for a, b in zip(s, back, strict=True) if a != b)
    return moved, len(s)


def main() -> None:
    random.seed(20260922)
    dense = set(range(1_000_000))
    sparse_48bit = {random.getrandbits(48) for _ in range(1_000_000)}
    print(f"dense 集合の要素数: {len(dense):,}")
    print(f"sparse 48bit 集合の要素数: {len(sparse_48bit):,}")
    print()
    for label, s in (("range(1_000_000) (密)", dense), ("48bit 一様乱数 (疎, 盤面に近い)", sparse_48bit)):
        moved, n = moved_fraction(s)
        print(f"{label}: 往復で反復順が同じ = {moved == 0} / 位置が動いた要素 {moved:,} ({moved / n * 100:.1f}%)")


if __name__ == "__main__":
    main()
