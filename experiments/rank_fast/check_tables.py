#!/usr/bin/python3
"""tables.py の「ロードの命令 → 読む表」の決め方を, perf mem の本物のデータの番地と照らす
(実験 rank_fast。記録試行ではない)。

    perf record -d -e cpu/mem-loads,ldlat=8/P -- <rankOf だけのベンチ> ...
    perf script -F ip,sym,symoff,dso,addr | python3 check_tables.py <rank.so> > logs/check_tables.txt

mem-loads (読み込み遅延が 8 サイクル以上のロードの標本) はデータの番地が取れる。ただしこの事象でも,
一部の標本の番地は 0xfeb800xx のような .so の外の値になる (mem_load_uops_retired と同じ形)。
標本ごとに, 番地を .so の表の記号に寄せ (attribute.py の data_symbols。.so を読み込んだ先頭は
命令の番地 − リンク時の番地), 命令ごとに .so の表に当たった標本の記号の内訳を出して,
静的な決め方 (tables.table_of_load) と比べる。.so の表に当たった標本が1つ以上ある命令で,
一番多い記号が静的に決めた記号と違ったら食い違い (終了コード 1)。
.so の表に当たった標本が無い命令 (スタックや入力の列を読む命令) は, 静的にも表に決まらない (「?」) ことを見る。
メモリを読まない命令 (静的に「-」。mem-loads は pp でないので, 標本が隣の命令に付くことがある) は判定しない。
"""

from __future__ import annotations

import pathlib
import re
import sys
from collections import Counter, defaultdict

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "perf_branch_34"))
from attribute import data_symbols, table_of  # noqa: E402
from branches import disasm, resolve  # noqa: E402
from tables import table_of_load  # noqa: E402

LINE = re.compile(r"^\s*([0-9a-f]+)\s+([0-9a-f]+)\s+(\S+)\s+\((.*)\)\s*$")


def main(argv: list[str]) -> int:
    so = argv[1]
    d = disasm(so)
    starts, ends = data_symbols(so)
    seen: dict[int, Counter[str]] = defaultdict(Counter)
    for line in sys.stdin:
        m = LINE.match(line)
        if not m or not m.group(4).endswith("rank.so"):
            continue
        daddr, ip, symoff = int(m.group(1), 16), int(m.group(2), 16), m.group(3)
        a = resolve(d, symoff)
        if a is None:
            continue
        seen[a][table_of(starts, ends, daddr - (ip - a))] += 1
    bad = 0
    print("番地\t命令\t.so の表に当たった標本の内訳\t.so の外の標本\t静的に決めた記号\t一致")
    for a in sorted(seen):
        inside = Counter({k: v for k, v in seen[a].items() if k != "-"})
        static = table_of_load(d, a)
        if static == "-":
            ok = True
        elif inside:
            ok = inside.most_common(1)[0][0] == static
        else:
            ok = static in ("?", "-")
        bad += 0 if ok else 1
        mn, args = d.insn[a]
        mix = " ".join(f"{k}:{v}" for k, v in inside.most_common()) or "-"
        mark = "判定しない" if static == "-" else "○" if ok else "×"
        print(f"{a:x}\t{mn} {args.split('#')[0].strip()}\t{mix}\t{seen[a]['-']}\t{static}\t{mark}")
    print(f"# 命令 {len(seen)} / 食い違い {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
