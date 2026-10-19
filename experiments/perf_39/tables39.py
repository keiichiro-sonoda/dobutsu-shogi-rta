"""ロードの命令が読む配列を決める (実験 perf_39。記録試行ではない)。attribute.py が使う。

experiments/rank_fast/tables.py の table_of_load (命令の側から, その命令が読む .so の静的な表を決める) を広げたもの。
後退解析の配列 g_dtm・g_prep は巨大ページに取った配列で, .so の中にはポインタ (記号 g_dtm・g_prep) だけがある。
読みの命令は「mov g_dtm(%rip),%r12」でポインタを読んでから「cmpb $0xff,(%r12,%rdi,1)」のように引くので,
rank_fast の tables.py では「?」になる。そこで3段で決める:

  1. rank_fast の table_of_load。静的な表 (g_rank_half など) が決まればその名前
  2. 1 で「?」なら, ベースのレジスタをたどって「mov <記号>(%rip),%reg」(ポインタの読み) に当たれば「*<記号>」
     (ポインタの指す先の配列)。ベースが %rsp なら「スタック」
  3. それでも決まらなければ, その命令の一番内側のソース行の文で添字を引いている配列 (「g_xxx[」と「frontier[」) が
     ちょうど1つなら「<名前>（行から）」(g_dtm・g_prep は「*」を付ける)。0 か2つ以上なら「?」
"""

from __future__ import annotations

import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "perf_branch_34"))
sys.path.insert(0, str(HERE.parent / "rank_fast"))
from branches import Disasm  # noqa: E402
from tables import MEM, NOWRITE, SYM, dest_of, func_start, reg64, table_of_load  # noqa: E402

# 行の文で決める配列 (3段目)。ポインタで持つ巨大ページの配列には「*」を付ける
INDEXED = re.compile(r"\b(g_\w+|frontier)\[")
POINTERS = {"g_dtm", "g_prep", "g_seen", "g_draws"}


def trace_ptr(d: Disasm, a: int, reg: str, depth: int = 0) -> str:
    """番地 a より前で reg に最後に書いた命令をたどり, ポインタの読みなら「*記号」。"""
    if reg == "rsp":
        return "スタック"
    if depth > 8:
        return "?"
    lo = func_start(d, a)
    i = d.addrs.index(a) - 1
    while i >= 0 and d.addrs[i] >= lo:
        b = d.addrs[i]
        mn, args = d.insn[b]
        if not NOWRITE.match(mn) and dest_of(args) == reg:
            body = args.split("#", 1)[0].strip()
            src = body.rsplit(",", 1)[0].strip()
            m = SYM.search(args)
            if mn == "mov" and "(%rip)" in src and m:
                return "*" + m.group(1)
            if mn == "mov" and src.startswith("%"):
                return trace_ptr(d, b, reg64(src), depth + 1)
            if mn.startswith("lea"):
                mm = MEM.search(body)
                if mm and mm.group(2) and "(%rip)" not in body:
                    return trace_ptr(d, b, reg64(mm.group(2)), depth + 1)
            return "?"
        i -= 1
    return "?"


def array_of_load(d: Disasm, a: int, line_text: str) -> str:
    """番地 a のロードの命令が読む配列。決められなければ「?」, メモリを読まない命令なら「-」。"""
    t = table_of_load(d, a)
    if t != "?":
        return t
    if a in d.insn:
        mm = MEM.search(d.insn[a][1].split("#", 1)[0])
        if mm and mm.group(2):
            t = trace_ptr(d, a, reg64(mm.group(2)))
            if t != "?":
                return t
    names = set(INDEXED.findall(line_text))
    if len(names) == 1:
        (n,) = names
        return ("*" if n in POINTERS else "") + n + "（行から）"
    return "?"
