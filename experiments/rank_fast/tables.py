"""ロードの命令が読む表を, 逆アセンブルから決める (実験 rank_fast。記録試行ではない)。

attribute.py と check_tables.py が使う。

この CPU (Broadwell) と perf 6.8 では, mem_load_uops_retired.* の PEBS の標本のデータの番地 (perf record -d)
が 0xfeb800xx のような値ばかりで, .so の表のどこにも当たらない (本番の前の試しで見た. README)。
標本の命令の番地は正しい (pp) ので, その命令がどの表を読むかを命令の側から決める:
  - メモリの引数が disp(%rip) なら, objdump の注記 (# 番地 <記号>) の記号
  - disp(%base, ...) なら, 同じ関数の中で, その命令より前 (番地の小さい側) にある最後の %base への書き込みを探す。
    それが lea disp(%rip) なら注記の記号, lea (%s, ...) か mov %s なら %s を同じように (その書き込みの位置から) たどる。
    ほかの命令 (足し算・ロードなど) で書いていたら決めない (「?」)
ループの中では「前」は番地の順で見る (ループの頭より前で一度だけ置いた表の先頭は, 頭より前にある)。
正しく決まるかは, check_tables.py が perf mem (データの番地が取れる読み込み遅延の事象) と照らす。
"""

from __future__ import annotations

import re
from bisect import bisect_right

from branches import Disasm

MEM = re.compile(r"(-?0x[0-9a-f]+|-?\d+)?\((%\w+)?(?:,(%\w+))?(?:,\d)?\)")
SYM = re.compile(r"#\s*[0-9a-f]+\s*<([^>+]+)(?:\+0x[0-9a-f]+)?>")
NOWRITE = re.compile(r"^(cmp|test|bt|prefetch|push|j|call|ret|nop|ucomi|comi)")
ALIAS = {}
for r in ("ax", "bx", "cx", "dx", "si", "di", "bp", "sp"):
    for a in (f"e{r}", r, f"{r[0]}l" if r[1] == "x" else f"{r}l"):
        ALIAS[a] = f"r{r}"
for n in range(8, 16):
    for suf in ("d", "w", "b"):
        ALIAS[f"r{n}{suf}"] = f"r{n}"


def reg64(r: str) -> str:
    r = r.lstrip("%")
    return ALIAS.get(r, r)


def dest_of(args: str) -> str | None:
    """最後の引数がレジスタなら, その 64 ビットの名前 (書き込み先)。"""
    body = args.split("#", 1)[0].strip()
    if not body:
        return None
    last = body.rsplit(",", 1)[-1].strip()
    if last.startswith("%") and "(" not in last:
        return reg64(last)
    return None


def func_start(d: Disasm, a: int) -> int:
    starts = sorted(d.funcs.values())
    i = bisect_right(starts, a) - 1
    return starts[i] if i >= 0 else 0


def table_of_load(d: Disasm, a: int) -> str:
    """番地 a のロードの命令が読む表の記号。決められなければ「?」, メモリを読まない命令なら「-」。"""
    if a not in d.insn:
        return "?"
    mn, args = d.insn[a]
    if mn.startswith("lea") or mn.startswith("prefetch"):
        return "-"
    m = SYM.search(args)
    if "(%rip)" in args and m:
        return m.group(1)
    mm = MEM.search(args.split("#", 1)[0])
    if not mm or not mm.group(2):
        return "-"
    return trace(d, a, reg64(mm.group(2)), 0)


def trace(d: Disasm, a: int, reg: str, depth: int) -> str:
    if depth > 8:
        return "?"
    lo = func_start(d, a)
    i = d.addrs.index(a) - 1
    while i >= 0 and d.addrs[i] >= lo:
        b = d.addrs[i]
        mn, args = d.insn[b]
        if not NOWRITE.match(mn) and dest_of(args) == reg:
            body = args.split("#", 1)[0]
            if mn.startswith("lea"):
                m = SYM.search(args)
                if "(%rip)" in body and m:
                    return m.group(1)
                mm = MEM.search(body)
                if mm and mm.group(2):
                    return trace(d, b, reg64(mm.group(2)), depth + 1)
                return "?"
            if mn == "mov" and body.strip().startswith("%"):
                return trace(d, b, reg64(body.split(",")[0].strip()), depth + 1)
            return "?"
        i -= 1
    return "?"
