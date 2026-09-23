"""前向き探索が本当に同じ答えを出すかを、小さく実際に走らせて確かめる。

impl/03 は searchNext() の重複排除をメモリ常駐に置き換えた。静的なテストでは
「読み直しのループが消えた」までしか言えないので、ここでは .so をビルドして
本物の探索を数ラウンド回し、直前の実装と成果物が一致することを見る。

impl/04 は全探索を1バイトも触っていないので、ここが一致することが
「後退解析しか変えていない」＝対照群が成立することの担保になる。
"""

from __future__ import annotations

import pathlib
import re

import pytest
from conftest import families, load_impl, run_forward

# 記録 #2 の実測では、最初のチャンク分割はラウンド11 の書き出しで起きる。
# そこまでは結果が一意に決まるので、直接比較できる。9ラウンドなら約2秒。
# ⚠️ 分割が起きたあとは比較できない。チャンクの分かれ方は集合の反復順で決まり、
#    次のラウンドで取り出す盤面が変わるので、途中で切った集合が実装ごとに違う
#    （impl/10 で差集合の書き方を変えたときに実際にそうなった）。完走すれば同じ。
ROUNDS_BEFORE_SPLIT = 9

# dat/ のファイル名に出る拡張子。#15 までが .pickle、#16 からが .bin
SUFFIX_RE = re.compile(r"\.(?:pickle|bin)\b")

# 分割を小さく起こすための上限。本番は 5,000,000。
SMALL_BOARD_NUM_MAX = 3000

# (前の実装, 次の実装)。全探索を変えたのは #3 だけで、#4 は無変更。
PAIRS = [
    ("02_resident_wins", "03_resident_seen"),
    ("03_resident_seen", "04_resident_unknown"),
    ("04_resident_unknown", "05_batch_wl_write"),
    ("05_batch_wl_write", "06_csr_counter"),
    ("06_csr_counter", "07_batch_forward_write"),
    ("07_batch_forward_write", "08_c_index"),
    ("08_c_index", "09_no_reslice"),
    ("09_no_reslice", "10_setdiff"),
    ("10_setdiff", "11_c_seen"),
    ("11_c_seen", "12_c_predecessors"),
    ("12_c_predecessors", "13_c_expand"),
    # ⚠️ #16 は dat/ の形式を pickle から生バイナリに変えた。**全探索の出力も
    #    そこに乗っている**ので、4系統の集合が #15 と一致することをここで見る
    #    (families() が dat/ の中身から形式を決めるので、形式をまたいで比べられる)。
    ("15_c_successors", "16_raw_binary"),
    # ⚠️ #17 は書き出しの set(...) を外した。集合は同じでもファイルの中の並びが
    #    変わるので、分割が起きる前 (ROUNDS_BEFORE_SPLIT) までなら比較できる。
    ("16_raw_binary", "17_no_set"),
    # ⚠️ #18 は Makefile の -O だけを変えた。C も Python もバイト同一なので、
    #    ここは conftest.build_library() の -O0 ビルドどうしの比較になり、
    #    **-O2 の答えは見ていない**。それは本走のオラクルと指紋とバイト比較が見る。
    ("17_no_set", "18_optimized"),
    # ⚠️ #19 が C に足した関数 (gatherPacked / gatherDraws) は retreatAnalysis() からしか
    #    呼ばれない。全探索の経路で変わったのは _profMark に足した getrusage だけで、
    #    値を読むだけ。forward.tsv の列は PROFILE_COLUMNS が決めているので出力は動かない。
    ("18_optimized", "19_c_gather"),
    # ⚠️ #20 は全探索の経路にも入る (F1 の nextBoardSeenNormal の先読みと, nextBoardInvNormal の
    #    moves = NULL)。先読みはヒントで書く値を変えず, moves は読まれない経路の初期化なので,
    #    出力は動かない。
    ("19_c_gather", "20_prefetch"),
    # #21 は発見済み表 (F1) の確保に巨大ページを頼む。付いても付かなくても書く値は同じ。
    # 全探索の要約に utime / stime の行を足したが, forward.tsv の列は変えていない
    ("20_prefetch", "21_hugepages"),
    # ⚠️ #22 はここに足せない。全探索が作業ファイル (unexplored / unknown) を書かなくなったので、
    #    打ち切った dat/ の4系統を比べる形が成り立たない。#21 との突き合わせ (ラウンドごとの件数・
    #    待ち行列・未知の並び・成果物のバイト) は tests/test_impl_22_in_memory.py が持っている
]

# ⚠️ #13 は展開ループを C へ移したので、集合の一致とサブログだけでは足りない
# (順序が動いてもここは通る)。dat/ のバイト比較は
# tests/test_impl_13_c_expand.py が別に持っている。


@pytest.mark.parametrize(("prev", "cur"), PAIRS)
def test_the_forward_search_is_unchanged_from_the_previous_impl(
    prev: str, cur: str, shared_library: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """分割が起きる前の範囲では、成果物もログも一致しなければならない。"""
    works: dict[str, pathlib.Path] = {}
    for impl in (prev, cur):
        work = tmp_path / impl
        module = load_impl(impl, work, shared_library)
        run_forward(module, work, ROUNDS_BEFORE_SPLIT)
        works[impl] = work

    fam_a, fam_b = families(works[prev] / "dat"), families(works[cur] / "dat")
    assert sum(len(v) for v in fam_a.values()) > 100_000, "探索が進んでいない (テストが空振り)"
    for key in fam_a:
        assert fam_a[key] == fam_b[key], f"{key} の盤面集合が impl/{prev} と違う"

    def sublog(work: pathlib.Path) -> str:
        text = (work / "kaiseki_log" / "kaiseki_log7.txt").read_text(encoding="utf-8")
        # サブログは探索中のファイル名をそのまま出すので、拡張子だけは食い違う
        # (#16 で .pickle → .bin)。⚠️ **潰すのは拡張子だけ**。件数も順序も潰さない
        return SUFFIX_RE.sub(".<形式>", text)

    assert sublog(works[prev]) == sublog(works[cur]), f"サブログが impl/{prev} と食い違う"


@pytest.fixture
def split_run(shared_library: pathlib.Path, tmp_path: pathlib.Path) -> tuple[object, pathlib.Path]:
    """チャンク分割が何度も起きる状態まで impl/04 (＝最新) を進める。"""
    work = tmp_path / "split"
    module = load_impl(PAIRS[-1][1], work, shared_library)
    run_forward(module, work, rounds=40, board_num_max=SMALL_BOARD_NUM_MAX)
    return module, work


def test_the_resident_set_equals_the_files_on_disk(
    split_run: tuple[object, pathlib.Path],
) -> None:
    """常駐集合は「発見済み盤面の全体」＝4系統の和集合であり続けること。

    ここが崩れると、すでに見た盤面をもう一度未探索に積んでしまう (＝答えが壊れる)。
    順序に依存しないので、チャンクの分かれ方が変わっても成立する。

    ⚠️ impl/11 から常駐集合は Python の set ではなく C 側の表になった。
    中身を丸ごと取り出す口は持たせていない (本走で 2.5 億件を Python に
    引き出す意味がない) ので、件数と全件の所属で同じことを確かめる。
    """
    module, work = split_run
    fam = families(work / "dat")
    assert len(fam["unexplored"]) > SMALL_BOARD_NUM_MAX, "分割が起きていない (テストが空振り)"

    union: set[int] = set()
    for boards in fam.values():
        assert not (union & boards), "4系統が互いに素でない"
        union |= boards

    seen = vars(module).get("seen_boards")
    if isinstance(seen, set):
        assert seen == union
        return
    # C 側の表 (impl/11 以降)
    count = vars(module)["seenCount"]
    contains = vars(module)["seenContains"]
    assert count() == len(union), "発見済みの件数が4系統の和と違う"
    missing = [b for b in union if not contains(b)]
    assert missing == [], f"表に入っていない盤面がある: {missing[:3]}"


def test_the_totals_match_what_is_on_disk(split_run: tuple[object, pathlib.Path]) -> None:
    """main.log の総未知/総勝ち/総負けは、いまカウンタから出ている。

    記録 #3 は 99485568 / 140298614 / 7018985。ここがずれたら完走ログもずれる。
    """
    module, work = split_run
    fam = families(work / "dat")
    assert vars(module)["tbn_uk"] == len(fam["unknown"])
    assert vars(module)["tbn_win"] == len(fam["win"])
    assert vars(module)["tbn_lose"] == len(fam["lose"])
