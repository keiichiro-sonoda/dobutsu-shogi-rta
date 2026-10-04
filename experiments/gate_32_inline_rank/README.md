# 門番 #32: `rankOf()` を必ずインライン展開させる（記録試行ではない）

`impl/32_inline_rank` は、`impl/30_rank_seen` の `rankOf()`（`static inline`）に **`__attribute__((always_inline))` を付けただけ**の版。
#31 は欠番。#30 では `gcc -O2` が大きさの見積もりで展開せず、`nextBoardSeenNormal()` から後続ごとに `call` していた（門番 #30 の `calls.py`）。
ランクの計算の中身は変えていない。`.h` / `.py` / `Makefile` は #30 とバイト同一（`Makefile` のフラグで全体の展開の基準は変えない）。

門番 #31（欠番）では、索引のランク化で P2 が +1.48 秒になり、後続ごとの `rankOf()` の `call` が足されたぶんと読めた。そこで先にこの変更を
記録にし、その上で索引のランク化を新しい番号で測り直す。この版の時点で `rankOf()` を熱い経路で呼ぶのは全探索の `nextBoardSeenNormal()` だけなので、
**効くのは F1**。

## 何が変わるか（回す前に数えた）

2腕を門番と同じ手順（その実装の `Makefile`）でビルドして数えた（[`calls.py`](calls.py) / [`insns.py`](insns.py) / [`symbols.py`](symbols.py)。
回したあとで、門番の本が作った `.so` で数え直して `logs/` に残す）。

| | #30（`old`） | #32（`new`） |
|---|---|---|
| `rankOf` への `call` | 3（`nextBoardSeenNormal`・`seenInsert`・`seenContains`） | **0**（`rankOf` の本体も `.so` から消える） |
| `nextBoardSeenNormal` の命令 | 90 | **237**（+147） |
| `rankFindKoma`・`rankSqueeze`・`rankHalf` | `rankOf` の中に展開済み（`call` 無し） | 同じ |

関数の番地は大きく動く。`rankOf` の本体（140 命令）が消え、展開した先が大きくなるので、`showBoard`〜`nextBoardIndexNormal` は **−560 バイト**
（いちばん熱い `nextBoardInvNormal` も含む）、`nextBoardSeenNormal` は +1,056、`expandRound`・`retreatStep`・`buildSuccRange` など後ろの関数は
**+1,632 バイト**ずれる。64 バイトの線の中の位置も多くが変わる。#26〜#30 では番地が動いてもほかの段は動かなかったが、動いたら本走の前に調べる。

門番 #31 のパッチ（[`../gate_31_rank_index/patches/rank_index.patch`](../gate_31_rank_index/patches/rank_index.patch)）は、この版の上に
fuzz なしで当たり（`patch --dry-run`）、当てたものも警告なくビルドでき、`rankOf` への `call` は無かった（当て直しは次の記録で行う）。

## 腕と配置

| 腕 | 中身 |
|---|---|
| `old` | `impl/30_rank_seen` |
| `new` | `impl/32_inline_rank` |

差分の範囲（`.c` は `rankOf()` の定義の行に属性を付けたことと直前のコメントだけ）と、`rankOf` への `call` が無いこと、打ち切って回した成果物の
#30 とのバイト一致は `tests/test_impl_32_inline_rank.py` が固定している。[`build_arm.sh`](build_arm.sh) はその実装の `Makefile` でビルドし、
毎本 `.so` の sha256 の先頭を進行ログに出す（回す前にビルドして読んだ値は `old` が `1948f6c159f2`（#30 本走と同じ）、`new` が `0ff76aa55cec`）。
2腕とも `-march=native` でビルドするので、何に解決されたかを [`march.sh`](march.sh) で `logs/march.txt` に残す。

単位は完走（空の `dat/` から `python3 ./animal_shogi.py` を1本）。`old new new old` を3ブロック、計12本（各腕6本）。
どの本も `numactl --cpunodebind=0 --membind=0` でノード0に固定する（[`run_all.sh`](run_all.sh)）。
各本の前に、ノード0の 2 MiB 以上の空きブロックが 16 GiB 以上あるかを見る（[`run_one.sh`](run_one.sh)）。足りなければ自分で回避せず、
止めて人にキャッシュを落としてもらう。起動する前やキャッシュを落とす前後の値は [`free_snapshot.sh`](free_snapshot.sh) で `logs/` に残す。

## 判定に使う量

**主な判定の量は F1 のユーザー時間**（`forward_summary.tsv` の `utime_F1`。[`f1p2_split.py`](f1p2_split.py)）。計算の手間を減らす変更なので
ユーザー時間で見る。主な量は1つなので補正は要らない。

**同点の扱い**: 主な量の区間の上端が 0 以上なら（下がったと言えない）同点か遅くなったとみなす。**欠番にする前に止まって本人に報告する。**
次の記録（索引のランク化の測り直し）の土台にするかどうかを、時間とは別に決める余地があるため。

## 止める条件（[`stop_rule.py`](stop_rule.py)）

どれかに掛かったら、本走の前に止めて報告する。

1. どれかの本の `dat/` が #30 本走とバイト一致しない（md5 一覧の sha256 を `results/30_rank_seen/bytecompare.txt` の値と照合）、
   件数の列（`n_in`・`n_win`・`n_lose`・`n_uk`・`n_new_post`）が `results/30_rank_seen/forward.tsv` と違う、またはオラクル174行で落ちた
2. F1 のユーザー時間の `new − old` の 95% 区間の上端が 0 以上（同点か遅くなった。欠番にする前に報告する）
3. 動かないはずの段（F0・F2・F5・F6・P0・P1・P2・P4・`R_dtm`・`loop174`）のどれかが、区間が 0 をまたがず、かつ差の大きさが **0.2 秒以上**
   （向きは問わない）。`rankOf()` を熱い経路で呼ばない段なので、動いたら本走の前に原因を調べる（関数の番地の移動など。確保は変えていないので
   mmap のしきい値の副作用は出ないはずだが、出たら [`diag_mmap.sh`](diag_mmap.sh) で確かめる）。段の数だけ比べるので多重比較は未補正
4. どれかの本で `thp_fault_fallback` の前後差が 0 でない、または巨大ページが表と配列の全部に付かない（両腕とも #30 と同じ確保:
   発見済み表 104,448・索引 8,388,608・後退解析の配列 4,972,544 kB 以上）

ほかに、落ちた本が無いことも見る。1・4 は `run_one.sh` が毎本その場で見る。

## 予測（門番を回す前に書いた）

| | 予測（`new − old`） | 根拠 |
|---|---|---|
| **F1 のユーザー時間** | 下がる。区間が 0 をまたがない。**−1〜−4 秒**（中心 −2 秒前後） | F1 で `rankOf()` を呼ぶのは後続の数（938,671,869 回）。#27 で `normalBoard()` の `call` を消したときの得は1回約 2 ns だったので、`call` のぶんだけなら約 −2 秒。展開で、表の番地の読み込みなどを後続のループの外へ出せれば、もう少し大きくなる |
| F1 のカーネル時間・minor fault | 変わらない | 確保もページも変えない |
| F0・F2・F5・F6・後退解析の全段 | 動かない（止める条件3に掛からない） | 後退解析は #30 ではランクを使っていない。関数の番地は動くが、#26〜#30 では番地の移動でほかの段は動かなかった |
| 全体のピーク RSS | 変わらない | |
| 巨大ページ | 12本とも表と配列の全部に付く | 確保は #30 と同じ |
| `dat/` | 12本とも #30 本走とバイト一致 | ランクの値は変わらない |
| 完走タイム | 幅を出さない（参考の見込みは −1〜−4 秒） | |

## 集計

```bash
python3 experiments/gate_32_inline_rank/stop_rule.py    # 止める条件
python3 experiments/gate_32_inline_rank/f1p2_split.py   # 判定の量と、予測に登録した量
python3 experiments/gate_stats.py gate_32_inline_rank forward
python3 experiments/gate_stats.py gate_32_inline_rank spans
O=runs/exp_g32_r1a_old/animal_shogi.so N=runs/exp_g32_r1b_new/animal_shogi.so
python3 experiments/gate_32_inline_rank/calls.py "$O" "$N"
python3 experiments/gate_32_inline_rank/insns.py "$O" "$N"
python3 experiments/gate_32_inline_rank/symbols.py "$O" "$N"
```

## ファイル

| | |
|---|---|
| [`build_arm.sh`](build_arm.sh) | 腕のソースを写し、その実装の `Makefile` でビルドし、`.so` の sha256 の先頭を出す |
| [`march.sh`](march.sh) | `-march=native` が何に解決されるか |
| [`run_one.sh`](run_one.sh) | 走る前にノード0の空きを確かめ、完走を1本測って検査し、生ログを `logs/` に写す |
| [`run_all.sh`](run_all.sh) | `march.sh` を残してから12本を上の順で回す。進行は `logs/console.log`（回す前の負荷は load average と CPU 使用率の合計だけ） |
| [`free_snapshot.sh`](free_snapshot.sh) | 起動する前やキャッシュを落とす前後の空きメモリを `logs/free_<名前>.txt` に残す |
| [`stop_rule.py`](stop_rule.py) / [`f1p2_split.py`](f1p2_split.py) | 止める条件 / 判定の量と内訳 |
| [`diag_mmap.sh`](diag_mmap.sh) | 止める条件3に掛かったときの調べ（mmap のしきい値を固定して1本回す。判定には使わない） |
| [`insns.py`](insns.py) / [`calls.py`](calls.py) / [`symbols.py`](symbols.py) | 2腕の `.so` の命令 / `call` の行き先 / 関数の番地のずれ |
| [`lib.sh`](lib.sh) | 周波数の標本・vmstat・md5 一覧・空きブロックの読み（`gate_30_rank_seen` の写し） |
