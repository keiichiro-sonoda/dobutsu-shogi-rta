#!/usr/bin/python3
"""手数ごとにファイルを束ねて, #33 と #34 の集合を比べる (記録試行ではない)。

    python3 experiments/sorted_compare_34/depth_compare.py <#33 の dat/> <#34 の dat/> \
        > experiments/sorted_compare_34/logs/depth_compare.tsv

compare.py (ファイルごと) で一致しなかったファイルは, どれも1つの手数が2ファイル以上に分かれている
ところだった。成果物は手数ごとに BOARD_NUM_MAX 件ずつに区切って書くので, 並びが変わると, 同じ手数の
中で局面がファイルの切れ目をまたいで入れ替わりうる。そこで, 名前の接頭辞 (lose002te など) が同じ
ファイルを番号順に連結し, 並べ替えて sha256 を比べる。win001te は全探索の側 (000〜028) と
後退解析の側 (029〜) を分けて束ねる。全探索の側の win001te (29 ファイル, 1.45 億件) は,
ファイルごとに元の並びのままバイト一致しているので (logs/compare.tsv) 束ねずに省く
(1プロセスで十数 GB を使うため)。
並べ替えた sha256 が一致しない束があれば, 片方にだけある局面の数を標準エラーに出し, 終了コード 1。
"""

from __future__ import annotations

import pathlib
import re
import sys
from array import array
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor

from compare import digest, forward_side, load


def group(name: str) -> str:
    prefix = re.sub(r"_?\d+\.bin$", "", name)
    if prefix == "win001te":
        return prefix + ("(全探索)" if forward_side(name) else "(後退解析)")
    return prefix


def one(args: tuple[str, list[str], str, str]) -> dict[str, object]:
    key, names, d33, d34 = args
    s33: list[int] = []
    s34: list[int] = []
    for n in names:
        s33.extend(load(pathlib.Path(d33) / n))
        s34.extend(load(pathlib.Path(d34) / n))
    n33, dup33, h33, l33 = digest(array("Q", s33))
    n34, dup34, h34, l34 = digest(array("Q", s34))
    out: dict[str, object] = {
        "group": key,
        "files": len(names),
        "n33": n33,
        "n34": n34,
        "dup33": dup33,
        "dup34": dup34,
        "sorted_same": h33 == h34,
        "sorted_sha256_33": h33,
        "sorted_sha256_34": h34,
    }
    if h33 != h34:
        a, b = set(l33), set(l34)
        out["only33"] = len(a - b)
        out["only34"] = len(b - a)
    return out


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    d33, d34 = sys.argv[1], sys.argv[2]
    groups: dict[str, list[str]] = defaultdict(list)
    for p in sorted(pathlib.Path(d33).iterdir()):
        groups[group(p.name)].append(p.name)
    skipped = "win001te(全探索)"
    jobs = [(k, v, d33, d34) for k, v in groups.items() if k != skipped]
    jobs.sort(key=lambda j: -len(j[1]))
    with ProcessPoolExecutor(max_workers=8) as ex:
        rows = list(ex.map(one, jobs))
    rows.sort(key=lambda r: str(r["group"]))
    cols = (
        "group",
        "files",
        "n33",
        "n34",
        "dup33",
        "dup34",
        "sorted_same",
        "sorted_sha256_33",
        "sorted_sha256_34",
    )
    print("\t".join(cols))
    for r in rows:
        print("\t".join(str(r[c]) for c in cols))
    print(f"# {skipped} ({len(groups[skipped])} ファイル) は省いた (ファイルごとにバイト一致)")
    bad = [r for r in rows if not r["sorted_same"]]
    for r in bad:
        sys.stderr.write(
            f"不一致 {r['group']}: #33 だけ {r['only33']} 個 / #34 だけ {r['only34']} 個\n"
        )
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
