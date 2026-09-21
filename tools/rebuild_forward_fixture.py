#!/usr/bin/env python3
"""完走した `dat/` から「全探索が終わった直後の状態」を組み直す。

記録 #6 の門番 G1 は、全規模の後退解析だけを走らせて答え合わせをする。
そのためには全探索の出力が要るが、**その状態はもう残っていない**。
後退解析が `unknown*` を消し、`win001te_*` に追記し、
`win{N}te_*` / `lose{N}te_*` を積み上げてしまうからである。

戻し方は、後退解析がしたことをちょうど逆にたどるだけ:

    キャッチ (1手勝ち)   win001te_* の先頭から、全探索が書いた件数ぶん
    トライ負け (0手負け) lose000te_* 全部 (後退解析は深さ0を書かない)
    未知                 それ以外の全部 (深さ1の残り, 深さ2以上, 引き分け)

件数は推測しない。全探索が完了時に main.log へ書いた行から読む:

    総未知盤面数：99485568, 総勝ち盤面数：140298614, 総負け盤面数：7018985

キャッチの境界がファイルの切れ目に乗らなければ、そこで止める。全探索は
`updateWLFile()` で末尾に詰めて書き、後退解析は `writeWLFilesForDepth()` で
空き副番号から新しいファイルを作るので、境界は必ずファイルの切れ目に来る。

⚠️ 出来上がるのは**後退解析の入力として完全な** `dat/` であって、全探索の作業
途中のファイル (`unexplored*`) は含まない。`retreatAnalysis()` は
`unknown*` / `win001te_*` / `lose000te_*` しか読まないので、これで足りる。

読む形式は元の `dat/` の中身から決める (#15 までの `.pickle` も #16 以降の
`.bin` も読む)。**書き出しは必ず新形式 (`.bin`)** で、記録 #16 以降の実装が
そのまま読める。形式の知識は `tools/fingerprint_dat.py` の `Format` に持たせて
2か所に置かない。

使い方:

    python3 tools/rebuild_forward_fixture.py <元の dat/> <その run の main.log> <出力先 dat/>
"""

from __future__ import annotations

import functools
import operator
import pathlib
import re
import sys
from array import array

import fingerprint_dat

# 1ファイルに入れる盤面数。実装側の BOARD_NUM_MAX と合わせる
BOARD_NUM_MAX = 5000000

# 書き出しは常に新形式 (記録 #16 以降の実装が読む形)。読みは元の dat/ に合わせる
OUT = fingerprint_dat.RAW

# 全探索が完了時に書く行
TOTALS_RE = re.compile(r"総未知盤面数：(\d+), 総勝ち盤面数：(\d+), 総負け盤面数：(\d+)")

MASK64 = (1 << 64) - 1


class Digest:
    """件数・総和・XOR。順序に依らないので、詰め替えの前後で比べられる。"""

    def __init__(self) -> None:
        self.count = 0
        self.total = 0
        self.xor = 0

    def add(self, boards: list[int]) -> None:
        self.count += len(boards)
        self.total = (self.total + sum(boards)) & MASK64
        self.xor ^= functools.reduce(operator.xor, boards, 0)

    def as_tuple(self) -> tuple[int, int, int]:
        return self.count, self.total, self.xor


def read_forward_totals(main_log: pathlib.Path) -> tuple[int, int, int]:
    """main.log から (未知, キャッチ, トライ負け) の件数を読む。"""
    for line in main_log.read_text(encoding="utf-8").splitlines():
        m = TOTALS_RE.search(line)
        if m:
            return int(m.group(1)), int(m.group(2)), int(m.group(3))
    raise SystemExit(f"{main_log} に全探索の総数の行が無い")


def load(path: pathlib.Path, fmt: fingerprint_dat.Format) -> list[int]:
    return list(fmt.load(path))


def write(boards: list[int], path: pathlib.Path) -> None:
    """新形式で書き出す。⚠️ set() を通す順序が採番順になるので、ここも実装に揃える。"""
    path.write_bytes(array("Q", set(boards)).tobytes())


def sorted_subs(dat: pathlib.Path, pattern: re.Pattern[str], depth: int) -> list[pathlib.Path]:
    """指定した手数のファイルを副番号の順に返す。"""
    out: list[tuple[int, pathlib.Path]] = []
    for p in dat.iterdir():
        m = pattern.match(p.name)
        if m and int(m.group(1)) == depth:
            out.append((int(m.group(2)), p))
    return [p for _, p in sorted(out)]


def other_files(
    dat: pathlib.Path, catch_files: set[pathlib.Path], fmt: fingerprint_dat.Format
) -> list[pathlib.Path]:
    """キャッチと 0手負け以外＝未知に戻すファイル。"""
    out: list[pathlib.Path] = []
    for p in sorted(dat.iterdir()):
        if p in catch_files:
            continue
        m = fmt.win.match(p.name) or fmt.lose.match(p.name)
        if m:
            if fmt.lose.match(p.name) and int(m.group(1)) == 0:
                continue  # 0手負けはそのまま残す
            out.append(p)
        elif fmt.unknown.match(p.name):
            out.append(p)  # 引き分け
    return out


def pick_catch_files(
    dat: pathlib.Path, n_catch: int, fmt: fingerprint_dat.Format
) -> list[pathlib.Path]:
    """win001te_* の先頭から、キャッチの件数ちょうどになるまで取る。"""
    picked: list[pathlib.Path] = []
    seen = 0
    for path in sorted_subs(dat, fmt.win, 1):
        if seen == n_catch:
            break
        seen += len(load(path, fmt))
        picked.append(path)
        if seen > n_catch:
            raise SystemExit(
                f"キャッチの境界がファイルの切れ目に乗らない: {path.name} まで {seen} 件 "
                f"(欲しいのは {n_catch} 件)。全探索を1本回してフィクスチャを作ること"
            )
    if seen != n_catch:
        raise SystemExit(f"キャッチが足りない: {seen} / {n_catch} 件")
    return picked


def write_unknown(boards: list[int], dst: pathlib.Path, sub: int, digest: Digest) -> int:
    """未知盤面を1ファイル書き出し、次の副番号を返す。"""
    digest.add(boards)
    write(boards, dst / f"unknown{sub:03d}{OUT.suffix}")
    return sub + 1


def rebuild(src: pathlib.Path, main_log: pathlib.Path, dst: pathlib.Path) -> None:
    n_uk, n_catch, n_lose = read_forward_totals(main_log)
    print(f"全探索の総数: 未知 {n_uk:,} / キャッチ {n_catch:,} / トライ負け {n_lose:,}")
    dst.mkdir(parents=True, exist_ok=True)
    if any(dst.iterdir()):
        raise SystemExit(f"{dst} が空でない")

    # 元の dat/ の形式は中身から決める。#15 までの .pickle も #16 以降の .bin も読む
    fmt = fingerprint_dat.detect(src)
    print(f"元の形式: {fmt.name} ({fmt.suffix}) → 書き出し: {OUT.name} ({OUT.suffix})")

    before = Digest()
    after = Digest()

    # キャッチ: win001te_* の先頭から件数ぶん
    catch_files = pick_catch_files(src, n_catch, fmt)
    for sub, path in enumerate(catch_files):
        boards = load(path, fmt)
        before.add(boards)
        after.add(boards)
        write(boards, dst / f"win001te_{sub:03d}{OUT.suffix}")
    print(f"キャッチ: {len(catch_files)} ファイル")

    # トライ負け: lose000te_* をそのまま
    lose_files = sorted_subs(src, fmt.lose, 0)
    n_lose_seen = 0
    for sub, path in enumerate(lose_files):
        boards = load(path, fmt)
        n_lose_seen += len(boards)
        before.add(boards)
        after.add(boards)
        write(boards, dst / f"lose000te_{sub:03d}{OUT.suffix}")
    if n_lose_seen != n_lose:
        raise SystemExit(f"0手負けが合わない: {n_lose_seen} / {n_lose}")
    print(f"トライ負け: {len(lose_files)} ファイル")

    # 未知: 残り全部
    buf: list[int] = []
    sub = 0
    n_uk_seen = 0
    for path in other_files(src, set(catch_files), fmt):
        boards = load(path, fmt)
        before.add(boards)
        n_uk_seen += len(boards)
        buf += boards
        while len(buf) >= BOARD_NUM_MAX:
            sub = write_unknown(buf[:BOARD_NUM_MAX], dst, sub, after)
            del buf[:BOARD_NUM_MAX]
    # 端数 (0件でも1ファイルは作る)
    sub = write_unknown(buf, dst, sub, after)
    print(f"未知: {sub} ファイル")

    if n_uk_seen != n_uk:
        raise SystemExit(f"未知が合わない: {n_uk_seen} / {n_uk}")

    # 詰め替えで局面が増減していないこと (順序に依らない指紋で見る)
    if before.as_tuple() != after.as_tuple():
        raise SystemExit(f"詰め替えで中身が変わった: {before.as_tuple()} → {after.as_tuple()}")
    print(f"照合した局面数: {before.count:,}")


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print(__doc__)
        return 2
    rebuild(pathlib.Path(argv[1]), pathlib.Path(argv[2]), pathlib.Path(argv[3]))
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
