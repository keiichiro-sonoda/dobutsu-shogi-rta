#!/usr/bin/python3
"""腕の束ね方の表を作る (実験 f1_select_catch。回す前に決める. 回したあとで組み替えない)。

    python3 make_categories.py <腕の animal_shogi.c> > categories_<腕>.tsv

experiments/bitboard_gen/make_categories.py の作りを, 4腕 (base も impl/37_mirror1 の行番号で) に広げたもの.
束の名前は perf_branch_34 と bitboard_gen と同じで, 先行判定の束「キャッチの先行判定」と「表づくり」を足した.
- nextBoardInvNormalNC の行は, 行の文の形 (RULES) で束に当てる. 先行判定の区画 (「キャッチの先行判定.」の注釈から
  if (hit) return 0; まで) は「キャッチの先行判定」. ビット集合を取り出すループ (while (x) / while (t)) は「ループの回数」.
  当たらない if / for / while と閉じ括弧の行は「その他」
- 生成器から呼ばれる下請け: normalBoard と normalBoardSel の本体は「左右の正規化」, komaSet の本体は「キャッチの先行判定」
- 起動時に1回走る表づくり (dstTableBuild・rankTablesBuild の本体) は「表づくり」
"""

from __future__ import annotations

import pathlib
import re
import sys

# (行の文に含まれる形, 束, 説明). 上から順に当てる. 前半は bitboard_gen の RULES と同じ
RULES = (
    ("for (int sq = 0; sq < 12; sq++)", "ループの回数", "利きの一覧の12マスのループ (今のまま)"),
    ("if (dst_koma == LION1) return 0;", "キャッチ", "行き先が相手のライオン (return 0)"),
    ("own_p = dst_koma == CHICKEN1", "持ち駒の数", "取った駒の持ち駒の位置"),
    ("nb ^= ((b >> own_p) & 0b11 ?", "持ち駒の数", "取った駒の種類の持ち駒が既にあるか"),
    ("nb ^= ((u_long)(1 + 2 *", "持ち駒の数", "取った駒の種類の持ち駒が既にあるか (select: 算術で選ぶ)"),
    ("k2 = koma +", "トライ・成り", "ひよこが端の行に進んだら成る"),
    ("c = koma == LION2 ?", "駒の種類と空き", "動かす駒がライオンか (キャッチ抜きの数え方を選ぶ)"),
    ("unsigned isL = ", "駒の種類と空き", "動かす駒がライオンかのマスク (select)"),
    ("c = (int)((((att1", "駒の種類と空き", "キャッチ抜きの数え方をマスクで選ぶ (select)"),
    ("try_flag = ", "トライ・成り", "相手のライオンがトライの段にいるか"),
    ("if (try_flag) return -1;", "トライ・成り", "トライが成立していて return -1"),
    ("for (i = 0; i < 3; i++)", "ループの回数", "持ち駒の3種類のループ"),
    ("if (!own_num) continue;", "持ち駒の数", "その種類の持ち駒が無い"),
    ("nb = b ^ (own_num == 2", "持ち駒の数", "打ったあとの持ち駒の数"),
    ("for (j = 0; j < emp_num; j++)", "ループの回数", "打つ空きマスのループ"),
)
HELPERS = (
    ("normalBoard", "左右の正規化"),
    ("normalBoardSel", "左右の正規化"),
    ("komaSet", "キャッチの先行判定"),
    ("dstTableBuild", "表づくり"),
    ("rankTablesBuild", "表づくり"),
)


def func_range(src: list[str], name: str) -> range:
    """関数 name の定義の行 (0始まりの添字, 閉じ括弧まで)。無ければ空。"""
    for i, ln in enumerate(src):
        if re.match(rf"^\S.*\b{name}\(", ln) and ln.rstrip().endswith("{"):
            j = next(k for k in range(i, len(src)) if src[k] == "}")
            return range(i, j + 1)
    return range(0)


def main() -> int:
    src = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
    out: dict[int, tuple[str, str]] = {}
    for name, bundle in HELPERS:
        for i in func_range(src, name):
            out[i + 1] = (bundle, f"{name}: {src[i].strip()[:60]}")
    gen = func_range(src, "nextBoardInvNormalNC")
    pre_lo = next((i for i in gen if "キャッチの先行判定." in src[i]), None)
    pre_hi = next((i for i in gen if "if (hit) return 0;" in src[i]), None)
    nwhile = 0
    for i in gen:
        text = src[i].strip()
        line = i + 1
        if pre_lo is not None and pre_hi is not None and pre_lo <= i <= pre_hi:
            out[line] = ("キャッチの先行判定", f"先行判定: {text[:60]}")
            continue
        if text.startswith("while (x)"):
            nwhile += 1
            what = "手番側の駒のマスを取り出すループ" if nwhile == 1 else "空きマスを取り出すループ"
            out[line] = ("ループの回数", what)
            continue
        if text.startswith("while (t)"):
            out[line] = ("ループの回数", "行き先を取り出すループ")
            continue
        for pat, bundle, what in RULES:
            if pat in text:
                out[line] = (bundle, what)
                break
        else:
            if i == gen[-1] or text.startswith(("if ", "for ", "while ")):
                out[line] = ("その他", text[:60])
    print("# 束ね方 (実験 f1_select_catch。回す前に決めた. make_categories.py が作った)")
    print("line\tbundle\twhat")
    for line in sorted(out):
        print(f"{line}\t{out[line][0]}\t{out[line][1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
