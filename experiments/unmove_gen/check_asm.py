#!/usr/bin/python3
"""逆向きの生成器の機械語を数える (実験 unmove_gen。記録試行ではない。回す前の静的な確かめ)。

    python3 experiments/unmove_gen/check_asm.py <腕> <build_arm.sh の出力先> > logs/asm_<腕>.txt

build_arm.sh が作った -g の .so (出力先/g/animal_shogi.so) で unmoveCandidates (unmoveRaw・unmovePiece・
unmoveEmit などはインライン展開されて中に入る) を逆アセンブルし,
- 命令・tzcnt・lzcnt の数
- 条件分岐の数と, それぞれのソース行 (addr2line -i の一番内側) と行の文
を出す. bb_unmove では, 行の文に今の逆向きの生成器の分岐の形 (FORBIDDEN) が残っていたら終了コード 1
(狙った分岐: 元のマスが空いているか・盤の端・X の駒か・駒の種類の switch). tzcnt か lzcnt が無いときも 1.
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

FUNC = "unmoveCandidates"
# 今の逆向きの生成器 (impl/35_bitboard の unmovePiece・unmoveRaw) の分岐の形.
# 行番号は perf_branch_34 の categories.tsv (impl/34_unmove の行番号) で書く
FORBIDDEN = (
    "getKoma(nb, s)",  # 元のマスが空いているか (979)
    "s < 0",  # 元のマスが盤の外 (963)
    "s16 ==",  # 端の回り込み2条件 (966・967)
    "d16 ==",  # ひよこの成らない前進を戻せる行か (947)・にわとりが端の行か (972)
    "& 0b1000",  # X の駒か (1006)
    "switch",  # 駒の種類の switch (954)
    "k == CHICK2",  # 打った手を戻せる駒か (938)・戻す駒がひよこか (945)
    "k == CHICKEN2",  # にわとりが端の行にいて, ひよこの成りを戻せるか (972)
    "moves_num",  # 指し手の表のループ (961)
    "k0s[j]",  # 戻した先から相手のライオンに利くか (980)
)


def main() -> int:
    arm, out = sys.argv[1], pathlib.Path(sys.argv[2])
    so = str(out / "g" / "animal_shogi.so")
    src = (out / "animal_shogi.c").read_text(encoding="utf-8").splitlines()
    d = disasm(so)
    st = d.funcs[FUNC]
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
    print(f"# {arm}: {FUNC} の機械語 (-g の .so。.text は -g なしと一致)")
    print(
        f"命令 {len(body)} / tzcnt {names['tzcnt']} / lzcnt {names['lzcnt']} / "
        f"条件分岐 {len(br)}"
    )
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
    if arm == "bb_unmove":
        if names["tzcnt"] == 0 or names["lzcnt"] == 0:
            print("!!! tzcnt か lzcnt が無い")
            ok = False
        if bad:
            print(f"!!! 今の分岐の形が残っている行: {bad}")
            ok = False
        print("判定: " + ("通過" if ok else "止める"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
