# 実験 lever_scan_2: 174段ループの先読みと、展開の作業用配列（ふるい分けの回・2回目）

⚠️ **これは記録試行ではない。** 番号を取らず、`impl/` を作らず、タイムを `results/` にも
README の記録表にも載せない。候補のレバーをまとめて門番にかけ、**順位を付けるところまで**やる。
記録にするかどうか、何を束ねるかは結果を見て決める。記録にするときは、その回の門番で測り直す
（この回の数字を記録の証拠に流用しない。[`lever_scan`](../lever_scan/) と同じ運用）。

## 何を測るか

記録 #22（完走 0:03:09）の段の大きい順は F1 展開 77.7 s、P2 47.6 s、**174段ループ 27.3 s**、P4 20.5 s
（[#22 のノート](../../docs/records/22-in-memory.md)の「次」）。そこに挙げた候補のうち2つを測る。

**174段ループ（`retreatStep()`）の先読み。** 次の読みを数珠つなぎにしている。

```
frontier[i] → pred_off[q], pred_off[q+1] → pred[e] → cnt[p], dtm[p]
 (順に読む)       約 1 GB・ランダム         3.75 GB     約 100 MB / 約 247 MB・ランダム
```

どれも L3（この計測機は1ソケット 35 MiB）に載らず、次の番地が前の読みの値で決まる。
**#20 の前の P4_scatter と同じ形**で、あちらは2段の先読みで 57.31 → 12.92 秒になった
（[`lever_scan`](../lever_scan/)）。174段ループには先読みが入っていない。
確定する局面 244,120,467 個に対して 27.3 秒で、1個あたり約 112 ns（DRAM 往復1回ぶん程度。状況証拠で、未検証）。

**展開（F1）の作業用配列の使い回し。** F1 は毎ラウンド（74 ラウンド）、入力の写し `array("Q", unexp_boards)` と、
勝ち・負け・未知の受け皿3本 `array("Q", bytes(8)) * n` を新しく確保し、受け皿は件数ぶんの写しを取ってから足している。
延べ 1局面あたり 40 B × 246,803,167 ≒ 9.9 GB で、40 MB 級の確保は mmap されて毎回まっさらなページが来る。
#22 の本走の F1 のカーネル時間は 4.94 秒。#22 の門番で区切らない腕が遅かったのも F1・F6 のカーネル時間だった（機序は未分離）。

## 腕（6本）

どの腕も `impl/22_in_memory` の写しにパッチを当てて組む（[`make_arm.sh`](make_arm.sh)）。`impl/22_in_memory` は凍結物なので触らない。
パッチは [`patches/`](patches/) にあり、当てる順に並べたときの前の状態に対する unified diff。

| 腕 | パッチ | 変えるもの |
|---|---|---|
| `base` | instr | 何も変えない |
| `pf2` | instr → [`pf2`](patches/pf2.patch) | `retreatStep()` に2段の先読み。32 個先の q で `pred_off[q]`、16 個先の q で `pred[pred_off[q]]`（距離は #20 の `predScatter` と同じ。調整しない） |
| `pf3` | instr → [`pf3`](patches/pf3.patch) | `pf2` ＋ 3段目。8 個先の q の前任を**先頭から最大4本**（平均の入次数 3.80 を覆う固定値）本当に読み、その p の `dtm[p]` と、奇数段だけ `cnt[p]` を先読み |
| `hugeR` | instr → [`hugeR`](patches/hugeR.patch) | `pred` / `pred_off` / `cnt` / `dtm` を、索引と同じ `hugeAlloc()`（2 MiB 境界 ＋ `memset` の前に `MADV_HUGEPAGE`）で確保する。C に `hugeFill()` を足し、Python は ctypes の配列で包む。先読みは入れない |
| `reuse` | instr → [`reuse`](patches/reuse.patch) | F1 の受け皿3本を最初のラウンドで `BOARD_NUM_MAX` 件ずつ1回だけ確保して使い回す（0 埋めはその1回だけ）。入力の写しをやめて待ち行列の塊をそのまま渡し、件数ぶんの写しの代わりに memoryview から `frombytes` で足す。**待ち行列の区切り（500万）は変えない** |
| `all` | instr → pf3 → hugeR → reuse | 3つを重ねる |

先読みはヒントで、書く値を変えない。先読みのために本当に読む値（`frontier[i+k]`、`pred_off[q]`、`pred[e]`）は、
本処理と同じ範囲検査（`i+k < hi`、`q < n_all`、`e < e_end`、`p < n_uk`）を通してから読む。
範囲モード（`frontier == NULL`）は `q = i+k`。偶数段は `cnt` を触らない。

`reuse` で 0 埋めを外してよいのは、`expandRound()` が受け皿に `counts` の件数までしか書かず（`win[n_win++]` など）、
Python もそこまでしか読まないため。受け皿の中身は同じラウンドのうちに `catch_wins` / `try_loses` / `uk_all` へ
足し終えるので、後ろで保持されない。

**全腕共通の計装 [`instr`](patches/instr.patch)**（腕どうしでバイト同一。`base` にも入れる）:
- 全探索: 段ごとの minor fault を、ユーザー時間・カーネル時間と同じ組でラウンドをまたいで足し、
  `forward_summary.tsv` の末尾に `minflt_F0`〜`minflt_forward_total` を出す（`reuse` の判定に使う）
- 後退解析: `R_uk` のあと（どの区間にも入らない）で `/proc/self/smaps_rollup` を読み、
  `retreat_summary.tsv` の末尾に `anonhuge_loop_kB` などを出す（174段ループの配列が生きているうちの巨大ページ。`hugeR` の証拠）

### 効いたことの確認（回す前に機械で取った）

[`check_arms.sh`](check_arms.sh) の出力（[`logs/warnings.txt`](logs/warnings.txt)）:

| 腕 | `-Wall -Wextra` の警告 | `retreatStep` の先読み命令 | `call madvise@plt` | `hugeFill` | `searchNext` の毎ラウンドの確保 |
|---|---|---|---|---|---|
| `base` | 0 | 0 | 3 | 無し | 4 行 |
| `pf2` | 0 | 4 | 3 | 無し | 4 行 |
| `pf3` | 0 | 5 | 3 | 無し | 4 行 |
| `hugeR` | 0 | 0 | 4 | あり | 4 行 |
| `reuse` | 0 | 0 | 3 | 無し | 0 行 |
| `all` | 0 | 5 | 4 | あり | 0 行 |

先読み命令の数は、コンパイラが範囲モードと frontier の経路を分けたり、まとめたりするので、段の数と一致しない
（`pf3` の 5 は `dtm` / `cnt` の1バイト単位の2つと、`pred_off` / `pred` の3つ）。

[`smoke.py`](smoke.py) の出力（[`logs/smoke.txt`](logs/smoke.txt)）: 6腕を `BOARD_NUM_MAX` ＝ 2000 で組み、全探索を
40 ラウンドで打ち切って後退解析まで回した。**`dat/` の中身、`buildPredecessors()` が返した `pred` / `pred_off` のバイト列、
ラウンドごとの件数が、6腕とも `base` と一致した**（`hugeR` で配列の中身と並びが変わらないことを含む）。

## 単位と配置

**単位は完走**（空の `dat/` から `python3 ./animal_shogi.py` を1本）。#22 から後退解析はファイルを読まないので、
後退解析だけを回すには driver が要る。完走でも1本3分強なので、完走で揃える。
どの本も `numactl --cpunodebind=0 --membind=0` で片ノードに固定する（CLAUDE.md）。

**配置は 6×6 の Williams 型ラテン方陣**（[`run_all.sh`](run_all.sh)。1行目 `0 1 5 2 4 3`、以後の行は +1 ずつ。
番号は `base pf2 pf3 hugeR reuse all`）。各腕は各位置（1〜6番目）にちょうど1回ずつ来る。
ブロックの中で隣り合う前後の順序対（30通り）も、どれもちょうど1回ずつ来る
（巡回型だと直前の腕が固定される。`lever_scan` の README が挙げた弱点）。ブロックをまたぐ前後は揃えていない。

| ブロック | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|
| 1 | base | pf2 | all | pf3 | reuse | hugeR |
| 2 | pf2 | pf3 | base | hugeR | all | reuse |
| 3 | pf3 | hugeR | pf2 | reuse | base | all |
| 4 | hugeR | reuse | pf3 | all | pf2 | base |
| 5 | reuse | all | hugeR | base | pf3 | pf2 |
| 6 | all | base | reuse | pf2 | hugeR | pf3 |

計36本、見込みは約2時間10分。**機械時間の上限は4時間**で、次の本を始める前に「経過 ＋ 5 分 > 4 時間」なら止める。
途中で腕を足したり、結果を見て本数を増やしたりしない。

## 判定に使う量

- 先読み・巨大ページの腕: `retreat_summary.tsv` の `loop174`（生値）と、そのユーザー時間・カーネル時間の内訳
  （`R_dtm` → `R_loop` の境界の差）
- `reuse`: `forward_summary.tsv` の F1 と `utime_F1` / `stime_F1` / `minflt_F1`
- 完走の壁時計も出すが、**判定には使わない**（雑音が大きい。CLAUDE.md）

比較は **6本**（`base` に対して5本と、`pf3 − pf2` の1本）。p 値と 95% 区間はどれも個々の比較についての値で、
**多重比較は補正していない**。区間で判断しても多重比較の問題は解消しない。

## 事前登録（回す前に書いた）

大きさは、根拠のあるものだけ書く。

| 腕 | 狙う段 | 予測 | 触らないはずの段（対照） |
|---|---|---|---|
| `pf2` | `loop174` | 下がる（ほぼユーザー時間から） | F0〜F6、P0〜P4 |
| `pf3` | `loop174` | `pf2` より下がる（弱い予測） | 同上 |
| `hugeR` | `loop174`、P4 | 下がる。ただし P4 は `pred` / `pred_off` の確保（`memset`）を含むので、巨大ページのためのコンパクション待ちでカーネル時間が増える向きもありうる。`anonhuge_loop_kB` は 4,972,544 kB 以上（4配列を 2 MiB に切り上げた 2,428 ページ）、ほかの腕は 0 | F0〜F6、P2_loop（P2_alloc は `cnt` の確保を含むので動きうる） |
| `reuse` | F1、`stime_F1`、`minflt_F1` | 下がる。F1 の下がり幅は大きくても、`stime_F1`（#22 の門番の chunk 腕で 5.00 秒）と 0 埋めのユーザー時間 1〜2 秒の和ほど。`minflt_F1` の減りは、延べの確保量（9.9 GB ÷ 4 KiB）から見て最大約 241 万回 | P0〜P4、`loop174`。F2 は書き方を変えた（`extend` → `frombytes`）ので向き未知。F6 も向き未知 |
| `all` | — | 3腕（`pf3` / `hugeR` / `reuse`）の差の和と比べる（足し算になるか） | — |
| 全腕 | `dat/` | 36本とも、md5 一覧の sha256 が `results/22_in_memory/bytecompare.txt` の値（`f18f3075…`）と一致 | — |

### 測る前の懸念 — P4 ほど効かないかもしれない理由

- 行き先が1段多い。2段の先読み（`pf2`）では `cnt[p]` / `dtm[p]` の待ちが残る
- 深い手数の段は数件〜数千件しかなく、先読みの距離が稼げない。効くのは確定数の多い序盤の段のはず
- 待ちの一部が番地の翻訳（TLB）かもしれない。`pred` / `pred_off` は Python の `array` で 4 KiB ページのまま
  （#21 で巨大ページにしたのは索引と発見済み表だけ。#21 の P2 の待ちは番地の翻訳だった）

## 止める条件

どれかに掛かったら、そこで止めて報告する（結果の解釈に進まない）。[`run_one.sh`](run_one.sh) が毎本その場で見て、
全部そろったあとに [`stop_rule.py`](stop_rule.py) がもう一度まとめて見る。

1. どれかの本の `dat/` の md5 一覧の sha256 が、`results/22_in_memory/bytecompare.txt` に記録された値と一致しない
   （`dat/` 本体は git に無いので、その手順で出した値で照合する）。またはオラクル174行で落ちた
2. どれかの本の `forward.tsv` の件数の列（`n_in`・`n_win`・`n_lose`・`n_uk`・`n_new_post`）が
   `results/22_in_memory/forward.tsv` と違う
3. 途中で落ちた本がある（再開せず、その本の扱いを報告する）
4. どれかの本で `/proc/vmstat` の `thp_fault_fallback` の前後差が 0 でない（巨大ページが頼んだぶん付かない）。
   **下の「1回目の起動を止めた」のあとで足した条件**

## 1回目の起動を止めた — ノード0のメモリが断片化していて、巨大ページが付かなかった

準備のコミットのあと、2026-09-26 13:28（UTC）に一度起動した。1本目の `b1a_base` は答えの検査
（オラクル・`dat/` のバイト一致・件数の列）をすべて通ったが、**巨大ページが頼んだぶん付かなかった**。

| | #21・#22 の門番 | `b1a_base`（1回目の起動の1本目） |
|---|---|---|
| `thp_fault_fallback`（前後差） | 0 | **909** |
| `compact_stall` / `compact_fail` | 0 / 0 | **4,369 / 2,980** |
| 索引の `AnonHugePages`（8,388,608 kB が全部） | 全部 | **6,801,408 kB** |
| 発見済み表の `AnonHugePages`（4,194,304 kB が全部） | 全部 | **3,919,872 kB** |
| P1 / P2 | 7.35 / 46.4 秒（#22 の門番の chunk） | **10.86 / 49.68 秒** |

2本目の途中で見たノード0は、32 GB のうちページキャッシュが 12 GB、空きが 12.9 GB で、
2 MiB 以上のまとまった空きブロックは Normal と DMA32 の域を合わせて約 4.6 GiB だった（`/proc/buddyinfo`。
2本目が使っているぶんを含む）。索引（8 GiB）を全部巨大ページにするには、コンパクションでまとめ直す必要があり、
それが 2,980 回失敗した。この状態では、巨大ページを頼む腕（とくに 5 GB を足して頼む `hugeR` と `all`）の差が、
レバーの効果ではなく断片化の進み方を測ることになる。答えの検査で決めた止める条件1〜3には掛かっていないが、
結果を解釈する前に止めた（2本目の `b1b_pf2` の途中）。生ログは [`logs/aborted/`](logs/aborted/) にある。

ページキャッシュを落としてメモリをまとめ直し（`sync; echo 3 > /proc/sys/vm/drop_caches; echo 1 > /proc/sys/vm/compact_memory`。
一回きりの操作で、THP などの設定は変えていない）、**36本を最初から回し直す。** 腕・配置・予測・判定の量は変えない。
落としたあとのノード0は、ページキャッシュが 0.37 GB、2 MiB 以上の空きブロックが約 17.6 GiB だった
（回す直前の `buddyinfo` と `meminfo` は `logs/console.log` の冒頭に残る）。
変えたのは次の2つだけ。
- 止める条件4を足した
- [`run_all.sh`](run_all.sh) が回す前のノード0の `buddyinfo` と `meminfo` を `logs/console.log` に残すようにした

## 集計

表は生ログから組む（手で書かない）。

```bash
python3 experiments/lever_scan_2/stop_rule.py        # 止める条件
python3 experiments/lever_scan_2/summary.py          # 狙う段・内訳・対照・巨大ページ・完走（参考）
python3 experiments/lever_scan_2/additivity.py       # all と 3腕の差の和
python3 experiments/gate_stats.py lever_scan_2 forward base pf3:pf2
python3 experiments/gate_stats.py lever_scan_2 spans base pf3:pf2
```

## ファイル

| | |
|---|---|
| [`make_arm.sh`](make_arm.sh) | 腕のソースを組んでビルドする。`make_arm.sh <腕> <出力先>` |
| [`patches/`](patches/) | `instr`（全腕共通の計装）・`pf2`・`pf3`・`hugeR`・`reuse` |
| [`check_arms.sh`](check_arms.sh) | 警告と、効いたことの確認を数える（出力は `logs/warnings.txt`） |
| [`smoke.py`](smoke.py) | 6腕を小さく回して `base` と比べる（出力は `logs/smoke.txt`） |
| [`run_one.sh`](run_one.sh) / [`run_all.sh`](run_all.sh) | 完走を1本測って検査する / 36本を上の順で回す（進行は `logs/console.log`） |
| [`stop_rule.py`](stop_rule.py) / [`summary.py`](summary.py) / [`additivity.py`](additivity.py) | 止める条件 / README の表 / 足し算の確認 |
| [`lib.sh`](lib.sh) | 周波数の標本・vmstat・md5 一覧（`gate_22_in_memory` の写し） |
| [`logs/aborted/`](logs/aborted/) | 止めた1回目の起動の生ログ（1本と、進行ログ・バイト比較）。進行ログの「回す前の負荷」は load average だけを残し、プロセスの一覧・稼働日数・ログイン人数は公開しないので消した |
