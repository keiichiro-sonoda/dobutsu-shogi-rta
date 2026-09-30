#!/usr/bin/python3
"""2腕の .so で, どの関数の番地がどれだけずれたかを出す (門番 #27。記録試行ではない)。

    python3 experiments/gate_27_no_interposition/symbols.py <old の .so> <new の .so>

`nm --defined-only -S` のコードの記号 (T / t) を並べ, 番地の差 (new − old) と大きさを表にする。
.so は門番の本が作ったもの (runs/exp_g27_<ラベル>/animal_shogi.so) を渡す。
build_arm.sh が進行ログに出す sha256 と同じものであることを先頭に書く。

#27 は C を変えないが, normalBoard() などがインライン展開されて関数の大きさが変わり,
後ろの関数がずれる。F1・P2 の差にはこのずれの効果も混ざりうる (分けられない) ので,
その材料として残す。呼び出しの変化は calls.py。
関数の先頭の番地を 64 で割った余り (キャッシュ線の中の位置) も並べる。
大きさと余りは, 変わったものだけ `old → new` と書く。
"""

from __future__ import annotations

import hashlib
import pathlib
import subprocess
import sys


def symbols(so: pathlib.Path) -> dict[str, tuple[int, int]]:
    out = subprocess.run(
        ["nm", "--defined-only", "-S", str(so)], capture_output=True, text=True, check=True
    ).stdout
    table: dict[str, tuple[int, int]] = {}
    for line in out.splitlines():
        parts = line.split()
        # 名前.localalias は -fno-semantic-interposition が直接の呼び出しのために作る別名
        # (本体と同じ番地)。関数としては本体の行で足りるので除く
        if len(parts) == 4 and parts[2] in ("T", "t") and not parts[3].endswith(".localalias"):
            table[parts[3]] = (int(parts[0], 16), int(parts[1], 16))
    return table


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    old_so, new_so = pathlib.Path(argv[1]), pathlib.Path(argv[2])
    for arm, so in (("old", old_so), ("new", new_so)):
        print(f"- `{arm}`: so sha256 {hashlib.sha256(so.read_bytes()).hexdigest()[:12]}")
    old, new = symbols(old_so), symbols(new_so)
    print()
    print("| 関数 | `old` 番地 | `new` 番地 | ずれ（バイト） | 大きさ | mod 64 |")
    print("|---|---|---|---|---|---|")
    for name in sorted(set(old) | set(new), key=lambda n: old.get(n, new.get(n, (0, 0)))[0]):
        if name not in old or name not in new:
            print(f"| `{name}` | 片方にしか無い | | | | |")
            continue
        (a, sa), (b, sb) = old[name], new[name]
        size = f"{sa}" if sa == sb else f"{sa} → {sb}"
        mod = f"{a % 64}" if a % 64 == b % 64 else f"{a % 64} → {b % 64}"
        print(f"| `{name}` | 0x{a:x} | 0x{b:x} | {b - a:+d} | {size} | {mod} |")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
