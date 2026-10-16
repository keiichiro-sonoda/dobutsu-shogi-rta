"""分岐の標本を数える道具 (実験 perf_branch_34。記録試行ではない)。

probe/check_attr.py と summary.py が使う。

- disasm(): objdump -d で, 関数ごとの命令の番地と名前を読む (リンク時の番地)
- branch_of(): PEBS の標本の番地を分岐に対応づける. Broadwell の :pp の標本は, 分岐そのものか,
  それと融合した直前の比較 (cmp / test など) の番地に付く (probe で確かめた).
  標本の番地が条件分岐ならそれ, そうでなく次の命令が条件分岐ならその分岐, どちらでもなければ None
- lbr_counts(): LBR (perf script -F brstacksym) から, 分岐ごとに「取られた回数」
  「取られて外れた回数」「取られなかった回数」を数える. 隣り合う2つの記録の間
  (古いほうの飛び先から新しいほうの分岐まで) はまっすぐ実行された区間なので, その中の条件分岐は
  取られなかったと数える (AutoFDO と同じ組み立て). LBR は取られた分岐しか記録しないので,
  取られずに外れた回数は分からない
"""

from __future__ import annotations

import re
import subprocess
from bisect import bisect_left
from collections import Counter
from dataclasses import dataclass, field

LINE = re.compile(r"^\s*([0-9a-f]+):\s+(\S+)(?:\s+(.*))?$")
FUNC = re.compile(r"^([0-9a-f]+) <([^>]+)>:$")
# 条件分岐 (jmp 以外の j*) と, ループの命令
COND = re.compile(r"^j(?!mp)[a-z]+$|^loop")


@dataclass
class Disasm:
    insn: dict[int, tuple[str, str]] = field(default_factory=dict)  # 番地 → (命令, 引数)
    addrs: list[int] = field(default_factory=list)  # 昇順
    funcs: dict[str, int] = field(default_factory=dict)  # 関数名 → 先頭の番地

    def is_cond(self, a: int) -> bool:
        return a in self.insn and bool(COND.match(self.insn[a][0]))

    def next_addr(self, a: int) -> int | None:
        i = bisect_left(self.addrs, a)
        if i < len(self.addrs) and self.addrs[i] == a and i + 1 < len(self.addrs):
            return self.addrs[i + 1]
        return None

    def conds_in(self, lo: int, hi: int) -> list[int]:
        """[lo, hi) の中の条件分岐の番地。"""
        i = bisect_left(self.addrs, lo)
        out = []
        while i < len(self.addrs) and self.addrs[i] < hi:
            if self.is_cond(self.addrs[i]):
                out.append(self.addrs[i])
            i += 1
        return out


def disasm(path: str) -> Disasm:
    text = subprocess.run(
        ["objdump", "-d", "--no-show-raw-insn", "-w", path],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    d = Disasm()
    for line in text.splitlines():
        if m := FUNC.match(line):
            d.funcs[m.group(2)] = int(m.group(1), 16)
        elif m := LINE.match(line):
            d.insn[int(m.group(1), 16)] = (m.group(2), m.group(3) or "")
    d.addrs = sorted(d.insn)
    return d


def branch_of(d: Disasm, a: int) -> int | None:
    if d.is_cond(a):
        return a
    n = d.next_addr(a)
    if n is not None and d.is_cond(n):
        return n
    if a in d.insn and d.insn[a][0].startswith(("jmp", "call", "ret")):
        return a
    return None


SYMOFF = re.compile(r"^(.+)\+0x([0-9a-f]+)$")


def resolve(d: Disasm, s: str) -> int | None:
    """'関数+0x位置' をリンク時の番地に。知らない関数 (Python・libc・カーネル) は None。"""
    m = SYMOFF.match(s)
    if not m or m.group(1) not in d.funcs:
        return None
    return d.funcs[m.group(1)] + int(m.group(2), 16)


@dataclass
class LbrCounts:
    taken: Counter[int] = field(default_factory=Counter)
    taken_misp: Counter[int] = field(default_factory=Counter)
    not_taken: Counter[int] = field(default_factory=Counter)
    entries: int = 0  # 読んだ記録の数
    ranges: int = 0  # 組み立てに使えた区間の数


def lbr_counts(d: Disasm, lines: list[str]) -> LbrCounts:
    c = LbrCounts()
    for line in lines:
        recs = []
        for tok in line.split():
            parts = tok.split("/")
            if len(parts) < 3:
                continue
            fn = parts[0].rsplit("+", 1)[0]
            tn = parts[1].rsplit("+", 1)[0]
            recs.append((resolve(d, parts[0]), resolve(d, parts[1]), parts[2] == "M", fn, tn))
        # perf script は新しい記録から順に並べる
        for i, (frm, _to, misp, fn, _tn) in enumerate(recs):
            c.entries += 1
            if frm is not None and d.is_cond(frm):
                c.taken[frm] += 1
                if misp:
                    c.taken_misp[frm] += 1
            if i + 1 < len(recs):
                older_to, older_tn = recs[i + 1][1], recs[i + 1][4]
                # 区間は同じ関数の中だけ使う (関数をまたぐと, 間の命令を実行したとは言えない)
                if frm is not None and older_to is not None and older_tn == fn and older_to <= frm:
                    c.ranges += 1
                    for a in d.conds_in(older_to, frm):
                        c.not_taken[a] += 1
    return c
