# 門番 #28: `-march=native` を足す（記録試行ではない）

`impl/28_march_native` は、`impl/27_no_interposition` の `Makefile` の `gcc` 行に **`-march=native` を1つ足しただけ**
（`-O2 -fno-semantic-interposition` は残す）。`animal_shogi.c`・`.h`・`.py` は #27 とバイト同一。
`-march=native` は `-mtune` も一緒に変える。命令セットの効果と並べ方の効果を分ける腕（`-mtune=native` だけ）は作らず、
2腕で本数を確保する。

過去の実測は [`lever_scan`](../lever_scan/) の1回だけで、#18 のコードでの値（多重比較未補正、向きは測る前に登録していなかった）:
F1 −2.40 s（区間 −4.23〜−0.56）、P2 −3.56 s（区間 −5.29〜−1.82）、後退解析の合計 −4.35 s（区間 −5.82〜−2.88）。
その後 #26（盤面の反転）と #27（インライン展開）で生成器の命令列が大きく変わったので、この門番で測り直す。

## `native` が何に解決されたか（再現のために残す）

別の CPU では別のバイナリになる。[`march.sh`](march.sh) の出力（回したときの値は `logs/march.txt`。[`run_all.sh`](run_all.sh) が最初に残す）:

| | 計測機（gcc 13.3.0） |
|---|---|
| `-march=` / `-mtune=` | **`broadwell` / `broadwell`** |
| 増える命令セット（事前定義マクロ） | AVX・AVX2・FMA・F16C・BMI・BMI2・LZCNT（ABM）・POPCNT・MOVBE・SSE3〜SSE4.2・ADX・AES・PCLMUL・RDRND・RDSEED・RTM など |

## 命令がどう変わるか（回す前に数えた）

2腕を門番と同じ手順（その実装の `Makefile`）でビルドし、`objdump -d` で関数ごとに数えた（[`insns.py`](insns.py)）。
回したあとで、門番の本が作った `.so` で数え直して `logs/insns.txt` に残す。

| 関数 | x86-64 のベースラインに無い命令（`new`） | 命令の総数 `old` → `new` |
|---|---|---|
| `nextBoardInvNormal`（生成器） | **`shlx` 18・`shrx` 6** | **322 → 285** |
| `expandRound`（F1） | `vzeroupper` 5・`vmovdqu` 2 など AVX の移動 13 | 153 → 168 |
| `buildSuccRange`（P2） | `vzeroupper` 3・`vmovdqu` 2 など AVX の移動 14 | 190 → 177 |
| `nextBoardIndexNormal`（P2） | `shrx` 2・`vmovd` など 5 | 96 → 99 |
| `indexBuild`（P1）・`seenInsert` | `shlx` 2・`shrx` 2 ずつ（ハッシュのシフト） | 148 → 144 / 変わらず |
| `nextBoardSeenNormal`（F1）・`seenContains` | `shrx` 1 ずつ | 変わらず / 29 → 28 |
| `predScatter`（P4）・`retreatStep`（174段ループ） | 無し | 82 → 84 / 192 → 194（並べ方が変わる） |
| 合計 | **0 → 69 か所** | |

- 入ったのはほぼ BMI2 のシフト（`shlx`/`shrx`。シフト量を `cl` に置かなくてよく、Broadwell では `shl r, cl` の 3 µop が 1 µop になる）と、
  AVX の移動（`vmovdqu` などで、16〜32 バイトの塊のコピー）。**BMI の `andn`・`blsr`・`tzcnt` や、`popcnt`・`movbe` は1つも入らなかった。**
  `invBoard()` の `bswap` も `movbe` にはならない（137 バイトのまま）
- ⚠️ `buildSuccRange()` に **`memcpy@plt` への呼び出しが1つ増える**（[`calls.py`](calls.py)）。後続を中継バッファへ写すループを、
  `-march=native` を付けた gcc が `memcpy` の呼び出しに替えた（`-march` と `-mtune` のどちらが決めたかは分けていない）。P2 の未知局面ごと（99,485,568 回）に PLT 経由で呼ばれるので、P2 では
  遅くなる向きの要素になる
- `.so` 全体のコード生成が変わり、関数の番地も −80〜+32 バイト動く（[`symbols.py`](symbols.py)。回したあとで `logs/symbols.txt`）

**#27 のように「生成器を通らない段は動かない」とは言えない。** P1・P4・174段ループも動いてよい前提で、段ごとに向きを先に登録する（下の予測）。

## 腕と配置

| 腕 | 中身 |
|---|---|
| `old` | `impl/27_no_interposition` |
| `new` | `impl/28_march_native`（`old` の `gcc` 行に `-march=native` を足したもの） |

2腕の差が `Makefile` のこのフラグ1つだけであることは `tests/test_impl_28_march_native.py` が固定している（2腕をそれぞれの
`Makefile` でビルドし、BMI2 を持つ CPU なら生成器に `shlx`/`shrx` が入ることと、打ち切って回した成果物のバイト一致も見る）。
[`build_arm.sh`](build_arm.sh) はその実装の `Makefile` でビルドし、毎本 `.so` の sha256 の先頭を進行ログに出す
（回す前にビルドして読んだ値は `old` が `77e88ec9d704`（#27 本走と同じ）、`new` が `5128798ef4a5`）。

単位は完走（空の `dat/` から `python3 ./animal_shogi.py` を1本）。`old new new old` を3ブロック、計12本（各腕6本）。
どの本も `numactl --cpunodebind=0 --membind=0` でノード0に固定する（[`run_all.sh`](run_all.sh)）。
各本の前に、ノード0の 2 MiB 以上の空きブロックが 16 GiB 以上あるかを見る（[`run_one.sh`](run_one.sh)）。足りなければ自分で回避せず、
止めて人にキャッシュを落としてもらう。起動する前やキャッシュを落とす前後の値は [`free_snapshot.sh`](free_snapshot.sh) で `logs/` に残す。

## 判定に使う量

**主な判定の量は F1 のユーザー時間と P2 のユーザー時間**（F1 は `utime_F1`、P2 は境界 P1 → P2 の差。[`f1p2_split.py`](f1p2_split.py)）。
命令を替える変更なので、ユーザー時間で見る。

**多重比較**: 主な量が2つなので、「下がった」と言うのは **95% 区間の上端が 0 より下で、かつ p < 0.025**（Bonferroni 補正）のとき。
2つのうち**少なくとも1つ**が下がったと言えれば記録に進む。

**同点の扱い**: F1 と P2 のユーザー時間の**どちらも**下がったと言えなければ同点とみなし、記録にしない（本走しない。
門番の結果だけをコミットして報告する）。

段ごとの全表は `gate_stats.py`（`forward` / `spans`）。後退解析の合計・P1・P4・`loop174`・完走も並べるが、判定には使わない。

## 止める条件（[`stop_rule.py`](stop_rule.py)）

どれかに掛かったら、本走の前に止めて報告する。

1. どれかの本の `dat/` が #27 本走とバイト一致しない（md5 一覧の sha256 を `results/27_no_interposition/bytecompare.txt` の値と照合）、
   件数の列が `results/27_no_interposition/forward.tsv` と違う、またはオラクル174行で落ちた
2. F1 と P2 のユーザー時間の**どちらも**下がったと言えない（上の多重比較の基準で）
3. **どの段も、区間が 0 をまたがずに 0.3 秒以上遅くならないこと**（全探索の F0〜F6 と合計、後退解析の区間の全部）。掛かったら
   本走の前に原因を調べる。`-march` は `.so` 全体を変えるので、どこかで遅くなる可能性を最初から見ておく。段の数だけ比べるので
   多重比較は未補正（安全側の条件なので、引っ掛かりやすい側でよい）
4. どれかの本で `thp_fault_fallback` の前後差が 0 でない、または巨大ページが表と配列の全部に付かない
   （両腕とも、`anonhuge_seen_kB` 4,194,304・`anonhuge_index_kB` 8,388,608・`anonhuge_loop_kB` 4,972,544 kB 以上）

ほかに、落ちた本が無いことも見る。1・4 は `run_one.sh` が毎本その場で見る。

## 予測（門番を回す前に書いた）

| | 予測（`new − old`） | 根拠 |
|---|---|---|
| **F1 のユーザー時間** | 下がる（上の基準で）。**−0.5〜−3 秒** | 生成器の命令が 322 → 285。可変シフト 24 か所が 1 µop になる。lever_scan（#18 のコード）は F1 −2.40。#26・#27 で生成器の命令列が変わったので、その値より小さい側へ寄せる |
| **P2 のユーザー時間** | 下がる（上の基準で）。**−0.5〜−3 秒** | 生成器は P2 も通る。lever_scan は P2 −3.56 で F1 より大きかったが、今回は `buildSuccRange()` に `memcpy@plt` が増えるぶん、lever_scan より小さい側へ寄せる |
| 後退解析の合計 | 下がる。−0.5〜−4 秒 | ほぼ P2 のぶん |
| P1 | 向きを決め打ちしない。大きさは 0.5 秒未満 | `indexBuild()` のハッシュのシフトが `shlx`/`shrx` になるが、P1 は索引への書き込みの待ちが主 |
| P4・174段ループ | 向きを決め打ちしない。大きさは書かない | どちらもランダムアクセス主体で、BMI/AVX の命令は入らない（並べ方だけ変わる） |
| F2・F5・F6・P0 | 動かない（区間が 0 をまたぐか、差が 0.1 秒未満） | C の中身はほとんど通らない |
| カーネル時間・minor fault・ピーク RSS | 変わらない | 確保もページも変えない |
| 巨大ページ | 12本とも表と配列の全部に付く | |
| `dat/` | 12本とも #27 本走とバイト一致 | 命令を替えても計算の結果は同じ |
| 完走タイム | 幅を出さない（参考の見込みは −1〜−6 秒） | |

## 結果（回したあとで書いた）

**止める条件には掛からなかった**（[`logs/stop_rule.txt`](logs/stop_rule.txt)）。12本とも

- オラクル174行 PASS、`dat/` は #27 本走とバイト一致（[`logs/bytecompare.tsv`](logs/bytecompare.tsv)）、件数の列は全74ラウンド一致
- `thp_fault_fallback` の前後差は 0（`compact_stall` も全本 0）、巨大ページは両腕とも表と配列の全部に付いた
- `native` は `-march=broadwell` / `-mtune=broadwell` に解決された（[`logs/march.txt`](logs/march.txt)）。`.so` の sha256 の先頭は
  `old` が `77e88ec9d704`、`new` が `5128798ef4a5` で、回す前にビルドした値と同じ。命令の表（[`logs/insns.txt`](logs/insns.txt)）・
  `call` の表（[`logs/calls.txt`](logs/calls.txt)）・番地の表（[`logs/symbols.txt`](logs/symbols.txt)）も回す前に数えたものと同じ

起動する前のノード0は 12.53 GiB で 16 GiB に届かず（[`logs/free_before_launch.txt`](logs/free_before_launch.txt)）、
人が root でキャッシュを落として 21.15 GiB にしてから起動した（[`logs/free_after_drop.txt`](logs/free_after_drop.txt)）。
12本の走る前の値は 21.15〜21.47 GiB。

### 判定の量: F1 のユーザー時間 −1.20 秒、P2 のユーザー時間 −1.64 秒（どちらも下がった）

[`f1p2_split.py`](f1p2_split.py) の出力（[`logs/f1p2_split.txt`](logs/f1p2_split.txt)）。主な量の p は F1 が 2.2 × 10⁻⁶、P2 が 1.3 × 10⁻⁶ で、
どちらも Bonferroni 補正のしきい値 0.025 を下回った。

| 量 | `old` 平均（sd） | `new` 平均（sd） | `new` − `old`（95% 区間） | p |
|---|---|---|---|---|
| F1 | 63.66（0.15） | 62.47（0.22） | -1.20（-1.44 … -0.95） | < 0.0001 |
| F1 のユーザー時間 | 60.73（0.13） | 59.53（0.22） | -1.20（-1.44 … -0.97） | < 0.0001 |
| F1 のカーネル時間 | 2.93（0.04） | 2.93（0.03） | +0.00（-0.04 … +0.05） | 0.8429 |
| P2 | 41.24（0.11） | 39.61（0.29） | -1.62（-1.93 … -1.32） | < 0.0001 |
| P2 のユーザー時間 | 39.24（0.13） | 37.60（0.26） | -1.64（-1.92 … -1.36） | < 0.0001 |
| P2 のカーネル時間 | 1.99（0.03） | 2.00（0.05） | +0.01（-0.04 … +0.07） | 0.5767 |
| P2_alloc | 0.29（0.00） | 0.29（0.00） | +0.00（-0.00 … +0.01） | 0.5033 |
| P2_loop | 40.95（0.11） | 39.32（0.29） | -1.63（-1.93 … -1.33） | < 0.0001 |
| F1 と P2 の和 | 104.90（0.24） | 102.08（0.49） | -2.82（-3.34 … -2.30） | < 0.0001 |
| P1 | 7.29（0.05） | 7.18（0.04） | -0.11（-0.17 … -0.05） | 0.0016 |
| P4 | 15.75（0.07） | 15.82（0.11） | +0.07（-0.06 … +0.19） | 0.2559 |
| loop174 | 14.58（0.08） | 14.55（0.12） | -0.03（-0.17 … +0.10） | 0.5886 |
| 全探索 合計 | 68.51（0.17） | 67.32（0.25） | -1.19（-1.47 … -0.91） | < 0.0001 |
| 後退解析 合計 | 80.95（0.24） | 79.25（0.55） | -1.69（-2.27 … -1.11） | 0.0002 |
| minor fault (万) | 371.84（0.00） | 371.84（0.00） | +0.00（-0.00 … +0.00） | 0.7362 |
| 全体のピーク RSS (GiB) | 13.84（0.00） | 13.84（0.00） | +0.00（-0.00 … +0.00） | 0.8106 |
| 完走 (秒、参考) | 149.64（0.41） | 146.75（0.78） | -2.89（-3.72 … -2.05） | < 0.0001 |

**F1 は 63.66 → 62.47 秒、P2 は 41.24 → 39.61 秒で、どちらもユーザー時間だけから下がった**（カーネル時間は区間が 0 をまたぐ）。
**P2 のほうが F1 より大きく下がった**のは lever_scan と同じ形。`buildSuccRange()` に増えた `memcpy@plt` の呼び出しは、
差し引きで P2 を遅くするほどではなかった（その呼び出しだけの費用は分けていない）。
**後退解析の合計は −1.69 秒**（区間 −2.27 … −1.11）で、ほぼ P2 のぶん。

段ごとの全表は [`logs/stats_forward.txt`](logs/stats_forward.txt) と [`logs/stats_spans.txt`](logs/stats_spans.txt)。
**区間が 0 をまたがずに遅くなった段は無い**（止める条件3）。F1・P2 のほかに区間が 0 をまたがなかったのは **P1 −0.11 秒**
（区間 −0.17 … −0.05）だけで、`indexBuild()` のハッシュのシフトが `shlx`/`shrx` になったぶんと読める（分けていない）。
P4 は +0.07（−0.06 … +0.19）、174段ループは −0.03（−0.17 … +0.10）で、どちらも区間が 0 をまたいだ。
F2・F5・F6・P0 は差が 0.01 秒以下。minor fault は `old` 3,718,424〜3,718,432、`new` 3,718,419〜3,718,431 で差が無く、
全体のピーク RSS の平均の差は +25 kB。

lever_scan（#18 のコード）の F1 −2.40・P2 −3.56 に対して、今回は F1 −1.20・P2 −1.64 で、どちらもほぼ半分だった。
コードも本数も並べ方も違うので、差どうしを引き算して偏りを出すことはしない。

### 予測と実測

| | 予測（`new − old`） | 実測 | |
|---|---|---|---|
| **F1 のユーザー時間** | 下がる。−0.5〜−3 秒 | −1.20（−1.44 … −0.97） | ✅ |
| **P2 のユーザー時間** | 下がる。−0.5〜−3 秒 | −1.64（−1.92 … −1.36） | ✅ |
| 後退解析の合計 | 下がる。−0.5〜−4 秒 | −1.69（−2.27 … −1.11） | ✅ |
| P1 | 向きを決め打ちしない。大きさは 0.5 秒未満 | −0.11（−0.17 … −0.05） | ✅ |
| P4・174段ループ | 向きを決め打ちしない | +0.07 / −0.03（どちらも 0 をまたぐ） | — |
| F2・F5・F6・P0 | 動かない | 差は 0.01 秒以下 | ✅ |
| カーネル時間・minor fault・ピーク RSS | 変わらない | F1 +0.00、P2 +0.01（0 をまたぐ）/ 差なし / +25 kB | ✅ |
| 巨大ページ | 12本とも全部に付く | そのとおり | ✅ |
| `dat/` | 12本とも #27 本走とバイト一致 | 一致 | ✅ |
| 完走タイム | 幅を出さない（参考の見込みは −1〜−6 秒） | −2.89（−3.72 … −2.05） | — |

## 集計

```bash
python3 experiments/gate_28_march_native/stop_rule.py    # 止める条件
python3 experiments/gate_28_march_native/f1p2_split.py   # 判定の量と、予測に登録した量
python3 experiments/gate_stats.py gate_28_march_native forward
python3 experiments/gate_stats.py gate_28_march_native spans
O=runs/exp_g28_r1a_old/animal_shogi.so N=runs/exp_g28_r1b_new/animal_shogi.so
python3 experiments/gate_28_march_native/insns.py "$O" "$N"
python3 experiments/gate_28_march_native/calls.py "$O" "$N"
python3 experiments/gate_28_march_native/symbols.py "$O" "$N"
```

## ファイル

| | |
|---|---|
| [`build_arm.sh`](build_arm.sh) | 腕のソースを写し、その実装の `Makefile` でビルドし、`.so` の sha256 の先頭を出す |
| [`march.sh`](march.sh) | `-march=native` が何に解決されるか（`-march=` / `-mtune=` と、増える命令セットのマクロ） |
| [`run_one.sh`](run_one.sh) | 走る前にノード0の空きを確かめ、完走を1本測って検査し、生ログを `logs/` に写す |
| [`run_all.sh`](run_all.sh) | `march.sh` を残してから12本を上の順で回す。進行は `logs/console.log`（回す前の負荷は load average と CPU 使用率の合計だけ） |
| [`free_snapshot.sh`](free_snapshot.sh) | 起動する前やキャッシュを落とす前後の空きメモリを `logs/free_<名前>.txt` に残す |
| [`stop_rule.py`](stop_rule.py) / [`f1p2_split.py`](f1p2_split.py) | 止める条件 / 判定の量と内訳 |
| [`insns.py`](insns.py) / [`calls.py`](calls.py) / [`symbols.py`](symbols.py) | 2腕の `.so` の命令 / `call` の行き先 / 関数の番地のずれ |
| [`lib.sh`](lib.sh) | 周波数の標本・vmstat・md5 一覧・空きブロックの読み（`gate_27_no_interposition` の写し） |
