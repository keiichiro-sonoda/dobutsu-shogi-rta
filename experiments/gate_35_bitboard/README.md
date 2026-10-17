# 門番 #35: 全探索の生成器をビットボード型にした `impl/35_bitboard` を、#34 と完走で比べる（記録試行の門番）

`old` ＝ `impl/34_unmove`（記録 #34）、`new` ＝ `impl/35_bitboard`。どちらもその実装の `Makefile` でビルドする（[`build_arm.sh`](build_arm.sh)）。
作りは [`gate_34_unmove`](../gate_34_unmove/) を写した。

## 何を比べるか

`impl/35_bitboard` は `impl/34_unmove` に [`experiments/bitboard_gen/patches/bb_nibble.patch`](../bitboard_gen/patches/bb_nibble.patch) を当てただけの実装。
変わるのは全探索の生成器 `nextBoardInvNormalNC()` と、行き先の表・それを作る `dstTableBuild()`（`.so` を読み込んだときに1回走る）だけで、
`.py`・`Makefile`・`hot_layout.ld`・逆向きの生成器・`nextBoardSeenNormal()`・`normalBoard()`・`invBoard()`・ランクは #34 とバイト同一
（[`tests/test_impl_35_bitboard.py`](../../tests/test_impl_35_bitboard.py)）。

生成器は、マスの集合をビットで持ち、表引きとビット演算で行き先の集合を作って `ctz` で1つずつ取り出す。手番側の駒のマスと行き先を番号の小さい順に
取り出すので、**後続の列は並びまで #34 と同じ**。だから全探索の待ち行列も後退解析の採番順も変わらず、`dat/` は #34 とバイト一致するはず。

## 回す前に確かめたこと

- **`impl/35_bitboard` の `.so` は、`bitboard_gen` の腕 `bb_nibble` の `.so` とバイト一致した**（どちらも sha256 の先頭 `3b37ebdc6230`。C もバイト一致）。
  だから `bitboard_gen` の全局面の一致の検査（到達可能な全 246,803,167 局面で、戻り値・後続の列の並び・キャッチ抜きの数が #34 と同じ。
  [`logs/verify_bb_nibble.txt`](../bitboard_gen/logs/verify_bb_nibble.txt)）が、そのまま `impl/35_bitboard` に当たる
- `bitboard_gen` の `check_asm.py` を `impl/35_bitboard` の `.so` に当てた（[`logs/asm_impl35.txt`](logs/asm_impl35.txt)）: 生成器の命令 297（#34 は 374）、`tzcnt` 5、
  条件分岐 19（#34 は 37）、`-Wall -Wextra` の警告 0。#34 の分岐の形（623・625・626・628・629・643・646・657・659・660・661・662 行に当たるもの）はどれも残っていない
- `tests/test_impl_35_bitboard.py`: 打ち切った全探索の出力と、そのあとの後退解析の `dat/` が全ファイル #34 とバイト一致。詰め物の検査も通る
- **熱い関数の置き場所のずれ**（`nm`。`.text.hot_layout` の中。左が #34、右が #35）: 生成器が 0x5d0 → 0x482 バイト（−334）に縮み、後ろの関数はどれも
  **−0x140（−320 バイト、64 バイトの区切り5つ）**ずれる。ページ（4 KiB）の中の位置も変わる

  | 関数 | #34 | #35 | 段 |
  |---|---|---|---|
  | `invBoard`・`nextBoardInvNormal` | 0x2000・0x20c0 | 同じ | |
  | `nextBoardInvNormalNC` | 0x2540（0x5d0 バイト） | 0x2540（0x482 バイト） | F1 |
  | `nextBoardSeenNormal`・`expandRound` | 0x2b40・0x3040 | 0x2a00・0x2f00 | F1 |
  | `unmoveCandidates`・`unmoveInit`・`unmoveStep`・`unmoveDraws` | 0x3340・0x42c0・0x43c0・0x48c0 | 0x3200・0x4180・0x4280・0x4780 | 後退解析 |

## 判定の量（回す前に決めた）

- **主: 完走の秒**（`/usr/bin/time -v` の Elapsed）の `new − old`。平均の差と Welch の 95% 区間（[`stop_rule.py`](stop_rule.py)。比較は1対1の1本）
- 並べて出す（判定には使わない。[`summary.py`](summary.py)）: 全探索の合計・F1・F1 のユーザー時間とカーネル時間・F5・F6、後退解析の合計と `U_init`・`U_loop`・`U_draw`・`U_uk`、
  ユーザー時間・カーネル時間・minor fault・ピーク RSS

## 記録にするかの取り決め（回す前に決めた）

これは作りの変更ではなく速さだけのレバーなので、#34 とは違い、確定しないときは記録にしない（#29・#31 と同じ扱い）。

- 完走の `new − old` の区間の上端が 0 より下 → **本走して記録にする**
- 区間が 0 をまたぐ → **本走せずに止めて報告する**（欠番にするかは本人が決める）
- 区間の下端が 0 より上（遅くなった）→ **本走せずに止めて報告する**

## 配置と条件

- 単位は完走（空の `dat/` から1本）。`old new new old` を3ブロック、計12本（各腕6本。[`run_all.sh`](run_all.sh)）
- どの本も `numactl --cpunodebind=0 --membind=0`。各本の前にノード0の 2 MiB 以上の空きを読んで `logs/<ラベル>_hugefree.txt` に残し、16 GiB に満たなければ走らせずに止める
- **門番の前に1本、`new` を完走させて答えの検査を通す**（[`run_trial.sh`](run_trial.sh)。計時には使わない。通らなければ `run_all.sh` は回さない）。
  この本では `dat/` 全213ファイルを #34 本走の `dat/` と `diff -rq` でも比べる
- 回す前に、CPU 使用率（全 CPU）が 3% 以下（ほかの計算が動いていない）ことを確かめ、load average と CPU 使用率だけを残す。`impl/34_unmove`・`impl/35_bitboard` に `__pycache__` が無いこと

## 答えの検査（毎本。[`run_one.sh`](run_one.sh)）

**今回はバイト一致で見る。**

- 両腕: `dat/` の md5 一覧の sha256 が **#34 本走と同じ（`851de9569efc…`）**（[`check_answer.py`](check_answer.py)。基準は
  [`sorted_compare_34` の `logs/identify.txt`](../sorted_compare_34/logs/identify.txt) の #34 の値。`perf_34`・`perf_branch_34` の本もこの値だった）
- 両腕: オラクル174行。`forward.tsv` の件数の列が `results/34_unmove/forward.tsv` と一致
- 両腕: `thp_fault_fallback` の前後差が 0、巨大ページが表と配列に付いている（しきい値は両腕とも門番 #34 の `new` と同じ）

## 止める条件（回す前に決めた）

1. 答えの検査が1本でも外れる（**`dat/` の md5 一覧の sha256 が #34 本走と違うことも含む**。順番が同じはずなのに一致しないなら、一致の検査が見落とした違いがある）
2. `impl/35_bitboard` の `.so` が `bb_nibble` の `.so` とバイト一致せず、かつ全局面の一致の検査を回し直して1局面でも外れる（上で一致を確かめたので、ここは掛からない）
3. 上の取り決めで「確定しない」「遅くなった」
4. どれかの本で `thp_fault_fallback` の前後差が 0 でない、または巨大ページが表と配列に付かない
5. 巨大ページに使える空きが下限に満たない（走らせずに止めて本人に知らせる。キャッシュは本人が落とす）

## 予測（回す前に書いた）

| | 予測（`new − old`） | 根拠 |
|---|---|---|
| **完走の秒** | **−6〜−11 秒。区間の上端は 0 より下** | `bitboard_gen` の生成器だけのベンチで order の cycles −158.1 / 局面、F1 の秒への換算 −11.45 秒。過去に生成器だけの換算が門番で出た割合は 75〜83%（`gen_bench` → #26）なので −8.6〜−9.5 秒が中心。置き場所のずれ（下）の分を幅に足した |
| F1 | −6〜−11 秒。ほぼ全部ユーザー時間から（カーネル時間は ±0.3 秒） | 生成器の仕事が減るだけで、ページを用意する仕事（カーネル）は同じ |
| F5・F6 | ±0.5 秒 | コードは同じ |
| 全探索の合計 | F1 と同じ大きさ | F1 以外の段はコードが同じ |
| 後退解析の合計・`U_init`・`U_loop`・`U_draw`・`U_uk` | **変わらない見込み。ただし置き場所のずれで ±1 秒程度は動きうる** | 後退解析はコードとして変わらず、F1 から渡す列も中身と並びが同じ。ただし `unmoveCandidates`〜`unmoveDraws` は −320 バイトずれる（#33 のノートの「熱い関数そのものを変えたときのずれは固定できない」。#32 では命令が同じ段が置き場所だけで ＋0.63 秒動いた） |
| `nextBoardSeenNormal`・`expandRound`（F1 の中） | 置き場所が −320 バイトずれる。F1 の差に混ざる（分けられない） | 同上 |
| minor fault・ピーク RSS・カーネル時間の合計 | ほぼ変わらない（±0.5%） | 行き先の表は 16 × 12 × 8 ＝ 1,536 バイトの `.bss` |
| `dat/` | 12本とも #34 本走と md5 一覧が同じ。門番の前の1本は `diff -rq` でも一致 | 後続の列が並びまで同じ |
