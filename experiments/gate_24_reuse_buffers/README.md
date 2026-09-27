# 門番 #24: 展開の作業用配列を使い回す（記録試行ではない）

`impl/24_reuse_buffers` は、全探索の展開（F1。`searchNext()`）で毎ラウンド新しく確保していた作業用配列をやめた。

| | #23 まで | #24 |
|---|---|---|
| 勝ち・負け・未知の受け皿3本 | 毎ラウンド `array("Q", bytes(8)) * n` で新しく確保し 0 で埋める | 最初のラウンドで `BOARD_NUM_MAX` 件ずつ1回だけ確保し、以後は上書き |
| 入力 | 待ち行列の塊を `array("Q", ...)` で写してから渡す | 塊のバッファをそのまま渡す |
| 受け皿からの取り出し | 件数ぶんのスライス（写し）を作ってから足す | `memoryview` で見て `frombytes` で足す |

コードは [`lever_scan_2`](../lever_scan_2/)（記録ではない）の [`reuse.patch`](../lever_scan_2/patches/reuse.patch) のまま。
lever_scan_2 は6腕を `base`（#22 ＋ 計装）に対して引いていて、多重比較は未補正。選んだ腕の効果は上に偏っている
可能性がある。この門番で、記録にする版そのものを1対1で測り直す。

## 腕と配置

| 腕 | 中身 |
|---|---|
| `old` | `impl/23_loop_prefetch` |
| `new` | `impl/24_reuse_buffers`（`animal_shogi.py` の `searchNext()` だけが違う。C・`.h`・`Makefile` はバイト同一） |

2腕の `.so` はバイト同一のはずで、[`build_arm.sh`](build_arm.sh) が毎本 `.so` の sha256 の先頭を進行ログに出す。
関数の番地がずれて別の段が動くことは無いはず（#23 では P2 の関数が 208 バイトずれた）。

単位は完走（空の `dat/` から `python3 ./animal_shogi.py` を1本）。変えたのは全探索だけだが、後退解析が動かないことも
同じ本で見る。`old new new old` を3ブロック、計12本（各腕6本）。どの本も `numactl --cpunodebind=0 --membind=0` で
ノード0に固定する（[`run_all.sh`](run_all.sh)）。

**各本の前に、ノード0の 2 MiB 以上の空きブロック（`/proc/buddyinfo` の order 9 以上）が 16 GiB 以上あるかを見る**
（[`run_one.sh`](run_one.sh)。記録は `logs/<ラベル>_hugefree.txt`）。足りなければその本を走らせずに止める。
起動する前に空きを確かめるとき、キャッシュを落とす前と後には [`free_snapshot.sh`](free_snapshot.sh) で
`logs/free_<名前>.txt` に残す（#23 では、起動する前に手で読んだ値と落とした直後の値が残らなかった）。

## 判定に使う量

**F1**（`forward_summary.tsv` の生値）と、その `utime_F1` / `stime_F1`（[`f1_split.py`](f1_split.py)）。
minor fault は `time.txt` の合計で見る（段ごとの minor fault の計装は入れていない）。比較は `old` 対 `new` の1本だけ。
段ごとの全表は `gate_stats.py`（`forward` / `spans`）。完走の壁時計も出すが、判定には使わない。

## 止める条件（[`stop_rule.py`](stop_rule.py)）

どれかに掛かったら、本走の前に止めて報告する。

1. どれかの本の `dat/` が #23 本走とバイト一致しない（md5 一覧の sha256 を
   `results/23_loop_prefetch/bytecompare.txt` の値と照合）、件数の列（`n_in`・`n_win`・`n_lose`・`n_uk`・`n_new_post`）が
   `results/23_loop_prefetch/forward.tsv` と違う、またはオラクル174行で落ちた
2. F1 の `new − old` の 95% 区間が 0 をまたがずに上（遅くなった）
3. どれかの本で `/proc/vmstat` の `thp_fault_fallback` の前後差が 0 でない

ほかに、落ちた本が無いことも見る。1・3 は `run_one.sh` が毎本その場で見る。

## 予測（門番を回す前に書いた）

lever_scan_2 の値は `reuse − base`（6本ずつ）。`base` は #22 ＋ 計装で、この門番の `old`（#23）とは174段ループの先読みと
計装（段ごとの minor fault など）のぶん違う。全探索のコードは計装を除けば同じ。

| | 予測（`new − old`） | 根拠 |
|---|---|---|
| **F1** | 下がる。区間が 0 をまたがない。大きさは lever_scan_2 の −3.66 と同じ桁 | lever_scan_2 の F1 −3.66（−4.33 … −2.98） |
| F1 の内訳 | カーネル時間とユーザー時間の両方から下がる | lever_scan_2 はカーネル −1.92、ユーザー −1.74。ページを用意する OS の仕事と、0 で埋める仕事・写す仕事の両方が減る |
| minor fault の合計 | 約 139 万回減る | lever_scan_2 の合計は −1,387,313（6,414,026 → 5,026,713）。段ごとでは F1 −1,048,467、F6 −283,957、F5 −59,979 |
| F6 | 下がる（弱い予測） | lever_scan_2 は −0.59（うちカーネル −0.46）。F6 のコードは変えていない。新しいページの側の変化と読めるが、機序は分けていない |
| F5 | 下がる（弱い予測） | lever_scan_2 は −0.11。F5 のコードも変えていない（機序は同上） |
| F2 | 動いても 0.02 秒未満 | `extend` → `frombytes` の差。lever_scan_2 は +0.00（+0.00 … +0.01） |
| 後退解析の段（P0〜`R_uk`） | 誤差内 | コードも入力の並びも同じで、`.so` もバイト同一。lever_scan_2 の `reuse` は後退解析の対照が1つも動かなかった |
| 全探索のピーク RSS（`hwm_F6`） | +0.04 GiB 前後 | lever_scan_2 は 7.251 → 7.288 GiB |
| **全体のピーク RSS** | **+0.1 GiB 前後** | 受け皿（3 × 500万 × 8 バイト ＝ 120 MB）は全探索が終わっても手放さないので、ピークの P2 にも乗る。lever_scan_2 は +102,436 kB |
| `dat/` | 12本とも #23 本走とバイト一致 | 並びを変えない |
| 完走タイム | 幅を出さない（参考の見込みは −4 秒前後） | lever_scan_2 の `reuse` は完走 −4.48 |

lever_scan_2 の数字は多重比較未補正なので、上に偏っている可能性がある。下回っても外れとしない。

## 集計

```bash
python3 experiments/gate_24_reuse_buffers/stop_rule.py   # 止める条件
python3 experiments/gate_24_reuse_buffers/f1_split.py    # F1 の内訳と、予測に登録した量
python3 experiments/gate_stats.py gate_24_reuse_buffers forward
python3 experiments/gate_stats.py gate_24_reuse_buffers spans
```

## ファイル

| | |
|---|---|
| [`build_arm.sh`](build_arm.sh) | 腕のソースを組んでビルドし、`.so` の sha256 の先頭を出す |
| [`run_one.sh`](run_one.sh) | 走る前にノード0の空きを確かめ、完走を1本測って検査し、生ログを `logs/` に写す |
| [`run_all.sh`](run_all.sh) | 12本を上の順で回す。進行は `logs/console.log`（回す前の負荷は load average と CPU 使用率の合計だけ） |
| [`free_snapshot.sh`](free_snapshot.sh) | 起動する前やキャッシュを落とす前後の空きメモリを `logs/free_<名前>.txt` に残す |
| [`stop_rule.py`](stop_rule.py) / [`f1_split.py`](f1_split.py) | 止める条件 / 判定の量の内訳 |
| [`lib.sh`](lib.sh) | 周波数の標本・vmstat・md5 一覧・空きブロックの読み（`gate_23_loop_prefetch` の写し） |
