#!/usr/bin/python3
"""生成器の機械語を数える (実験 f1_select_catch。記録試行ではない。組むたびの静的な確かめ)。

    python3 experiments/f1_select_catch/check_asm.py <腕> <build_arm.sh の出力先> > logs/asm_<腕>.txt

experiments/bitboard_gen/check_asm.py を広げたもの. build_arm.sh が作った -g の .so (出力先/g/animal_shogi.so) で
nextBoardInvNormalNC を逆アセンブルし, 命令ごとのソース行 (addr2line -i の一番内側) を引いて,
- 命令の数, tzcnt・cmov・set の数, 条件分岐の数
- 条件分岐の行 (数 / 行 / 文)
- 狙った3か所 (TARGETS) の行ごとに, 条件分岐・cmov・set の数
- 3か所以外の三項演算 (OTHERS) の行ごとに, 条件分岐の数 (変えない. 機械語でジャンプかどうかを書くだけ)
- precheck と both では, 先行判定の行 (PRECHECK) の条件分岐 ( if (hit) return 0; の1つだけのはず)
を出す. select と both では, 狙った3か所のどれかに条件分岐が残っていたら終了コード 1 (止める条件 3).
狙った行が1つも見つからないときも 1 (パターンが外れて, 確かめたことにならないため).
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

# 狙った3か所. (名前, base の行の文の形, select の行の文の形)
TARGETS = (
    ("持ち駒の更新", "nb ^= ((b >> own_p) & 0b11 ?", "nb ^= ((u_long)(1 + 2 * (((b >> own_p) & 0b11) != 0))"),
    ("キャッチ抜きの数を選ぶ", "c = koma == LION2 ?", "c = (int)((((att1 >> (dst / 4)) & 1u) & isL)"),
    ("左右の正規化", "if (col_A <= col_C) return b;", None),  # select は normalBoardSel の本体の行 (下で数える)
)
# 3か所以外の三項演算 (変えない)
OTHERS = (
    ("取った駒の持ち駒の位置", "own_p = dst_koma == CHICKEN1 ?"),
    ("打ったあとの持ち駒の数", "nb = b ^ (own_num == 2 ?"),
)
PRECHECK_IF = "if (hit) return 0;"


def func_lines(src: list[str], name: str) -> range:
    """関数 name の定義の行 (1始まり, 閉じ括弧まで)。無ければ空。"""
    for i, ln in enumerate(src):
        if re.match(rf"^\S.*\b{name}\(", ln) and ln.rstrip().endswith("{"):
            j = next(k for k in range(i, len(src)) if src[k] == "}")
            return range(i + 1, j + 2)
    return range(0)


def main() -> int:
    arm, out = sys.argv[1], pathlib.Path(sys.argv[2])
    so = str(out / "g" / "animal_shogi.so")
    src = (out / "animal_shogi.c").read_text(encoding="utf-8").splitlines()
    d = disasm(so)
    st = d.funcs["nextBoardInvNormalNC"]
    end = min(a for a in d.funcs.values() if a > st)
    body = [a for a in d.addrs if st <= a < end]
    res = subprocess.run(
        ["addr2line", "-a", "-i", "-e", so, *[hex(a) for a in body]],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    line_of: dict[int, int] = {}
    cur = None
    for ln in res:
        if ln.startswith("0x"):
            cur = int(ln, 16)
        elif cur is not None:
            m = re.search(r":(\d+)", ln)
            line_of[cur] = int(m.group(1)) if m else -1
            cur = None
    names = Counter(d.insn[a][0] for a in body)
    br = [a for a in body if d.is_cond(a)]
    n_cmov = sum(n for k, n in names.items() if k.startswith("cmov"))
    n_set = sum(n for k, n in names.items() if k.startswith("set"))
    warn = (out / "warnings.txt").read_text(encoding="utf-8")
    print(f"# {arm}: nextBoardInvNormalNC の機械語 (-g の .so。.text は -g なしと一致)")
    print(f"命令 {len(body)} / tzcnt {names['tzcnt']} / cmov {n_cmov} / set {n_set} / 条件分岐 {len(br)}")
    print(f"-Wall -Wextra の警告: {warn.count('warning:')}")

    def text(line: int) -> str:
        return src[line - 1].strip() if 0 < line <= len(src) else "?"

    def count(lines: set[int]) -> tuple[int, int, int, int]:
        ins = [a for a in body if line_of.get(a) in lines]
        k = Counter(d.insn[a][0] for a in ins)
        return (
            len(ins),
            sum(1 for a in ins if d.is_cond(a)),
            sum(n for m, n in k.items() if m.startswith("cmov")),
            sum(n for m, n in k.items() if m.startswith("set")),
        )

    print("条件分岐の行 (数 / 行 / 文):")
    for line, n in sorted(Counter(line_of[a] for a in br).items()):
        print(f"  {n}\t{line}\t{text(line)[:100]}")

    selected = arm in ("select", "both")
    sel_body = set(func_lines(src, "normalBoardSel"))
    gen = func_lines(src, "nextBoardInvNormalNC")
    # 行の文の形を当てる範囲: 生成器と normalBoard の本体 (nextBoardInvNormal などの同じ形の行を拾わない)
    scope = set(gen) | set(func_lines(src, "normalBoard"))
    print("狙った3か所 (行の命令の数 / 条件分岐 / cmov / set。インライン展開された命令を行に寄せた数):")
    ok = True
    for name, base_pat, sel_pat in TARGETS:
        pat = sel_pat if selected else base_pat
        if pat is None:
            lines = sel_body
        else:
            lines = {i for i in scope if pat in src[i - 1]}
        n_ins, n_br, n_cm, n_st = count(lines)
        where = ",".join(str(x) for x in sorted(lines)) or "?"
        print(f"  {name}\t行 {where}\t命令 {n_ins} / 条件分岐 {n_br} / cmov {n_cm} / set {n_st}")
        if selected and (not lines or n_ins == 0):
            print(f"!!! {name}: 狙った行が見つからないか, 命令が1つも寄っていない")
            ok = False
        if selected and n_br:
            print(f"!!! {name}: 条件分岐が {n_br} 個残っている")
            ok = False
    print("3か所以外の三項演算 (変えない。条件分岐の数):")
    for name, pat in OTHERS:
        lines = {i for i in scope if pat in src[i - 1]}
        n_ins, n_br, n_cm, n_st = count(lines)
        print(f"  {name}\t行 {','.join(str(x) for x in sorted(lines))}\t命令 {n_ins} / 条件分岐 {n_br} / cmov {n_cm} / set {n_st}")
    if arm in ("precheck", "both"):
        lo = next(i for i in gen if "キャッチの先行判定." in src[i - 1])
        hi = next(i for i in gen if PRECHECK_IF in src[i - 1])
        lines = set(range(lo, hi + 1)) | set(func_lines(src, "komaSet"))
        n_ins, n_br, n_cm, n_st = count(lines)
        print(f"先行判定 (行 {lo}〜{hi} と komaSet の本体): 命令 {n_ins} / 条件分岐 {n_br} / cmov {n_cm} / set {n_st}")
        if n_br != 1:
            print(f"!!! 先行判定の条件分岐が {n_br} 個 (if (hit) return 0; の1つだけのはず)")
    if selected:
        print("判定: " + ("通過" if ok else "止める (止める条件 3)"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
