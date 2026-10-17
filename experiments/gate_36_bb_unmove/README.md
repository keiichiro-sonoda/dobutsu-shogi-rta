# 門番 #36: 後退解析の逆向きの生成器をビットボード型にした `impl/36_bb_unmove` を、#35 と完走で比べる（記録試行の門番）

`old` ＝ `impl/35_bitboard`（記録 #35）、`new` ＝ `impl/36_bb_unmove`。どちらもその実装の `Makefile` でビルドする（[`build_arm.sh`](build_arm.sh)）。
作りは [`gate_35_bitboard`](../gate_35_bitboard/) を写した。

## 何を比べるか

`impl/36_bb_unmove` は `impl/35_bitboard` に [`experiments/unmove_gen/patches/bb_unmove.patch`](../unmove_gen/patches/bb_unmove.patch) を当てただけの実装。
変わるのは逆向きの生成器の下請け（`unmovePiece`・`unmoveRaw`、くくり出した `unmoveCaptures`）と、表を作る `unmoveTableBuild`・`unmoveSrcTableBuild` だけで、
`unmoveCandidates`・`unmoveEmit`・`unmoveStep`・全探索の側・`normalBoard()`・`invBoard()`・ランク・`.py`・`Makefile`・`hot_layout.ld` は #35 とバイト同一
（[`tests/test_impl_36_bb_unmove.py`](../../tests/test_impl_36_bb_unmove.py)）。

逆向きの生成器は、元のマスの候補を「表 ∧ 空きマス ∧ ¬（戻すと相手のライオンに利くマス）」のビット集合で出し、X の駒（直前に指した側）のマスもビット集合で取り出す。
元のマスは番号の大きい順（`lzcnt`）に、成りを戻す候補はほかのあとに出すので、**前任の候補の列は並びまで #35 と同じ**。だから後退解析が局面を決める順も変わらず、
`dat/` は全探索の側も後退解析の側も #35 とバイト一致するはず。

## 回す前に確かめたこと

- **`impl/36_bb_unmove` の `.so` は、`unmove_gen` の腕 `bb_unmove` の `.so` とバイト一致した**（どちらも sha256 の先頭 `c7106b9e0aaf`。C もバイト一致）。
  だから `unmove_gen` の全局面の一致の検査（到達可能な全 246,803,167 局面で、候補の数と列が並びまで #35 と同じ。
  [`logs/verify_bb_unmove.txt`](../unmove_gen/logs/verify_bb_unmove.txt)）と、完走の答え合わせ（`dat/` の md5 一覧が #35 本走と同じ）が、そのまま `impl/36_bb_unmove` に当たる
- `unmove_gen` の `check_asm.py` を `impl/36_bb_unmove` の `.so` に当てた（[`logs/asm_impl36.txt`](logs/asm_impl36.txt)。`unmove_gen` の `logs/asm_bb_unmove.txt` と同じ中身）:
  `unmoveCandidates` の命令 1,093（#35 は 981）、`tzcnt` 6・`lzcnt` 4、条件分岐 88（#35 は 129）、`-Wall -Wextra` の警告 0。狙った分岐（元のマスが空いているか・盤の端・
  端の回り込み・X の駒か・駒の種類の `switch`・指し手の表のループ・戻した先から利くか）の形はどれも残っていない
- `tests/test_impl_36_bb_unmove.py`: 打ち切った全探索の出力と、そのあとの後退解析の `dat/` が全ファイル #35 とバイト一致。展開した局面とその前任の候補を q にした
  逆向きの生成器の出力が #35 と並びまで同じ。詰め物の検査も通る。`CLAUDE.md` の「次の実装で必ず直すもの」は空だった
- **熱い関数の置き場所のずれ**（`nm`。`.text.hot_layout` の中。左が #35、右が #36）: `unmoveCandidates` が 0xf7a → 0x1183 バイト（＋521）に伸び、後ろの3つは
  **＋0x240（＋576 バイト、64 バイトの区切り9つ）**ずれる。前に並ぶ全探索の関数は1つも動かない

  | 関数 | #35 | #36 | 段 |
  |---|---|---|---|
  | `invBoard`・`nextBoardInvNormal`・`nextBoardInvNormalNC` | 0x2000・0x20c0・0x2540 | 同じ | F1 |
  | `nextBoardSeenNormal`・`expandRound` | 0x2a00・0x2f00 | 同じ | F1 |
  | `unmoveCandidates` | 0x3200（0xf7a バイト） | 0x3200（0x1183 バイト） | 後退解析 |
  | `unmoveInit`・`unmoveStep`・`unmoveDraws` | 0x4180・0x4280・0x4780 | 0x43c0・0x44c0・0x49c0 | 後退解析 |

- **`.bss` の並び**: 新しい表3つ（`g_uatk`・`g_upromo`・`g_usrc`、各 1,536 バイト）が `.bss` の頭に入り、ほかの変数（`g_xatt`・`g_dst`・`g_att`・ランクの表など）は
  どれも **＋0x1200（＋4,608 バイト）**ずれる。64 バイトの区切りの中の位置は変わらないが、4 KiB のページの中の位置は ＋0x200 変わる。全探索の段もランクの表と
  `g_dst`・`g_att` を引くので、全探索の側がこのずれで動きうる

## 判定の量（回す前に決めた）

- **主: 完走の秒**（`/usr/bin/time -v` の Elapsed）の `new − old`。平均の差と Welch の 95% 区間（[`stop_rule.py`](stop_rule.py)。比較は1対1の1本）
- 並べて出す（判定には使わない。[`summary.py`](summary.py)）: 全探索の合計・F1・F1 のユーザー時間とカーネル時間・F5・F6、後退解析の合計と `U_init`・`U_loop`
  （ユーザー時間とカーネル時間）・`U_draw`・`U_uk`、ユーザー時間・カーネル時間・minor fault・ピーク RSS

## 記録にするかの取り決め（回す前に決めた）

速さだけのレバーなので、#35 と同じ扱い。

- 完走の `new − old` の区間の上端が 0 より下 → **本走して記録にする**
- 区間が 0 をまたぐ → **本走せずに止めて報告する**（欠番にするかは本人が決める）
- 区間の下端が 0 より上（遅くなった）→ **本走せずに止めて報告する**

## 配置と条件

- 単位は完走（空の `dat/` から1本）。`old new new old` を3ブロック、計12本（各腕6本。[`run_all.sh`](run_all.sh)）
- どの本も `numactl --cpunodebind=0 --membind=0`。各本の前にノード0の 2 MiB 以上の空きを読んで `logs/<ラベル>_hugefree.txt` に残し、16 GiB に満たなければ走らせずに止める
- **門番の前に1本、`new` を完走させて答えの検査を通す**（[`run_trial.sh`](run_trial.sh)。計時には使わない。通らなければ `run_all.sh` は回さない）。
  この本では `dat/` 全213ファイルを #35 本走の `dat/` と `diff -rq` でも比べる
- 回す前に、CPU 使用率（全 CPU）が 3% 以下（ほかの計算が動いていない）ことを確かめ、load average と CPU 使用率だけを残す。`impl/35_bitboard`・`impl/36_bb_unmove` に `__pycache__` が無いこと

## 答えの検査（毎本。[`run_one.sh`](run_one.sh)）

**バイト一致で見る。**

- 両腕: `dat/` の md5 一覧の sha256 が **#35 本走と同じ（`851de9569efc…`。#34 本走とも同じ値）**（[`check_answer.py`](check_answer.py)。基準は
  [`results/35_bitboard/bytecompare.txt`](../../results/35_bitboard/bytecompare.txt) の #35 の値）
- 両腕: オラクル174行。`forward.tsv` の件数の列が `results/35_bitboard/forward.tsv` と一致
- 両腕: `thp_fault_fallback` の前後差が 0、巨大ページが表と配列に付いている（しきい値は両腕とも門番 #34 の `new`・門番 #35 と同じ。配列は変わらない）

## 止める条件（回す前に決めた）

1. 答えの検査が1本でも外れる（**`dat/` の md5 一覧の sha256 が #35 本走と違うことも含む**。並びが同じはずなのに一致しないなら、一致の検査が見落とした違いがある）
2. `impl/36_bb_unmove` の `.so` が `bb_unmove` の `.so` とバイト一致せず、かつ全局面の一致の検査を回し直して1局面でも外れる（上で一致を確かめたので、ここは掛からない）
3. 上の取り決めで「確定しない」「遅くなった」
4. どれかの本で `thp_fault_fallback` の前後差が 0 でない、または巨大ページが表と配列に付かない
5. 巨大ページに使える空きが下限に満たない（走らせずに止めて本人に知らせる。キャッシュは本人が落とす）

## 予測（回す前に書いた）

| | 予測（`new − old`） | 根拠 |
|---|---|---|
| **完走の秒** | **−8〜−13 秒。区間の上端は 0 より下** | `unmove_gen` の生成器だけのベンチで order の cycles −444.0 / 局面（−464.8〜−430.2）、`U_loop` の秒への換算 −13.49 秒（−14.13〜−13.07）。過去に生成器だけの換算が門番で出た割合は #35 で 90%、`gen_bench` → #26 で 75〜83%。それを当てると −10.1〜−12.1 秒が中心。置き場所のずれ（下）の分を両側に足した |
| `U_loop` | −8〜−13 秒。ほぼ全部ユーザー時間から（カーネル時間は ±0.3 秒） | 生成器の仕事が減るだけで、手数の配列と残りの数の読み書き・書き出しは同じ。`perf_34` で `U_loop` のメモリの待ちは小さく（memory bound 8.1%）、予測ミスを減らした分は隠れにくい |
| `U_init`・`U_draw`・`U_uk` | ±0.5 秒 | コードは同じ。`unmoveInit`・`unmoveDraws` が ＋576 バイトずれる（#35 では −320 バイトのずれで後退解析の段は ±0.01 秒） |
| 全探索の合計・F1・F5・F6 | ±1 秒（変わらない見込み） | 全探索の関数はコードも番地も同じ。ただし `.bss` の変数（ランクの表・`g_dst`・`g_att`）が ＋4,608 バイトずれ、ページの中の位置が変わる。64 バイトの区切りは同じなので、キャッシュの行の分かれ方は変わらない |
| minor fault・ピーク RSS・カーネル時間の合計 | ほぼ変わらない（±0.5%） | 新しい表は 3 × 16 × 12 × 8 ＝ 4,608 バイトの `.bss` |
| `dat/` | 13本とも #35 本走と md5 一覧が同じ。門番の前の1本は `diff -rq` でも一致 | 前任の候補の列が並びまで同じ |
