# 門番 #31: 後退解析の索引を「ランク → 連番」の対応表にする（記録試行ではない）

`impl/31_rank_index` は、`impl/30_rank_seen` の後退解析の索引（パック値 → 連番のオープンアドレス法のハッシュ表。16 B のエントリ、
本番 2^29 スロット = 8 GiB）を、#30 のランク（正規化した盤面どうしで単射、値域 855,232,344）を添字にした `uint32_t` の表
（**3.42 GB**、索引にない位置は番兵）に替えた版。連番は今までと同じ（`packed` の並びの添字）なので、採番順も `dat/` も #30 と
変わらないはず。全探索・ランク関数・`.py`・`Makefile` は #30 のまま。`rankOf()` のインライン展開はしていない。

| | #30（`old`） | #31（`new`） |
|---|---|---|
| 索引 | ハッシュ表 2^29 スロット × 16 B = 8 GiB（4,096 枚の 2 MiB ページ） | 対応表 855,232,344 × 4 B = 3.42 GB（1,632 枚） |
| 構築（P1） | 8 GiB を 0xff で埋め、246,803,167 件を乗算ハッシュ＋線形探査で挿入（16 個先を先読み） | 3.42 GB を 0xff で埋め、64 件ずつランクを出して取り寄せてから書く |
| 引き（P2） | 後続ごとに乗算ハッシュ＋線形探査（16 B を1回、たまに2回以上） | 後続ごとにランク（`rankOf()` の `call`）＋ 4 B を1回 |

回す前にビルドして `objdump` で見ると、`indexBuild` と `nextBoardIndexNormal` から `rankOf` への直接の `call` が1つずつ増え、
`nextBoardIndexNormal` の命令は 99 → 76（[`calls.py`](calls.py) / [`insns.py`](insns.py)。回したあとで `logs/` に残す）。

⚠️ 実装の途中で、`indexBuild` に盤面としての検査（`rankValid`）を全件に通す形にしていた。#30 本走の全局面で測ると 1件約 23 ns
（`rankOf` は約 15 ns）で、P1 に 5 秒以上足されるので、#30 までと同じく番兵だけを弾く形に戻してから門番の準備をした
（`packed` は全探索の成果物で、正規化した正しい盤面だけが来る）。

## 腕と配置

| 腕 | 中身 |
|---|---|
| `old` | `impl/30_rank_seen` |
| `new` | `impl/31_rank_index` |

差分の範囲（`.c` は索引の宣言と3つの関数だけ、`.h` は索引の宣言の節だけ、`.py` と `Makefile` はバイト同一）は
`tests/test_impl_31_rank_index.py` が固定している（ほかに、到達局面の標本で素朴な対応（`dict`）と同じ連番を返すこと、重複で -5・番兵で -4・
索引にない後続で -2、打ち切って回した成果物の #30 とのバイト一致）。[`build_arm.sh`](build_arm.sh) はその実装の `Makefile` でビルドし、
毎本 `.so` の sha256 の先頭を進行ログに出す（回す前にビルドして読んだ値は `old` が `1948f6c159f2`（#30 本走と同じ）、`new` が `14effc10ba75`）。
2腕とも `-march=native` でビルドするので、何に解決されたかを [`march.sh`](march.sh) で `logs/march.txt` に残す。

単位は完走（空の `dat/` から `python3 ./animal_shogi.py` を1本）。`old new new old` を3ブロック、計12本（各腕6本）。
どの本も `numactl --cpunodebind=0 --membind=0` でノード0に固定する（[`run_all.sh`](run_all.sh)）。
各本の前に、ノード0の 2 MiB 以上の空きブロックが 16 GiB 以上あるかを見る（[`run_one.sh`](run_one.sh)）。足りなければ自分で回避せず、
止めて人にキャッシュを落としてもらう。起動する前やキャッシュを落とす前後の値は [`free_snapshot.sh`](free_snapshot.sh) で `logs/` に残す。

## 判定に使う量

**主な判定の量は P1 ＋ P2 のユーザー時間 ＋ カーネル時間**（`retreat_summary.tsv` の境界 P0 → P2 の `utime_` と `stime_` の差の和。
[`f1p2_split.py`](f1p2_split.py)）。索引は P1 で作って P2 で引くので、2段を1つにまとめる。主な量は1つなので補正は要らない。
内訳として P1・P2 それぞれのユーザー時間とカーネル時間、`P2_free`（索引を捨てる区間）、全体のピーク RSS も並べる。

**同点の扱い**: 主な量の区間の上端が 0 以上なら（下がったと言えない）同点か遅くなったとみなす。**欠番にする前に止まって本人に報告する。**
ピーク RSS は下がるはずなので、`rankOf()` のインライン展開を先に記録にしてからこの版を測り直す、という選択肢があるため。

## 止める条件（[`stop_rule.py`](stop_rule.py)）

どれかに掛かったら、本走の前に止めて報告する。

1. どれかの本の `dat/` が #30 本走とバイト一致しない（md5 一覧の sha256 を `results/30_rank_seen/bytecompare.txt` の値と照合）、
   件数の列（`n_in`・`n_win`・`n_lose`・`n_uk`・`n_new_post`）が `results/30_rank_seen/forward.tsv` と違う、またはオラクル174行で落ちた
2. P1 ＋ P2 のユーザー時間 ＋ カーネル時間の `new − old` の 95% 区間の上端が 0 以上（同点か遅くなった。欠番にする前に報告する）
3. 動かないはずの段（F0・F1・F2・F5・F6・P0・P4・`R_dtm`・`loop174`）のどれかが、区間が 0 をまたがず、かつ差の大きさが **0.2 秒以上**
   （向きは問わない）。索引を触らない段なので、動いたら本走の前に原因を調べる。まず malloc の mmap のしきい値の副作用を疑う
   （[`diag_mmap.sh`](diag_mmap.sh)。門番 #30 と同じ方法）。`P2_free` は捨てる量が変わるので入れない。段の数だけ比べるので多重比較は未補正
4. どれかの本で `thp_fault_fallback` の前後差が 0 でない、または巨大ページが表と配列の全部に付かない。索引は腕ごとに大きさが違うので、
   `anonhuge_index_kB` のしきい値は `old` 8,388,608・`new` 3,342,336 kB（対応表 1,632 枚）。発見済み表 104,448・後退解析の配列 4,972,544 kB は両腕同じ

ほかに、落ちた本が無いことも見る。1・4 は `run_one.sh` が毎本その場で見る。

## 予測（門番を回す前に書いた）

#30 本走の P1 は 7.13 秒（ユーザー 4.88、カーネル 2.25）、P2 は 39.44 秒（ユーザー 37.50、カーネル 1.93）。
回す前に #30 本走の全局面で測ると、`rankOf` だけで 1件約 15 ns（全件で 3.75 秒）かかる。

| | 予測（`new − old`） | 根拠 |
|---|---|---|
| **P1 ＋ P2 のユーザー＋カーネル時間** | **向きを決め打ちしない。−3〜+3 秒**。同点もありうる | 下の P1・P2 の和 |
| P1 | 下がる。**−0.5〜−2 秒**（中心 −1 秒前後） | カーネル時間は、ページを用意して 0 で埋める量が 8 GiB → 3.42 GB になるぶん −1〜−1.5 秒。ユーザー時間は、埋める量が減るぶんと、挿入の1件がハッシュ＋探査からランク（約 15 ns）＋書き込みに替わるぶんで、ほぼ相殺（−0.5〜+1 秒） |
| P1 のカーネル時間 | 下がる。−1〜−1.5 秒 | 上のとおり |
| P2 | **向きを決め打ちしない。−2〜+4 秒** | 後続 938,671,869 個のそれぞれで、乗算ハッシュ（1 ns 程度）がランク（約 15 ns、`call`）に替わり、DRAM から取り寄せるのは 16 B → 4 B になる。#30 の設計の試作では、もう入っている局面の判定はハッシュ表 19.4 ns・ランク＋ビット表 19.8 ns でほぼ同じだった。ランクの計算が DRAM の待ちに隠れきらなければ遅くなる |
| P2 のカーネル時間 | 変わらない | 引くだけで確保は変わらない |
| `P2_free`（#30 で 0.05 秒） | 小さくなる | 捨てる量が 8 GiB → 3.42 GB |
| **全体のピーク RSS**（#30 本走で 13.86 GiB、P2 の時点） | **約 4.8 GiB 下がる**（約 9.0 GiB） | 索引 8 GiB が対応表 3.19 GiB（1,632 枚 × 2 MiB）に替わる |
| `anonhuge_index_kB` | `old` 8,486,912、`new` 3,440,640 kB | 索引に `cnt`（98,304 kB）が足される（P2 の終わりにプロセス全体を読むため） |
| F0〜F6・P0・P4・`R_dtm`・174段ループ | 動かない（止める条件3に掛からない） | 索引を触らない。`P2_free` で捨てる塊は両腕とも 32 MiB より大きいので、mmap のしきい値は両腕とも上限（32 MiB）まで上がり、P4 以降の確保は同じ扱いになるはず |
| `dat/` | 12本とも #30 本走とバイト一致 | 連番と採番順が同じ |
| 完走タイム | 幅を出さない（参考の見込みは −3〜+3 秒） | |

**いちばん不確かなのは P2。** ランクの計算（`call` のまま）が、後続ごとの DRAM の待ちにどれだけ隠れるかで向きが決まる。
時間が同点か遅くなっても、全体のピーク RSS は約 4.8 GiB 下がるはず。

## 集計

```bash
python3 experiments/gate_31_rank_index/stop_rule.py    # 止める条件
python3 experiments/gate_31_rank_index/f1p2_split.py   # 判定の量と、予測に登録した量
python3 experiments/gate_stats.py gate_31_rank_index forward
python3 experiments/gate_stats.py gate_31_rank_index spans
O=runs/exp_g31_r1a_old/animal_shogi.so N=runs/exp_g31_r1b_new/animal_shogi.so
python3 experiments/gate_31_rank_index/calls.py "$O" "$N"
python3 experiments/gate_31_rank_index/insns.py "$O" "$N"
python3 experiments/gate_31_rank_index/symbols.py "$O" "$N"
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
