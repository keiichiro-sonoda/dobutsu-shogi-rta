# 門番 #27: `-fno-semantic-interposition` を足す（記録試行ではない）

`impl/27_no_interposition` は、`impl/26_inv_bits` の `Makefile` の `gcc` 行に **`-fno-semantic-interposition` を1つ足しただけ**。
`animal_shogi.c`・`.h`・`.py` は #26 とバイト同一。

`-fPIC -shared` の既定では、同じ `.so` の中の関数どうしの呼び出しも「実行時に別の定義へ差し替えられうる」ものとして扱われ、
PLT を経由し、インライン展開もされない。このフラグは差し替えないと約束して、それをやめさせる。このリポジトリは `.so` を
ctypes から呼ぶだけで、関数を差し替える仕組みは使っていない。

このレバーは #18 の門番で見えていた（[`gate_18_opt`](../gate_18_opt/) で F1 −3.75 s（区間 −4.91〜−2.58）、
[`lever_scan`](../lever_scan/) で F1 −3.92 s（区間 −5.24〜−2.59）。どちらも #18 のコードで、F1 は約 98 秒）。
lever_scan の P2 は +0.93 s（区間 −10.00〜+11.85）で、`fnsi` 腕の外れ値1本のせいで確定できなかった。多重比較も未補正。
この門番で、#26 の上に足した版そのものを1対1で測り直す。

## 呼び出しがどう変わるか（回す前に数えた）

2腕を門番と同じ手順（その実装の `Makefile`）でビルドし、`objdump -d` の `call` を呼び出し元ごとに数えた（[`calls.py`](calls.py)）。
回したあとで、門番の本が作った `.so` で数え直して `logs/calls.txt` に残す。

| 呼び出し元 | #26（`old`） | #27（`new`） |
|---|---|---|
| `nextBoardInvNormal`（生成器） | `normalBoard@plt` 3、`invBoard@plt` 1 | `normalBoard` は **0（インライン展開）**、`invBoard` 1（直接） |
| `nextBoardSeenNormal`（F1） | `nextBoardInvNormal@plt`・`seenInsert@plt`・`seenInit@plt` | どれも直接 |
| `expandRound`（F1） | `nextBoardSeenNormal@plt` | 直接 |
| `nextBoardIndexNormal`（P2） | `nextBoardInvNormal@plt` | 直接 |
| `buildSuccRange`（P2） | `nextBoardIndexNormal@plt` | 直接 |
| `indexBuild`（P1）・`seenInit` | `indexFree@plt` 3・`seenFree@plt` 1 | インライン展開（`free@plt` になる。失敗時と解放の経路） |
| 合計 | PLT 経由 60 / 直接 0 | PLT 経由 43 / 直接 13 |

`nextBoardInvNormal()` の中の `invBoard()` は、フラグを付けてもインライン展開されずに直接の `call` として残る
（gcc の判断。フラグが約束するのは差し替えないことだけ）。`normalBoard()` は生成した後続ごとに呼ばれるので、
呼ばれる回数は F1 で約12〜13億回（#18 のノートの見積り）、P2 でも辺の本数（938,671,869）以上ある。

### ⚠️ 関数の置き場所も動く

PLT が小さくなる（`.plt` 0x160 → 0xc0 バイトなど）ので `.text` の先頭が 320 バイト前へ動き、インライン展開した関数は大きくなる
（`nextBoardInvNormal` 1150 → 1200、`indexBuild` 530 → 640、`seenInit` 128 → 200 バイト）。そのため全部の関数の番地が
−112〜−336 バイト動き、64 バイトの線の中の位置も多くが変わる（[`symbols.py`](symbols.py)。回したあとで `logs/symbols.txt` に残す）。
**F1・P2 の差にはこの置き場所の効果も混ざりうる（分けられない）。** 動かないはずの段が動いたときは、下の止める条件4で止めて調べる。

## 腕と配置

| 腕 | 中身 |
|---|---|
| `old` | `impl/26_inv_bits` |
| `new` | `impl/27_no_interposition`（`old` の `gcc` 行に `-fno-semantic-interposition` を足したもの） |

2腕の差が `Makefile` のこのフラグ1つだけであることは `tests/test_impl_27_no_interposition.py` が固定している（そのテストは
2腕をそれぞれの `Makefile` でビルドし、上の呼び出しの変化と、打ち切って回した成果物のバイト一致も見る）。
[`build_arm.sh`](build_arm.sh) は、その実装の `Makefile` でビルドし、毎本 `.so` の sha256 の先頭を進行ログに出す
（回す前にビルドして読んだ値は `old` が `dd411cfbf38b`（#26 本走と同じ）、`new` が `77e88ec9d704`）。

単位は完走（空の `dat/` から `python3 ./animal_shogi.py` を1本）。`old new new old` を3ブロック、計12本（各腕6本）。
どの本も `numactl --cpunodebind=0 --membind=0` でノード0に固定する（[`run_all.sh`](run_all.sh)）。
各本の前に、ノード0の 2 MiB 以上の空きブロックが 16 GiB 以上あるかを見る（[`run_one.sh`](run_one.sh)。記録は
`logs/<ラベル>_hugefree.txt`）。起動する前やキャッシュを落とす前後の値は [`free_snapshot.sh`](free_snapshot.sh) で `logs/` に残す。

## 判定に使う量

**F1 のユーザー時間と P2 のユーザー時間**（F1 は `forward_summary.tsv` の `utime_F1`、P2 は `retreat_summary.tsv` の境界 P1 → P2 の差。
[`f1p2_split.py`](f1p2_split.py)）。呼び出しの手間を減らす変更なので、ユーザー時間で見る（壁時計の F1・P2 と、カーネル時間も並べる）。
比較は `old` 対 `new` の1本だけなので補正は要らない。段ごとの全表は `gate_stats.py`（`forward` / `spans`）。完走は参考。

**同点の扱い**: F1 のユーザー時間の区間が 0 をまたいだら同点とみなし、記録にしない（本走しない。門番の結果だけをコミットして報告する）。

## 止める条件（[`stop_rule.py`](stop_rule.py)）

どれかに掛かったら、本走の前に止めて報告する。

1. どれかの本の `dat/` が #26 本走とバイト一致しない（md5 一覧の sha256 を `results/26_inv_bits/bytecompare.txt` の値と照合）、
   件数の列が `results/26_inv_bits/forward.tsv` と違う、またはオラクル174行で落ちた
2. F1 のユーザー時間の `new − old` の 95% 区間が 0 をまたぐか上（同点か遅くなった）、
   または P2 のユーザー時間の区間が 0 をまたがずに上（遅くなった）
3. どれかの本で `thp_fault_fallback` の前後差が 0 でない、または巨大ページが表と配列の全部に付かない
   （両腕とも、`anonhuge_seen_kB` 4,194,304・`anonhuge_index_kB` 8,388,608・`anonhuge_loop_kB` 4,972,544 kB 以上）
4. 動かないはずの段（F2・F5・F6・P0・P1・P4・`loop174`）のどれかが、区間が 0 をまたがず、かつ差の大きさが **0.2 秒以上**。
   本走の前に原因を調べる（関数の配置が動いた影響など）。0.2 秒は P4・`loop174`（約 15 秒）の 1.3%、P1（7.3 秒）の 2.7% で、
   #25・#26 の門番でこれらの段の sd は 0.01〜0.14 秒だった

ほかに、落ちた本が無いことも見る。1・3 は `run_one.sh` が毎本その場で見る。

## 予測（門番を回す前に書いた）

| | 予測（`new − old`） | 根拠 |
|---|---|---|
| **F1 のユーザー時間** | 下がる。区間が 0 をまたがない。**−1.5〜−4 秒**（中心 −2.5 秒前後） | #18 のコードで −3.75 / −3.92 秒（壁時計）。`normalBoard()` の呼び出しの回数（約12〜13億回）は #26 でも変わらないので、1回 2〜3 ns の節約の絶対量はおおむね残る。ただし #26 で F1 の中身が軽くなったぶん、呼び出しの手間が表を引く待ちに隠れて目減りしうるので、下側を広く取る |
| **P2 のユーザー時間** | 下がる向き。大きさは判定にも当否にも使わない（参考の見込みは −1〜−3 秒） | P2 も生成器（`nextBoardInvNormal`）を通り、`normalBoard()` の呼び出しは辺の本数（約 9.4 億）以上で F1 の約 4 分の 3。lever_scan では外れ値1本のせいで確定できなかった |
| F1・P2 のカーネル時間 | 区間が 0 をまたぐ | 確保もページも変えない |
| F1・P2 の壁時計 | ユーザー時間とほぼ同じだけ下がる | |
| 動かないはずの段（F2・F5・F6・P0・P1・P4・`loop174`） | 止める条件4に掛からない | 生成器を通らない段。P1 の `indexBuild()` はコードが変わるが、変わるのは失敗時と解放の経路だけ |
| minor fault ／ 全体のピーク RSS | 変わらない | |
| 巨大ページ | 12本とも表と配列の全部に付く | 確保は #26 と同じ |
| `dat/` | 12本とも #26 本走とバイト一致 | 値を変えない変更（C は同じ） |
| 完走タイム | 幅を出さない（参考の見込みは −3〜−7 秒） | |

## 結果（回したあとで書いた）

**止める条件には掛からなかった**（[`logs/stop_rule.txt`](logs/stop_rule.txt)）。12本とも

- オラクル174行 PASS、`dat/` は #26 本走とバイト一致（[`logs/bytecompare.tsv`](logs/bytecompare.tsv)）、件数の列は全74ラウンド一致
- `thp_fault_fallback` の前後差は 0（`compact_stall` も全本 0）、巨大ページは両腕とも表と配列の全部に付いた
- `.so` の sha256 の先頭は `old` が `dd411cfbf38b`、`new` が `77e88ec9d704` で、回す前にビルドした値と同じ（`logs/console.log`）。
  `call` の数え直し（[`logs/calls.txt`](logs/calls.txt)）と番地の表（[`logs/symbols.txt`](logs/symbols.txt)）も、回す前に数えたものと同じ

起動する前のノード0は 2.85 GiB で 16 GiB に届かず（[`logs/free_before_launch.txt`](logs/free_before_launch.txt)）、
人が root でキャッシュを落として 20.32 GiB にしてから起動した（[`logs/free_after_drop.txt`](logs/free_after_drop.txt)）。
12本の走る前の値は 20.32〜21.16 GiB。

### 判定の量: F1 のユーザー時間 −2.53 秒、P2 のユーザー時間 −0.89 秒

[`f1p2_split.py`](f1p2_split.py) の出力（[`logs/f1p2_split.txt`](logs/f1p2_split.txt)）。比較は `old` 対 `new` の1本だけなので補正は要らない。

| 量 | `old` 平均（sd） | `new` 平均（sd） | `new` − `old`（95% 区間） | p |
|---|---|---|---|---|
| F1 | 66.54（0.22） | 64.00（0.39） | -2.54（-2.96 … -2.12） | < 0.0001 |
| F1 のユーザー時間 | 63.59（0.22） | 61.05（0.39） | -2.53（-2.95 … -2.11） | < 0.0001 |
| F1 のカーネル時間 | 2.95（0.01） | 2.94（0.03） | -0.00（-0.04 … +0.03） | 0.7418 |
| P2 | 42.24（0.21） | 41.41（0.18） | -0.83（-1.08 … -0.57） | < 0.0001 |
| P2 のユーザー時間 | 40.28（0.22） | 39.39（0.16） | -0.89（-1.14 … -0.63） | < 0.0001 |
| P2 のカーネル時間 | 1.96（0.04） | 2.02（0.05） | +0.06（-0.00 … +0.12） | 0.0501 |
| P2_alloc | 0.29（0.00） | 0.29（0.00） | +0.00（-0.00 … +0.01） | 0.1786 |
| P2_loop | 41.95（0.21） | 41.12（0.18） | -0.83（-1.09 … -0.58） | < 0.0001 |
| F1 と P2 の和 | 108.78（0.41） | 105.41（0.41） | -3.37（-3.89 … -2.85） | < 0.0001 |
| 全探索 合計 | 71.40（0.23） | 68.87（0.39） | -2.53（-2.96 … -2.11） | < 0.0001 |
| 後退解析 合計 | 82.24（0.33） | 81.38（0.29） | -0.86（-1.26 … -0.46） | 0.0007 |
| minor fault (万) | 371.84（0.00） | 371.84（0.00） | +0.00（-0.00 … +0.00） | 0.4513 |
| 全体のピーク RSS (GiB) | 13.84（0.00） | 13.84（0.00） | +0.00（-0.00 … +0.00） | 0.9095 |
| 完走 (秒、参考) | 153.83（0.55） | 150.42（0.48） | -3.40（-4.06 … -2.74） | < 0.0001 |

**F1 は 66.54 → 64.00 秒で、ほぼ全部ユーザー時間から下がった**（カーネル時間は区間が 0 をまたぐ）。
**P2 も 42.24 → 41.41 秒と下がり、区間は 0 をまたがなかった。** lever_scan で確定できなかった P2 の向きが、ここで確定した。
P2 のカーネル時間は +0.06（−0.00 … +0.12、p 0.0501）で、区間の下端がほぼ 0。
段ごとの全表は [`logs/stats_forward.txt`](logs/stats_forward.txt) と [`logs/stats_spans.txt`](logs/stats_spans.txt)。
**動かないはずの段はどれも区間が 0 をまたいだ**（差の大きさはどれも 0.02 秒以下）。全部の関数の番地が動いても、ほかの段は動かなかった。

minor fault は `old` 3,718,426〜3,718,433、`new` 3,718,427〜3,718,433 で差が無い。全体のピーク RSS の平均の差は +23 kB。

### 1回の呼び出しあたり

`normalBoard()` の呼び出しを1回 2〜3 ns と見込んでいた。F1 は約12〜13億回で −2.53 秒なので **約 2.0 ns**、P2 は辺の本数
（約 9.4 億）以上呼ばれて −0.89 秒なので **1 ns 以下**（どちらも、ほかの呼び出しが PLT を通らなくなったぶんと置き場所の
効果を含めて、`normalBoard()` の回数で割っただけの値）。P2 の1回あたりは F1 の半分以下だった。P2 の生成器の呼び出しは
`buildSuccRange()` → `nextBoardIndexNormal()` で、生成した後続ごとに索引を引く（DRAM の待ちが長い）。呼び出しの手間は
その待ちに F1 より多く隠れていたと読めるが、測っていない（性能カウンタは取っていない）。

### 予測と実測

| | 予測（`new − old`） | 実測 | |
|---|---|---|---|
| **F1 のユーザー時間** | 下がる。区間が 0 をまたがない。−1.5〜−4 秒（中心 −2.5 秒前後） | −2.53（−2.95 … −2.11） | ✅ |
| **P2 のユーザー時間** | 下がる向き（参考の見込み −1〜−3 秒は判定に使わない） | −0.89（−1.14 … −0.63） | ✅ 向き。参考の見込みは下回った |
| F1・P2 のカーネル時間 | 区間が 0 をまたぐ | F1 −0.00（−0.04 … +0.03）、P2 +0.06（−0.00 … +0.12） | ✅（P2 は下端がほぼ 0） |
| F1・P2 の壁時計 | ユーザー時間とほぼ同じだけ下がる | F1 −2.54、P2 −0.83 | ✅ |
| 動かないはずの段 | 止める条件4に掛からない | どれも区間が 0 をまたいだ | ✅ |
| minor fault ／ ピーク RSS | 変わらない | 差なし / +23 kB | ✅ |
| 巨大ページ | 12本とも全部に付く | そのとおり | ✅ |
| `dat/` | 12本とも #26 本走とバイト一致 | 一致 | ✅ |
| 完走タイム | 幅を出さない（参考の見込みは −3〜−7 秒） | −3.40（−4.06 … −2.74） | — |

#18 のコード（F1 約 98 秒）での −3.75 / −3.92 秒（壁時計）に対して、今回の F1 は −2.54 秒（壁時計）。
差どうしを引き算して偏りを出すことはしない（コードも本数も並べ方も違う）が、1回あたりの節約は #18 の頃より小さく出た。

## 集計

```bash
python3 experiments/gate_27_no_interposition/stop_rule.py    # 止める条件
python3 experiments/gate_27_no_interposition/f1p2_split.py   # 判定の量と、予測に登録した量
python3 experiments/gate_stats.py gate_27_no_interposition forward
python3 experiments/gate_stats.py gate_27_no_interposition spans
python3 experiments/gate_27_no_interposition/calls.py   runs/exp_g27_r1a_old/animal_shogi.so runs/exp_g27_r1b_new/animal_shogi.so
python3 experiments/gate_27_no_interposition/symbols.py runs/exp_g27_r1a_old/animal_shogi.so runs/exp_g27_r1b_new/animal_shogi.so
```

## ファイル

| | |
|---|---|
| [`build_arm.sh`](build_arm.sh) | 腕のソースを写し、その実装の `Makefile` でビルドし、`.so` の sha256 の先頭を出す |
| [`run_one.sh`](run_one.sh) | 走る前にノード0の空きを確かめ、完走を1本測って検査し、生ログを `logs/` に写す |
| [`run_all.sh`](run_all.sh) | 12本を上の順で回す。進行は `logs/console.log`（回す前の負荷は load average と CPU 使用率の合計だけ） |
| [`free_snapshot.sh`](free_snapshot.sh) | 起動する前やキャッシュを落とす前後の空きメモリを `logs/free_<名前>.txt` に残す |
| [`stop_rule.py`](stop_rule.py) / [`f1p2_split.py`](f1p2_split.py) | 止める条件 / 判定の量と内訳 |
| [`calls.py`](calls.py) / [`symbols.py`](symbols.py) | 2腕の `.so` の `call` の行き先 / 関数の番地のずれ |
| [`lib.sh`](lib.sh) | 周波数の標本・vmstat・md5 一覧・空きブロックの読み（`gate_26_inv_bits` の写し） |
