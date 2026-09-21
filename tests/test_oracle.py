"""oracle/ の内部整合性を検証する。

このリポジトリは「同じ答えに辿り着くまでの時間」だけを競う。
その「同じ答え」を固定しているのが oracle/ なので、ここが壊れると
記録すべてが無効になる。実装をいじる前に必ずここが通ること。
"""

from __future__ import annotations

import fingerprint_dat
from conftest import ORACLE_DIR, DistRow

# 田中哲朗 (2009) の完全解析で確定した既知の値
PUBLISHED_REACHABLE_TOTAL = 246_803_167


def fingerprint() -> dict[fingerprint_dat.Key, fingerprint_dat.Print]:
    """oracle/fingerprint.tsv を読む。壊れていれば load_tsv が落ちる。"""
    return fingerprint_dat.load_tsv((ORACLE_DIR / "fingerprint.tsv").read_text(encoding="utf-8"))


# distribution.tsv は 1手 から 174手 まで
FIRST_DEPTH = 1
LAST_DEPTH = 174


def test_distribution_has_174_rows(distribution: list[DistRow]) -> None:
    assert len(distribution) == LAST_DEPTH - FIRST_DEPTH + 1


def test_depths_are_contiguous(distribution: list[DistRow]) -> None:
    assert [d for d, _, _ in distribution] == list(range(FIRST_DEPTH, LAST_DEPTH + 1))


def test_odd_depths_are_win_and_even_are_lose(distribution: list[DistRow]) -> None:
    """手番が交互なので、奇数手は勝ち・偶数手は負けで確定する。"""
    for depth, result, _ in distribution:
        assert result == ("win" if depth % 2 else "lose"), f"depth={depth}"


def test_counts_are_non_negative(distribution: list[DistRow]) -> None:
    for depth, _, count in distribution:
        assert count >= 0, f"depth={depth}"


def test_win_sum_plus_catch_equals_win_total(
    distribution: list[DistRow], totals: dict[str, int]
) -> None:
    """distribution の win は depth=1 のキャッチ局面を含まない。足すと win_total になる。"""
    win_sum = sum(c for _, r, c in distribution if r == "win")
    assert win_sum + totals["catch_win_depth1"] == totals["win_total"]


def test_lose_sum_plus_depth0_equals_lose_total(
    distribution: list[DistRow], totals: dict[str, int]
) -> None:
    """distribution の lose は depth=0 の負け局面を含まない。足すと lose_total になる。"""
    lose_sum = sum(c for _, r, c in distribution if r == "lose")
    assert lose_sum + totals["lose_depth0"] == totals["lose_total"]


def test_decided_total_is_win_plus_lose(totals: dict[str, int]) -> None:
    assert totals["win_total"] + totals["lose_total"] == totals["decided_total"]


def test_reachable_total_is_decided_plus_draw(totals: dict[str, int]) -> None:
    assert totals["decided_total"] + totals["draw_total"] == totals["reachable_total"]


def test_reachable_total_matches_published_value(totals: dict[str, int]) -> None:
    assert totals["reachable_total"] == PUBLISHED_REACHABLE_TOTAL


def test_max_depth_is_the_last_nonzero_depth(
    distribution: list[DistRow], totals: dict[str, int]
) -> None:
    last_nonzero = max(d for d, _, c in distribution if c > 0)
    assert last_nonzero == totals["max_depth"]


def test_depth_174_is_empty(distribution: list[DistRow]) -> None:
    """新たな負け局面が1つも見つからなくなった時点が終了条件。その1手が 174手。"""
    by_depth = {d: c for d, _, c in distribution}
    assert by_depth[LAST_DEPTH] == 0
    assert by_depth[LAST_DEPTH - 1] > 0


# --------------------------------------------------------------------------
# oracle/fingerprint.tsv
#
# ⚠️ これはオラクルではない。記録 #15 の成果物から取った値で、由来が違う。
# ただし**件数の列は distribution.tsv と totals.tsv から導ける**ので、そこは
# 機械で固定できる。総和と XOR は導けないので、ここでは形だけを見る。
# --------------------------------------------------------------------------

FINGERPRINT_ROWS = 176


def test_the_fingerprint_is_readable() -> None:
    """★176 項目あり、重複も欠けも無いこと。"""
    assert len(fingerprint()) == FINGERPRINT_ROWS


def test_the_fingerprint_totals_match_totals_tsv(totals: dict[str, int]) -> None:
    """★勝ち・負け・引き分け・全体の件数が totals.tsv と合うこと。"""
    fp = fingerprint()
    by = {r: sum(c for (_, res), (c, _, _) in fp.items() if res == r) for r in ("win", "lose")}
    assert by["win"] == totals["win_total"]
    assert by["lose"] == totals["lose_total"]
    assert fp[(None, "draw")][0] == totals["draw_total"]
    assert sum(c for c, _, _ in fp.values()) == totals["reachable_total"]


def test_the_fingerprint_reproduces_the_distribution(
    distribution: list[DistRow], totals: dict[str, int]
) -> None:
    """★174行の件数をそのまま再現すること。差は depth=1 のキャッチだけ。

    ⚠️ **これがこのファイルの件数列を縛っている唯一の検査。**
    dat/ はキャッチを含むので depth=1 win だけ catch_win_depth1 のぶん多い。
    残り173行は distribution.tsv と一致しなければならない。
    """
    fp = fingerprint()
    for depth, result, count in distribution:
        want = count + (totals["catch_win_depth1"] if (depth, result) == (1, "win") else 0)
        assert fp[(depth, result)][0] == want, f"depth={depth} {result}"


def test_the_fingerprint_has_exactly_two_extra_keys(distribution: list[DistRow]) -> None:
    """★distribution.tsv に無いのは depth=0 の負けと引き分けの2つだけ。"""
    extra = set(fingerprint()) - {(d, r) for d, r, _ in distribution}
    assert extra == {(0, "lose"), (None, "draw")}


def test_the_depth0_lose_matches_totals(totals: dict[str, int]) -> None:
    assert fingerprint()[(0, "lose")][0] == totals["lose_depth0"]


def test_the_fingerprint_is_not_presented_as_the_oracle() -> None:
    """★「オラクルではない」と「完全一致を証明しない」が本文に書いてあること。

    置き場所が oracle/ なので、断り書きが消えると原典と同じ重みで読まれる。
    """
    head = (ORACLE_DIR / "fingerprint.tsv").read_text(encoding="utf-8")
    comments = "\n".join(line for line in head.splitlines() if line.startswith("#"))
    assert "オラクルではない" in comments
    assert "完全一致を証明しない" in comments
