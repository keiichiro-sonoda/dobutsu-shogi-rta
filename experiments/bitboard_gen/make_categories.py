#!/usr/bin/python3
"""bb_* の腕の束ね方の表を作る (実験 bitboard_gen。回す前に決める. 回したあとで組み替えない)。

    python3 make_categories.py <腕の animal_shogi.c> > categories_<腕>.tsv

nextBoardInvNormalNC の行を, 行の文の形 (RULES) で束に当てる. 束の名前は
perf_branch_34 の categories.tsv と同じ. パッチが変えた最初の行より前
(normalBoard の 100 行など) は,
impl/34_unmove と行番号も中身も同じなので, perf_branch_34 の categories.tsv の行をそのまま写す.
生成器の中で RULES に当たらない分岐の行は「その他」.
"""

from __future__ import annotations

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
P34B = HERE.parent / "perf_branch_34" / "categories.tsv"
# (行の文に含まれる形, 束, 説明). 上から順に当てる
RULES = (
    ("for (int sq = 0; sq < 12; sq++)", "ループの回数", "利きの一覧の12マスのループ (今のまま)"),
    ("if (dst_koma == LION1) return 0;", "キャッチ", "行き先が相手のライオン (return 0)"),
    ("own_p = dst_koma == CHICKEN1", "持ち駒の数", "取った駒の持ち駒の位置"),
    ("nb ^= ((b >> own_p) & 0b11 ?", "持ち駒の数", "取った駒の種類の持ち駒が既にあるか"),
    ("k2 = koma +", "トライ・成り", "ひよこが端の行に進んだら成る"),
    ("c = koma == LION2 ?", "駒の種類と空き", "動かす駒がライオンか (キャッチ抜きの数え方を選ぶ)"),
    ("try_flag = ", "トライ・成り", "相手のライオンがトライの段にいるか"),
    ("if (try_flag) return -1;", "トライ・成り", "トライが成立していて return -1"),
    ("for (i = 0; i < 3; i++)", "ループの回数", "持ち駒の3種類のループ"),
    ("if (!own_num) continue;", "持ち駒の数", "その種類の持ち駒が無い"),
    ("nb = b ^ (own_num == 2", "持ち駒の数", "打ったあとの持ち駒の数"),
    ("for (j = 0; j < emp_num; j++)", "ループの回数", "打つ空きマスのループ"),
)


def main() -> int:
    src = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
    base_c = HERE.parent.parent / "impl" / "34_unmove" / "animal_shogi.c"
    base_lines = base_c.read_text(encoding="utf-8").splitlines()
    pairs = enumerate(zip(src, base_lines, strict=False))
    first_diff = next(i for i, (a, b) in pairs if a != b) + 1
    start = next(i for i, ln in enumerate(src) if ln.startswith("int nextBoardInvNormalNC("))
    end = next(i for i in range(start, len(src)) if src[i] == "}")
    print("# 束ね方 (実験 bitboard_gen。回す前に決めた. make_categories.py が作った)")
    print("line\tbundle\twhat")
    for ln in P34B.read_text(encoding="utf-8").splitlines():
        if ln[:1].isdigit() and int(ln.split("\t")[0]) < first_diff:
            print(ln)
    nwhile = 0
    for i in range(start, end + 1):
        text = src[i].strip()
        line = i + 1
        if text.startswith("while (x)"):
            nwhile += 1
            what = "手番側の駒のマスを取り出すループ" if nwhile == 1 else "空きマスを取り出すループ"
            print(f"{line}\tループの回数\t{what}")
            continue
        if text.startswith("while (t)"):
            print(f"{line}\tループの回数\t行き先を取り出すループ")
            continue
        for pat, bundle, what in RULES:
            if pat in text:
                print(f"{line}\t{bundle}\t{what}")
                break
        else:
            if i == end or text.startswith(("if ", "for ", "while ")):
                print(f"{line}\tその他\t{text[:60]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
