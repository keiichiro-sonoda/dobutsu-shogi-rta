#!/usr/bin/python3
"""生成器の機械語を数える (実験 bitboard_gen。記録試行ではない。回す前の静的な確かめ)。

    python3 experiments/bitboard_gen/check_asm.py <腕> <build_arm.sh の出力先> > logs/asm_<腕>.txt

build_arm.sh が作った -g の .so (出力先/g/animal_shogi.so) で nextBoardInvNormalNC を逆アセンブルし,
- tzcnt と pext の数
- 条件分岐の数と, それぞれのソース行 (addr2line -i の一番内側) と行の文
を出す. bb_* の腕では, 行の文に今の生成器の分岐の形 (FORBIDDEN) が残っていたら終了コード 1
(止める条件 3). tzcnt が無い (bb_pext は pext も無い) ときも 1.
警告の数 (出力先/warnings.txt) も並べる.
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys
from collections import Counter

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "perf_branch_34"))
from branches import disasm  # noqa: E402

# 今の生成器 (impl/34_unmove の 623・625・643・646・657〜662 行) の分岐の形
FORBIDDEN = (
    "getKoma(b, src))",  # マスが空きか (623)
    "(koma == CHICK2)",  # ひよこか (625)
    "(koma == LION1)",  # ライオンか (643)。キャッチの (dst_koma == LION1) には当たらない
    "switch",  # 駒の種類 (646)
    "dst < 0",  # 盤の外 (657)
    "% 16 ==",  # ひよこが奥の端 (626)
    "_mod16 ==",  # 端の回り込み (659・660)
    "& 0b1000",  # 自分の駒か (662)
    "if ((dst_koma",  # 行き先に駒があるか (661)
)


def main() -> int:
    arm, out = sys.argv[1], pathlib.Path(sys.argv[2])
    so = str(out / "g" / "animal_shogi.so")
    src = (out / "animal_shogi.c").read_text(encoding="utf-8").splitlines()
    d = disasm(so)
    st = d.funcs["nextBoardInvNormalNC"]
    end = min(a for a in d.funcs.values() if a > st)
    body = [a for a in d.addrs if st <= a < end]
    names = Counter(d.insn[a][0] for a in body)
    br = [a for a in body if d.is_cond(a)]
    res = subprocess.run(
        ["addr2line", "-a", "-i", "-e", so, *[hex(a) for a in br]],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    lines: Counter[int] = Counter()
    cur = None
    for ln in res:
        if ln.startswith("0x"):
            cur = ln
        elif cur is not None:
            m = re.search(r":(\d+)", ln)
            lines[int(m.group(1)) if m else -1] += 1
            cur = None
    warn = (out / "warnings.txt").read_text(encoding="utf-8")
    print(f"# {arm}: nextBoardInvNormalNC の機械語 (-g の .so。.text は -g なしと一致)")
    print(f"命令 {len(body)} / tzcnt {names['tzcnt']} / pext {names['pext']} / 条件分岐 {len(br)}")
    print(f"-Wall -Wextra の警告: {warn.count('warning:')}")
    print("条件分岐の行 (数 / 行 / 文):")
    bad = []
    for line, n in sorted(lines.items()):
        text = src[line - 1].strip() if 0 < line <= len(src) else "?"
        hit = [p for p in FORBIDDEN if p in text]
        if hit:
            bad.append(line)
        mark = f"  ← 今の分岐の形 {hit}" if hit else ""
        print(f"  {n}\t{line}\t{text[:100]}{mark}")
    ok = True
    if arm != "base":
        if names["tzcnt"] == 0:
            print("!!! tzcnt が無い")
            ok = False
        if arm == "bb_pext" and names["pext"] == 0:
            print("!!! pext が無い")
            ok = False
        if bad:
            print(f"!!! 今の分岐の形が残っている行: {bad}")
            ok = False
        print("判定: " + ("通過" if ok else "止める"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
