#!/usr/bin/python3
"""#33 本走と #34 本走の dat/ を, ファイルごとに集合として比べる (記録試行ではない)。

    python3 experiments/sorted_compare_34/compare.py <#33 の dat/> <#34 の dat/> \
        > experiments/sorted_compare_34/logs/compare.tsv

dat/ のファイルは 8 バイトの符号なし整数 (リトルエンディアン) を並べただけでヘッダが無い。
各ファイルを局面の列として読み, 昇順に並べ替えてから sha256 を取る。並べ替えた列が同じなら,
重複の数まで含めてファイルの中身は集合として同じ。元の並びのままのバイト一致も並べる。

どちらの dat/ も読むだけ (開くのは読み取りだけで, 中へ cd しない)。出力は標準出力へ。
並べ替えた sha256 が一致しないファイルがあれば, 片方にだけある局面の数を標準エラーに出し,
終了コード 1 を返す。
"""

from __future__ import annotations

import hashlib
import pathlib
import sys
from array import array
from concurrent.futures import ProcessPoolExecutor

# 全探索の側のファイル (全探索がそのまま書く): lose000te_* と, キャッチ局面を書く win001te_000〜028
FORWARD_WIN001 = 29


def forward_side(name: str) -> bool:
    if name.startswith("lose000te_"):
        return True
    if name.startswith("win001te_"):
        return int(name[len("win001te_") : -len(".bin")]) < FORWARD_WIN001
    return False


def load(path: pathlib.Path) -> array:
    raw = path.read_bytes()
    if len(raw) % 8:
        raise SystemExit(f"{path.name}: 大きさ {len(raw)} が 8 の倍数でない")
    a = array("Q")
    a.frombytes(raw)
    if sys.byteorder != "little":
        a.byteswap()
    return a


def digest(a: array) -> tuple[int, int, str, list[int]]:
    """(件数, 重複の数, 並べ替えた列の sha256, 並べ替えた列)。"""
    s = sorted(a)
    dup = sum(1 for i in range(1, len(s)) if s[i] == s[i - 1])
    b = array("Q", s)
    if sys.byteorder != "little":
        b.byteswap()
    return len(s), dup, hashlib.sha256(b.tobytes()).hexdigest(), s


def one(args: tuple[str, str, str]) -> dict[str, object]:
    name, d33, d34 = args
    p33, p34 = pathlib.Path(d33) / name, pathlib.Path(d34) / name
    raw_same = p33.read_bytes() == p34.read_bytes()
    n33, dup33, h33, s33 = digest(load(p33))
    n34, dup34, h34, s34 = digest(load(p34))
    out: dict[str, object] = {
        "name": name,
        "side": "forward" if forward_side(name) else "retreat",
        "n33": n33,
        "n34": n34,
        "dup33": dup33,
        "dup34": dup34,
        "sorted_sha256_33": h33,
        "sorted_sha256_34": h34,
        "sorted_same": h33 == h34,
        "raw_same": raw_same,
    }
    if h33 != h34:
        a, b = set(s33), set(s34)
        out["only33"] = len(a - b)
        out["only34"] = len(b - a)
    return out


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    d33, d34 = sys.argv[1], sys.argv[2]
    names33 = sorted(p.name for p in pathlib.Path(d33).iterdir())
    names34 = sorted(p.name for p in pathlib.Path(d34).iterdir())
    if names33 != names34:
        sys.stderr.write(
            f"名前の集合が違う: #33 だけ {sorted(set(names33) - set(names34))} / "
            f"#34 だけ {sorted(set(names34) - set(names33))}\n"
        )
        return 1
    # 大きいファイルから先に回して, 最後に1つだけ残る待ちを短くする
    names = sorted(names33, key=lambda n: -(pathlib.Path(d33) / n).stat().st_size)
    with ProcessPoolExecutor(max_workers=8) as ex:
        rows = list(ex.map(one, [(n, d33, d34) for n in names]))
    rows.sort(key=lambda r: str(r["name"]))
    cols = (
        "name",
        "side",
        "n33",
        "n34",
        "dup33",
        "dup34",
        "sorted_same",
        "raw_same",
        "sorted_sha256_33",
        "sorted_sha256_34",
    )
    print("\t".join(cols))
    for r in rows:
        print("\t".join(str(r[c]) for c in cols))
    bad = [r for r in rows if not r["sorted_same"]]
    for r in bad:
        sys.stderr.write(
            f"不一致 {r['name']}: #33 だけ {r['only33']} 個 / #34 だけ {r['only34']} 個\n"
        )
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
