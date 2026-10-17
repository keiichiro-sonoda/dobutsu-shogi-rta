#!/usr/bin/python3
"""束ね方の表を作る (実験 unmove_gen。回す前に決める. 回したあとで組み替えない)。

    python3 make_categories.py <腕> <腕の animal_shogi.c> > categories_<腕>.tsv

束の名前と中身は perf_branch_34 の categories.tsv (impl/34_unmove の行番号) と同じ。
1. impl/34_unmove と impl/35_bitboard の行を difflib で突き合わせ, 同じ文の行に categories.tsv の束を写す
   (#35 は全探索の生成器だけを変えたので, 逆向きの生成器と unmoveStep の行は文が同じまま行番号だけずれる)
2. impl/35_bitboard と腕の行を同じく突き合わせ, 同じ文の行に 1 の束を写す (base はそのまま)
3. 腕で新しくなった行のうち, 条件分岐になりうる行 (if・for・while) を RULES で束に当てる.
   当たらなければ「その他」
写した行は, 両方の文が同じことを確かめる。
"""

from __future__ import annotations

import difflib
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
P34B = HERE.parent / "perf_branch_34" / "categories.tsv"
# (行の文に含まれる形, 束, 説明). 上から順に当てる
RULES = (
    ("while (src)", "ループの回数", "元のマスの候補を取り出すループ (番号の大きい順)"),
    ("while (xs)", "ループの回数", "X の駒のマスを取り出すループ"),
    ("UNMOVE_DROP_KOMA >> k", "駒の種類", "打った手を戻せる駒か・打ったあとの持ち駒の数が 2 未満か"),
    ("if (g_upromo[k]", "駒の種類", "にわとりが端の行にいて, ひよこの成りを戻せるか"),
    ("for (int t = 0; t < 4; t++)", "ループの回数", "取った駒の4種類のループ"),
    ("if (!cnt) continue;", "持ち駒・取った駒の数", "その種類の持ち駒が無い (取った手を戻せない)"),
    ("if (c < 2) n = unmoveEmit(", "持ち駒・取った駒の数", "打ったあとの持ち駒の数が 2 未満か"),
    ("if (asz >= 2) return n;", "王手の数", "A が2マス以上 (前任が無い)"),
    ("if (asz == 1) return unmovePiece(", "王手の数", "A が1マス (その駒だけ戻す)"),
    ("if (unmoveMirror(q) == q)", "左右の正規化", "q が左右対称か (q だけから戻す作りの選び分け)"),
    ("if (normalBoard(p) != p) return n;", "左右の正規化", "戻した前任が正規形か (normalBoard(p) != p なら捨てる)"),
    ("if (!nrm)", "左右の正規化", "q が左右対称なときの出し方か (定数に畳まれて分岐にはならない)"),
)


def read(path: pathlib.Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def mapping(a: list[str], b: list[str]) -> dict[int, int]:
    """a の行番号 → b の行番号 (1 始まり). 文が同じ塊の中の行だけ。"""
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    out = {}
    for blk in sm.get_matching_blocks():
        for k in range(blk.size):
            out[blk.a + k + 1] = blk.b + k + 1
    return out


def main() -> int:
    arm, path = sys.argv[1], pathlib.Path(sys.argv[2])
    c34 = read(ROOT / "impl" / "34_unmove" / "animal_shogi.c")
    c35 = read(ROOT / "impl" / "35_bitboard" / "animal_shogi.c")
    carm = read(path)
    m1, m2 = mapping(c34, c35), mapping(c35, carm)
    cats: dict[int, tuple[str, str]] = {}
    for ln in read(P34B):
        if not ln[:1].isdigit():
            continue
        line, bundle, what = ln.split("\t")
        l35 = m1.get(int(line))
        if l35 is None:
            continue  # 全探索の生成器の行 (#35 で書き換わった)
        larm = m2.get(l35)
        if larm is None:
            continue
        assert c34[int(line) - 1] == carm[larm - 1]
        cats[larm] = (bundle, what)
    mapped = set(m2.values())
    start = next(i for i, ln in enumerate(carm) if ln.startswith("static void unmoveTableBuild("))
    end = next(i for i, ln in enumerate(carm) if ln.startswith("int unmoveInit("))
    for i in range(start, end):
        line = i + 1
        text = carm[i].strip()
        if line in mapped or line in cats:
            continue
        if not text.startswith(("if ", "if(", "for ", "while ")) and " if (" not in text:
            continue
        for pat, bundle, what in RULES:
            if pat in text:
                cats[line] = (bundle, what)
                break
        else:
            cats[line] = ("その他", text[:60])
    print(f"# 束ね方 (実験 unmove_gen の {arm}。回す前に決めた. make_categories.py が作った)")
    print("# 行はこの腕の animal_shogi.c の行番号. perf_branch_34 の categories.tsv を写し, 新しい行は RULES で当てた")
    print("line\tbundle\twhat")
    for line in sorted(cats):
        bundle, what = cats[line]
        print(f"{line}\t{bundle}\t{what}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
