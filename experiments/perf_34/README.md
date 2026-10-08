# perf_34: F1 と `U_loop` の時間がどこで使われているかを、perf で切り分ける（記録試行ではない）

番号を取らず、`impl/` を作らず、タイムを `results/` にも README の記録表にも載せない。速くする工夫は入れない。測るだけ。

## 目的

記録 #34（`impl/34_unmove`、0:02:04）では、完走の 94% が2つの段に集まった（本走で F1 展開 58.53 秒、`U_loop` 56.82 秒。
`results/34_unmove/`）。次の大きな手は、次のどちらかになる。

- **メモリの待ちが大半なら**: 表の作りと局所性（番号の値域を詰める、処理の順をメモリの近さで揃える、など）
- **計算が大半なら**: 生成器の作り込み（分岐を減らす、番号の計算を生成器の中に入れる、など）

どちらも作り替えの規模が大きいので、先に段ごとの内訳を測る。どちらにするかはここでは決めず、根拠を添えて推す。

## 段の分け方

`impl/34_unmove` の写しに [`patches/perf_ctl.patch`](patches/perf_ctl.patch) を当てた腕で完走させる（[`build_arm.sh`](build_arm.sh)）。
パッチは `animal_shogi.py` だけを変える。C・ヘッダ・`Makefile`・`hot_layout.ld` は `impl/34_unmove` とバイト同一で、`.so` は #34 本走と
同じバイト列（sha256 の先頭 `572517006344`）。`impl/34_unmove` そのものは触らない。

- **F1 は起動した perf、`U_loop` は python に `-p` で付けた別の perf が数える。** どちらも `-D -1`（止めた状態で始める）と
  `--control fifo:` で、パッチが段の境界（`_profMark("F1_begin")` の直後と `_profMark("F1")` の直前、`U_init` の直後と `U_loop` の直前）で
  `enable` / `disable` を送り、perf の `ack` を待つ。1本の完走で2つの段を別々に数えられる
- 数える範囲は段の計時（`forward_summary.tsv` の F1、`retreat_summary.tsv` の `U_loop`）とほぼ同じ。F1 は Python 側の出し入れ
  （初見の後続を `array` に写す、など）も含む。`U_loop` は `dat/` への書き出し（`writeWLFilesForDepth`）と `smaps_rollup` の読みも含む
- パッチはほかに、`U_loop` で展開した局面（フロンティア）の延べ数をログに1行足し、`PERF_DUMP_DIR` があればベンチの入力を書き出す（下）。
  perf を付けない本ではパッチは何もしない（`PERF_CTL_*` を渡さない）
- 数えるのはユーザーとカーネルの両方（`perf_event_paranoid` が 1 なので自分のプロセスのカーネル側も数えられる）

## 使えたイベントと、使えなかったもの

回す前に、短い Python のループで確かめた（ログは残していない。数えた値は使わない）。

- perf 6.8.12。`kernel.perf_event_paranoid` は 1（本人が設定。再起動で戻る）。`kernel.nmi_watchdog` は 1
- **`perf stat -M TopdownL1` は使えなかった**（権限のエラー）。この CPU（Broadwell、ハイパースレッドが有効）での Topdown の式は、
  コアの2スレッドぶんを数える `*_ANY` のイベント（`CPU_CLK_UNHALTED.THREAD_ANY`、`INT_MISC.RECOVERY_CYCLES_ANY`）を使い、
  それには paranoid が 0 以下か権限が要る。**そこで第1段は、スレッドごとのイベントで同じ式を組んで出す**（下の式）。
  相方のスレッドが空いていればコアの値に近いが、同じものではない
- 汎用のカウンタは、`cycles` と `instructions`（固定カウンタ）のほかに **3つまで**多重化なしで載った。4つ載せると 66〜83% の多重化が
  起きた（NMI watchdog が汎用を1つ使っている）。そこでイベントを7つの組に分けて、組ごとに別の本で数える
- 使うイベント（どれも `perf list` にあり、短いループで数が出た）:

| 組 | イベント（`cycles`・`instructions` に足すもの） |
|---|---|
| T1 | `uops_issued.any`, `uops_retired.retire_slots`, `idq_uops_not_delivered.core` |
| T2 | `int_misc.recovery_cycles`, `idq_uops_not_delivered.cycles_0_uops_deliv.core`, `br_misp_retired.all_branches` |
| M1 | `cycle_activity.stalls_mem_any`, `cycle_activity.stalls_total`, `resource_stalls.sb` |
| M2 | `uops_executed.cycles_ge_1_uop_exec`, `uops_executed.cycles_ge_2_uops_exec`, `uops_executed.cycles_ge_3_uops_exec` |
| M3 | `rs_events.empty_cycles`, `br_inst_retired.all_branches`, `cycle_activity.stalls_l2_miss` |
| C1 | `mem_load_uops_retired.l1_miss`, `mem_load_uops_retired.l2_miss`, `mem_load_uops_retired.l3_miss` |
| C2 | `dtlb_load_misses.miss_causes_a_walk`, `dtlb_load_misses.walk_duration`, `dtlb_load_misses.stlb_hit` |

- `perf record` は `cycles` の標本（999 Hz）。関数ごとの割合は `perf report --sort dso,sym` のテキストだけを残す
  （見出しは出さない。`perf.data` は `runs/` に置いたままでコミットしない）。カーネルの記号の位置は `kptr_restrict` で読めず、
  カーネルの中の関数名は当てにならない（`[kernel]` の合計として読む）

## 式（回す前に決めた）

組ごとに別の本で数えるので、どの量も**その本の `cycles` で割ってから**組み合わせる（同じ仕事なので、1サイクルあたりで揃える）。
`slots` ＝ 4 × `cycles`（スレッドごと）。

- retiring ＝ `retire_slots` / slots（T1）
- frontend bound ＝ `idq_uops_not_delivered.core` / slots（T1）
- bad speculation ＝ (`uops_issued.any` − `retire_slots`) / slots（T1）＋ `recovery_cycles` / `cycles`（T2）
- backend bound ＝ 1 − 上の3つ
- memory bound ＝ backend bound × (`stalls_mem_any` ＋ `sb`) / (`stalls_total` ＋ `ge_1` − (IPC > 1.8 なら `ge_3`、でなければ `ge_2`)
  − (fetch latency > 0.1 なら `rs_events.empty_cycles`、でなければ 0) ＋ `sb`)。fetch latency ＝ `cycles_0_uops_deliv.core` / `cycles`（T2）。
  perf の `tma_memory_bound` と同じ形（`perf list -j` で読んだ）。core bound ＝ backend bound − memory bound
- 参考の「メモリの待ち」: `stalls_mem_any` / `cycles`（M1。読み込みが終わらずに止まったサイクルの割合）と `stalls_l2_miss` / `cycles`（M3）
- 局面1個あたり: F1 は展開した局面（`forward.tsv` の `n_in` の合計）、`U_loop` は展開した局面（パッチが足すログの行）と作った候補
  （`前任の候補：` の行）で割る
- 3本の中央値と範囲（最小〜最大）を出す。多重化が起きたら、その本の比率（`perf stat -x,` の5列目）を表に書く

## perf を使わない照らし合わせ

生成器だけを、キャッシュに乗る小さい集合の局面で回し（[`bench.c`](bench.c)・[`glue.c`](glue.c)・[`run_bench.sh`](run_bench.sh)）、
本物の F1・`U_loop` の1局面あたりと並べる。差は、メモリの待ちと、生成器の外の仕事（表を引く・書く、Python 側、`dat/` への書き出し）の
合計のおおよその上限になる。

- `glue.c` は `impl/34_unmove/animal_shogi.c` をそのまま取り込み、生成器の部分だけを回す関数を足したもの。`impl/34_unmove` の `Makefile` の
  gcc 行のまま `.so` にし、ベンチ本体が `dlopen` して呼ぶ（`experiments/gen_bench` と同じ条件）
  - F1: `nextBoardInvNormalNC` で後続を作り、後続ごとに `rankOf`（本物と同じ static inline）で番号を出す。本物の `nextBoardSeenNormal` から、
    発見済みの表・準備の配列・初見の後続の書き出しを除いたもの
  - `U_loop`: `unmoveCandidates` で候補を作り、候補ごとに `rankOf` で番号を出す。本物の `unmoveStep` から、手数の配列と残りの数の読み書き・
    決まった局面の書き出しを除いたもの
- 入力は2通り。ブロック（4,096 局面 ＝ 32 KiB）ごとに1周温めてから1周測る。5周まわして中央値と範囲
  - **order**: `dump` の本（`PERF_DUMP_DIR`）が書き出した、F1 の各ラウンドの入力と `U_loop` の各段のフロンティアの、真ん中の連続した
    4,096 局面（足りなければ全部）。並びは本物のまま。ラウンド（段）ごとの ns/局面に、そのラウンド（段）の局面数を掛けて足し、
    段の秒の見積もりにする
  - **random**: #34 本走の `dat/` から固定シードで一様に抜いた 262,144 局面（[`sample.py`](sample.py)）。並びを崩した場合

### 回す前に見た数（作りを確かめたときのもの）

ベンチの作りを確かめるとき、**random の入力で何度か回して値を見た**（ログは残していない）。最初は番号を `rankBoard`（番号にできる盤かの
検査と関数の呼び出しが乗る）で出していて F1 405 / `U_loop` 740 ns/局面、`rankOf` に替えて F1 311 と 258、`U_loop` 567 と 516 ns/局面
（同じ入力でも本ごとに 20% 近く振れた）。本物の F1（本走の 58.53 秒 ÷ 246,803,167 局面 ＝ 237 ns/局面）より、キャッシュに乗せた生成器だけの
ほうが重く出た。並びを崩したことが効いていると見て、本物の並びのままのブロック（order）を足した。下の見込みのうち random の行は、
この見た数から書いている。

## 条件

- 解析はどの本も `numactl --cpunodebind=0 --membind=0` で固定。perf 自身は固定しない。ベンチも同じ固定
- 各本の前に、ノード0の 2 MiB 以上の空きブロックが 16 GiB 以上あるか確かめて `logs/<ラベル>_hugefree.txt` に残す（門番と同じ下限）。
  足りなければ止めて本人に知らせる
- 回す順（[`run_all.sh`](run_all.sh)）: `base`（perf なし）→ `dump`（ベンチの入力を書き出す。段の秒は比べない）→ 3回 ×
  （T1・T2・M1・M2・M3・C1・C2・`record` を、回ごとに3つずつずらした順）→ ベンチ。完走は 26 本
- **perf を付けた本の秒は、記録とも門番とも比べない。** `base` の段の秒と並べて、perf の分の重さを出すだけ
- 回す前の負荷は load average と CPU 使用率の合計だけを残す

## 止める条件（回す前に決めた）

毎本その場で見て、どれかに掛かったら `dat/` を残して止める（[`run_one.sh`](run_one.sh)）:

- ノード0の空きが 16 GiB 未満（走らせずに止める。本人に知らせる）
- 解析が落ちた、または `U_loop` を数える perf が 0 以外で終わった
- オラクル174行（`tools/verify_log.py`）
- 答え（`experiments/gate_34_unmove/check_answer.py new`）: 全探索の側のファイルが #33 本走とバイト一致、ファイルの名前と件数、指紋
- `forward.tsv` の件数の列が `results/34_unmove/forward.tsv` と一致（[`check.py`](check.py)）
- `thp_fault_fallback` の前後差が 0、巨大ページが表と配列の全部に付いている（`check.py`。しきい値は門番 #34 の `new` と同じ）

参考に `dat/` の md5 一覧の sha256 を残す（#34 本走は `851de9569efc`。`experiments/sorted_compare_34/logs/identify.txt`）。判定には使わない。

## 見込み（回す前に書いた）

大きさは根拠のあるものだけ。根拠が薄いところは幅を広く取った。

| | F1 | `U_loop` | 根拠 |
|---|---|---|---|
| memory bound（式の値） | 15〜40% | 20〜50% | F1 は局面1つにつき、発見済みの表（107 MB）を後続の数（平均 3.8）だけ飛び飛びに引き、準備の配列（855 MB）を1回書く。`U_loop` は候補（平均 5.57。#34 本走の 578,723,910 ÷ 103,821,853）ごとに手数の配列（855 MB）を引く。どちらも LLC（35 MB）に乗らないが、局面ごとにまとめて先読みしている（#20 の形）。`U_loop` のほうが1局面あたりの飛び飛びの読みが多い |
| `stalls_mem_any` / `cycles` | 15〜45% | 20〜55% | 上と同じ |
| IPC | 0.9〜1.8 | 0.8〜1.6 | 生成器は分岐が多く、表引きの待ちが一部残る。`U_loop` のほうが待ちが多い |
| bad speculation | 10〜30% | 10〜30% | 生成器は駒の種類と盤の端で分岐する。`U_loop` はふるい（手数が未定か）の分岐がデータで決まる |
| 分岐の予測ミス / 局面 | 1〜4 | 2〜7 | F1 は後続 3.8 個の生成と、キャッチ・トライの早い出口。`U_loop` は候補 5.57 個の生成と、候補ごとのふるいの分岐（未定で残るのは 41%: 238,521,170 ÷ 578,723,910） |
| LLC のロードミス（`l3_miss`）/ 局面 | 0.3〜4 | 0.5〜6 | 飛び飛びに触る行は F1 で約 4.8 行、`U_loop` で約 5.6 行（奇数の段は残りの数も）。先読みが間に合えば、読み込みの命令は LFB で当たってミスに数えられないので、下は低く取った |
| dTLB のミスの歩き / 局面 | 0.1 未満 | 0.1 未満 | 表と配列は巨大ページに乗っている（門番 #34 で全部付いた） |
| perf の分の段の秒の増え（`base` と比べて） | stat ＋2% 以内、record ＋5% 以内 | 同じ | 数えるだけなら割り込みは無い。標本は 999 Hz |
| 多重化 | 起きない | 起きない | 組を3つずつにした |
| ベンチ order の ns/局面 | 本物の 237 ns/局面の 50〜100% | 本物の 547 ns/局面（56.82 秒 ÷ 103,821,853）の 50〜100% | 生成器の外の仕事（表・書き出し・Python）とメモリの待ちを除いたぶん軽い |
| ベンチ random の ns/局面 | 250〜320 | 500〜580 | 作りを確かめたときに見た数（上の節）。order より重い |

## 成果物

- `logs/console.log`（進行）、`logs/<ラベル>_*`（本ごとの生ログ: 段の秒、`perf stat` の CSV、`perf report` のテキスト、検査）
- `logs/bench.tsv`（ベンチ）、`logs/sample.txt`・`logs/blocks_index.tsv`（ベンチの入力）
- [`summary.py`](summary.py) が `logs/summary.txt` を作る
