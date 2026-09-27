# 門番 #23: 174段ループの2段の先読み（記録試行ではない）

`impl/23_loop_prefetch` は、174段ループ（`retreatStep()`）のループ頭に2段の先読みを入れた。
32 個先の q で `pred_off[q]` を、16 個先の q で `pred[pred_off[q]]` を取り寄せる。
コードは [`lever_scan_2`](../lever_scan_2/)（記録ではない）の [`pf2.patch`](../lever_scan_2/patches/pf2.patch) のまま。
距離は #20 の `predScatter` と同じで、調整していない。

lever_scan_2 は6腕を `base`（#22 ＋ 計装）に対して引いていて、多重比較は未補正。選んだ腕の効果は上に偏っている
可能性がある。この門番で、記録にする版そのものを1対1で測り直す。

## 腕と配置

| 腕 | 中身 |
|---|---|
| `old` | `impl/22_in_memory` |
| `new` | `impl/23_loop_prefetch`（C の `retreatStep()` だけが違う。`.py` / `.h` / `Makefile` はバイト同一） |

単位は完走（空の `dat/` から `python3 ./animal_shogi.py` を1本）。#22 から後退解析はファイルを読まない。
`old new new old` を3ブロック、計12本（各腕6本）。どの本も `numactl --cpunodebind=0 --membind=0` で
ノード0に固定する（[`run_all.sh`](run_all.sh)）。

**各本の前に、ノード0の 2 MiB 以上の空きブロック（`/proc/buddyinfo` の order 9 以上）が 16 GiB 以上あるかを見る**
（[`run_one.sh`](run_one.sh)。記録は `logs/<ラベル>_hugefree.txt`）。足りなければその本を走らせずに止め、
キャッシュを落として（root。`drop_caches` と `compact_memory`）門番を最初から回し直す。
走り始めてから巨大ページが付かなかった本は、止める条件3で扱う。

## 判定に使う量

**`loop174`**（`retreat_summary.tsv` の生値）と、そのユーザー時間・カーネル時間の内訳
（境界 `R_dtm` → `R_loop` の差。[`loop_split.py`](loop_split.py)）。比較は `old` 対 `new` の1本だけ。
段ごとの全表は `gate_stats.py`（`forward` / `spans`）。完走の壁時計も出すが、判定には使わない。

## 止める条件（[`stop_rule.py`](stop_rule.py)）

どれかに掛かったら、本走の前に止めて報告する。

1. どれかの本の `dat/` が #22 本走とバイト一致しない（md5 一覧の sha256 を
   `results/22_in_memory/bytecompare.txt` の値と照合）。またはオラクル174行で落ちた
2. `loop174` の `new − old` の 95% 区間が 0 をまたがずに上（遅くなった）
3. どれかの本で `/proc/vmstat` の `thp_fault_fallback` の前後差が 0 でない

ほかに、件数の列（`n_in`・`n_win`・`n_lose`・`n_uk`・`n_new_post`）が `results/22_in_memory/forward.tsv` と
一致すること、落ちた本が無いことも見る。1・3・件数の列は `run_one.sh` が毎本その場で見る。

## 予測（門番を回す前に書いた）

| | 予測（`new − old`） | 根拠 |
|---|---|---|
| **`loop174`** | 下がる。区間が 0 をまたがない。大きさは lever_scan_2 の −10.44 と同じ桁 | lever_scan_2 の `pf2`（`base` は #22 ＋ 計装、6本ずつ） |
| `loop174` の内訳 | ほぼ全部ユーザー時間から。カーネル時間は区間が 0 をまたぐ | lever_scan_2 でユーザー −10.45、カーネル +0.01 |
| P2 | ±1 秒程度動くかもしれない。**動いてもレバーの効果に数えない** | `retreatStep` が伸びて、後ろにある P2 の `buildSuccRange` の番地がずれる。lever_scan_2 の `pf2` では −0.14（区間が 0 をまたぐ）で、番地は 208 バイトずれていた |
| それ以外の段（F0〜F6、P0、P1、P4） | 誤差内 | コードも入力の並びも同じ |
| minor fault ／ ピーク RSS | 変わらない | 確保量も触るページも変えない |
| `dat/` | 12本とも #22 本走とバイト一致 | 並びを変えない |
| 完走タイム | 幅を出さない（参考の見込みは −9〜−11 秒。lever_scan_2 の `pf2` は −11.12） | |

lever_scan_2 の数字は多重比較未補正なので、上に偏っている可能性がある。下回っても外れとしない。

## 集計

```bash
python3 experiments/gate_23_loop_prefetch/stop_rule.py   # 止める条件
python3 experiments/gate_23_loop_prefetch/loop_split.py  # loop174 の内訳と、予測に登録した量
python3 experiments/gate_stats.py gate_23_loop_prefetch forward
python3 experiments/gate_stats.py gate_23_loop_prefetch spans
```

## ファイル

| | |
|---|---|
| [`build_arm.sh`](build_arm.sh) | 腕のソースを組んでビルドする |
| [`run_one.sh`](run_one.sh) | 走る前にノード0の空きを確かめ、完走を1本測って検査し、生ログを `logs/` に写す |
| [`run_all.sh`](run_all.sh) | 12本を上の順で回す。進行は `logs/console.log`（回す前の負荷は load average と CPU 使用率の合計だけ） |
| [`stop_rule.py`](stop_rule.py) / [`loop_split.py`](loop_split.py) | 止める条件 / 判定の量の内訳 |
| [`lib.sh`](lib.sh) | 周波数の標本・vmstat・md5 一覧・空きブロックの読み（`gate_22_in_memory` の写し ＋ `hugefree_gib`） |
