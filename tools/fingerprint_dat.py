#!/usr/bin/env python3
"""完全解析の成果物 (dat/) の指紋を取り、2つの実行が同じ答えを出したか照合する。

    python3 tools/fingerprint_dat.py <dat>            指紋を出力
    python3 tools/fingerprint_dat.py <dat> <dat2>     2つを照合 (終了コード 0 = 一致)

`tools/verify_log.py` は手数別の「局面数」しか見ない。実装を書き換えたとき、
数が合っていて中身が違う、という壊れ方は検出できない。ここでは
**どの局面がどの手数か**まで照合する。

指紋は深さごとの (件数, 総和 mod 2^64, XOR)。3つとも要素の順序に依存しないので、
チャンクの分かれ方が違っても同じ値になる。同じ答えでも win003te_000 と _001 の
分割は集合の pop 順で変わるため、バイト比較や件数比較では足りない。
"""

from __future__ import annotations

import pathlib
import pickle
import re
import sys

MASK64 = (1 << 64) - 1

# dat/ に並ぶファイル名。深さとチャンク番号を持つ
WIN_RE = re.compile(r"^win(\d+)te_(\d+)\.pickle$")
LOSE_RE = re.compile(r"^lose(\d+)te_(\d+)\.pickle$")
UNKNOWN_RE = re.compile(r"^unknown(\d+)\.pickle$")

# (深さ, 勝敗) -> (件数, 総和, XOR)。引き分けは深さを持たないので None を使う
Key = tuple[int | None, str]
Print = tuple[int, int, int]


def _load(path: pathlib.Path) -> set[int]:
    with path.open("rb") as f:
        obj = pickle.load(f)
    return set(obj)


def fingerprint(dat: pathlib.Path) -> dict[Key, Print]:
    """dat/ を走査して深さごとの指紋を返す。

    中間ファイル (_next / _next_win) は答えではないので無視する。
    最後まで確定しなかった unknown が引き分け局面。
    """
    acc: dict[Key, list[int]] = {}

    for path in sorted(dat.iterdir()):
        name = path.name
        if name.endswith("_next.pickle") or name.endswith("_next_win.pickle"):
            continue

        if m := WIN_RE.match(name):
            key: Key = (int(m.group(1)), "win")
        elif m := LOSE_RE.match(name):
            key = (int(m.group(1)), "lose")
        elif UNKNOWN_RE.match(name):
            key = (None, "draw")
        else:
            continue

        cell = acc.setdefault(key, [0, 0, 0])
        for v in _load(path):
            cell[0] += 1
            cell[1] = (cell[1] + v) & MASK64
            cell[2] ^= v

    return {k: (c, s, x) for k, (c, s, x) in acc.items()}


def _sort_key(key: Key) -> tuple[int, int, str]:
    depth, result = key
    # 引き分けは最後に置く
    return (1, 0, result) if depth is None else (0, depth, result)


def render(fp: dict[Key, Print]) -> str:
    lines = [f"{'depth':>6} {'result':<6} {'count':>12} {'sum(mod 2^64)':>18} {'xor':>18}"]
    total = 0
    for key in sorted(fp, key=_sort_key):
        depth, result = key
        count, s, x = fp[key]
        total += count
        d = "-" if depth is None else str(depth)
        lines.append(f"{d:>6} {result:<6} {count:>12,} {s:>#18x} {x:>#18x}")
    lines.append(f"{'':>6} {'合計':<6} {total:>12,}")
    return "\n".join(lines)


def compare(a: dict[Key, Print], b: dict[Key, Print]) -> list[str]:
    """不一致の説明を返す。空なら一致。"""
    bad = []
    for key in sorted(set(a) | set(b), key=_sort_key):
        depth, result = key
        d = "-" if depth is None else str(depth)
        if key not in a:
            bad.append(f"  depth={d:>3} {result:<5} 片方 (1つ目) に無い")
        elif key not in b:
            bad.append(f"  depth={d:>3} {result:<5} 片方 (2つ目) に無い")
        elif a[key] != b[key]:
            ca, sa, xa = a[key]
            cb, sb, xb = b[key]
            diff = []
            if ca != cb:
                diff.append(f"件数 {ca:,} != {cb:,}")
            if sa != sb:
                diff.append(f"総和 {sa:#x} != {sb:#x}")
            if xa != xb:
                diff.append(f"XOR {xa:#x} != {xb:#x}")
            bad.append(f"  depth={d:>3} {result:<5} " + " / ".join(diff))
    return bad


def main(argv: list[str]) -> int:
    if not 2 <= len(argv) <= 3:
        print(__doc__, file=sys.stderr)
        return 2

    first = pathlib.Path(argv[1])
    if not first.is_dir():
        print(f"ディレクトリが無い: {first}", file=sys.stderr)
        return 2

    fp_a = fingerprint(first)
    if len(argv) == 2:
        print(render(fp_a))
        return 0

    second = pathlib.Path(argv[2])
    if not second.is_dir():
        print(f"ディレクトリが無い: {second}", file=sys.stderr)
        return 2

    fp_b = fingerprint(second)
    bad = compare(fp_a, fp_b)
    if bad:
        print(f"FAIL: {len(bad)} 項目が不一致")
        print("\n".join(bad))
        return 1

    total = sum(c for c, _, _ in fp_a.values())
    print(f"PASS: {len(fp_a)} 項目すべて一致")
    print(f"  照合した局面数の合計: {total:,}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
