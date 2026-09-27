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

## 結果（回したあとで書いた）

**止める条件には掛からなかった**（[`logs/stop_rule.txt`](logs/stop_rule.txt)）。12本とも

- オラクル174行 PASS、`dat/` は #22 本走とバイト一致（[`logs/bytecompare.tsv`](logs/bytecompare.tsv)）
- 件数の列は #22 の `forward.tsv` と全74ラウンド一致
- `thp_fault_fallback` の前後差は 0（`thp_fault_alloc` は全本 +8,188、`compact_stall` は全本 0）

### 走る前の空きメモリ

起動する前に同じ読み方（[`lib.sh`](lib.sh) の `hugefree_gib`）で手で確かめると、ノード0の 2 MiB 以上の空きブロックは
12.80 GiB でしきい値に届かなかった（ページキャッシュが約 5.6 GB 溜まっていた）。root でキャッシュを落として
（`sync`、`drop_caches` に 3、`compact_memory` に 1）、22.79 GiB に戻ったのを確かめてから起動した。
**落とす前の 12.80 と、落とした直後の 22.79 は、どちらも記録が残っていない**（手で読んだだけで、`logs/` にも `runs/` にも無い）。
`logs/` に残っているのは落としたあとの値だけで、`logs/console.log` の冒頭（起動した時点のノード0の `buddyinfo`）と、
12本の走る前の値（`logs/<ラベル>_hugefree.txt`）。後者は 22.90 → 21.51 GiB で、少しずつ減ったがどれも 16 GiB を超えていた。

### 判定の量: `loop174` は −10.24 秒（区間 −10.49 … −9.99）

[`loop_split.py`](loop_split.py) の出力（[`logs/loop_split.txt`](logs/loop_split.txt)）。比較は `old` 対 `new` の1本だけなので補正は要らない。

| 量 | `old` 平均（sd） | `new` 平均（sd） | `new` − `old`（95% 区間） | p |
|---|---|---|---|---|
| loop174 | 26.56（0.22） | 16.31（0.14） | -10.24（-10.49 … -9.99） | < 0.0001 |
| loop174 のユーザー時間 | 25.08（0.22） | 14.87（0.12） | -10.21（-10.45 … -9.97） | < 0.0001 |
| loop174 のカーネル時間 | 1.47（0.02） | 1.45（0.04） | -0.03（-0.07 … +0.01） | 0.1783 |
| P2 | 46.31（0.21） | 46.49（0.25） | +0.18（-0.12 … +0.48） | 0.2152 |
| retreat_total | 101.74（0.59） | 91.83（0.47） | -9.91（-10.60 … -9.22） | < 0.0001 |
| minor fault (万) | 641.39（0.00） | 641.39（0.00） | -0.00（-0.00 … +0.00） | 0.2860 |
| ピーク RSS (GiB) | 13.86（0.00） | 13.86（0.00） | +0.00（-0.00 … +0.00） | 0.6291 |
| 完走 (秒、参考) | 184.00（0.83） | 174.34（1.23） | -9.66（-11.03 … -8.29） | < 0.0001 |

**174段ループは 26.56 → 16.31 秒（−38.6%）で、下がったぶんはほぼ全部ユーザー時間。**
ほかの段は全探索の5段、P0、P1、P2 とその内訳、P4 とその内訳、`R_dtm`・`R_draw`・`R_uk` のどれも区間が 0 をまたいだ
（[`logs/stats_forward.txt`](logs/stats_forward.txt) と [`logs/stats_spans.txt`](logs/stats_spans.txt)。
0 にいちばん近づいたのは `P4_count` の +0.05（−0.00 … +0.11、p 0.0606））。

### 予測と実測

| | 予測（`new − old`） | 実測 | |
|---|---|---|---|
| **`loop174`** | 下がる。区間が 0 をまたがない。−10.44 と同じ桁 | −10.24（−10.49 … −9.99） | ✅ |
| `loop174` の内訳 | ほぼ全部ユーザー時間。カーネル時間は区間が 0 をまたぐ | ユーザー −10.21、カーネル −0.03（−0.07 … +0.01） | ✅ |
| P2 | ±1 秒程度。動いてもレバーの効果に数えない | +0.18（−0.12 … +0.48） | ✅ 区間が 0 をまたいだ |
| それ以外の段 | 誤差内 | どれも区間が 0 をまたいだ | ✅ |
| minor fault ／ ピーク RSS | 変わらない | minor fault は `old` 6,413,905〜6,413,912、`new` 6,413,901〜6,413,914。ピーク RSS は両腕とも 14,529,680〜14,530,400 kB | ✅ |
| `dat/` | 12本とも #22 本走とバイト一致 | 一致 | ✅ |
| 完走タイム | 幅を出さない（参考の見込みは −9〜−11 秒） | −9.66（−11.03 … −8.29） | — |

lever_scan_2 の `pf2`（`loop174` −10.44、P2 −0.14、完走 −11.12）とは、どれも同じ桁に収まった。
腕の数・本数・並べ方が違うので、差どうしを引き算して偏りを出すことはしない。

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
