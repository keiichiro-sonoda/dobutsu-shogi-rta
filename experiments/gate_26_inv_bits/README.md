# 門番 #26: 盤面の反転 `invBoard()` をループ無しにする（記録試行ではない）

`impl/26_inv_bits` は、C の `invBoard()`（先手と後手を入れ替える）の中身だけを、ループと分岐の無い形に替える。
コードは [`gen_bench`](../gen_bench/)（記録ではない）の候補 B、[`invbits.patch`](../gen_bench/patches/invbits.patch) のまま。

| | #25 まで（`baseline/` から変わっていない） | #26 |
|---|---|---|
| 作り方 | 12マスを1つずつ読み、空きマスを飛ばし、駒のあるマスを反対側へ置き直す | 8バイトの逆順 → 各バイトの上下4ビットの入れ替え → 駒のあるマスだけ所有者ビットを反転（マスク） |
| 単体の時間（gen_bench） | 46.5 ns | 4.4 ns |

出力は全 246,803,167 局面で旧版と1ビットも違わないことを gen_bench で確かめてある。生成器の戻り値と後続の列
（順番を含む）も変わらないので、`dat/` は #25 とバイト一致するはず。`invBoard()` を呼ぶのは
`nextBoardInvNormal()` の冒頭だけで、F1（全探索の全局面）と P2（後退解析の未知局面）の両方から呼ばれる。

## 腕と配置

| 腕 | 中身 |
|---|---|
| `old` | `impl/25_huge_retreat` |
| `new` | `impl/26_inv_bits`（`old` に `invbits.patch` を足したもの） |

`.py`・`.h`・`Makefile` は2腕でバイト同一で、C の差が `invBoard()` だけであること（コメントを除く）は
`tests/test_impl_26_inv_bits.py` が固定している。#25 で計装と片付けを入れ終えているので、`old` は `impl/25` そのものでよい。
[`build_arm.sh`](build_arm.sh) は毎本 `.so` の sha256 の先頭を進行ログに出す（`old` は #25 本走と同じ `ed5df6fa4b89`、`new` は回す前にビルドして `dd411cfbf38b` だった）。

単位は完走（空の `dat/` から `python3 ./animal_shogi.py` を1本）。`old new new old` を3ブロック、計12本（各腕6本）。
どの本も `numactl --cpunodebind=0 --membind=0` でノード0に固定する（[`run_all.sh`](run_all.sh)）。

**各本の前に、ノード0の 2 MiB 以上の空きブロック（`/proc/buddyinfo` の order 9 以上）が 16 GiB 以上あるかを見る**
（[`run_one.sh`](run_one.sh)。記録は `logs/<ラベル>_hugefree.txt`）。足りなければその本を走らせずに止める。
起動する前に空きを確かめるとき、キャッシュを落とす前と後には [`free_snapshot.sh`](free_snapshot.sh) で
`logs/free_<名前>.txt` に残す。

### ⚠️ 関数の置き場所がずれる

`invBoard()` はファイルの前のほう（`normalBoard()`・`nextBoardInvNormal()` より前）にあるので、長さが変わると後ろの関数が
ずれる。回す前に2腕をビルドして `nm` で比べた（[`symbols.py`](symbols.py)。門番の本が作った `.so` での表は回したあとで
`logs/symbols.txt` に残す）。

- `invBoard()` は 87 → 137 バイト。後ろの関数（`nm` に出る25個）は、いちばん熱い `normalBoard()` と
  `nextBoardInvNormal()`、F1 の `expandRound()`・`nextBoardSeenNormal()`、P2 の `buildSuccRange()`・`nextBoardIndexNormal()`
  を含めて、どれも **+48 バイト**ずれる。前にある `main`・`showBoard`・`invBoard` の番地は動かない
- 関数の先頭は 16 バイト境界のままだが、64 バイトの線の中の位置は全部変わる（`normalBoard()` と `nextBoardInvNormal()` は
  32 → 16、`expandRound()` と `nextBoardSeenNormal()` は 0 → 48、`buildSuccRange()` と `nextBoardIndexNormal()` は 16 → 0）

#23・#25 では、ずれた関数の段が 1 秒前後動いたことがあった（#25 の門番で P2 −0.84）。
**F1・P2 の差にはこの置き場所の効果も混ざりうる（分けられない）。F1・P2 以外の段（P1・P4・174段ループなど）が 1 秒前後
動いても、このレバーの効果に数えない。**

## 判定に使う量

**F1 と P2**（`forward_summary.tsv` / `retreat_summary.tsv` の生値）と、それぞれのユーザー時間・カーネル時間
（F1 は `utime_F1` / `stime_F1`、P2 は境界 P1 → P2 の差。[`f1p2_split.py`](f1p2_split.py)）。比較は `old` 対 `new` の1本だけ。
段ごとの全表は `gate_stats.py`（`forward` / `spans`）。完走の壁時計も出すが、判定には使わない。

## 止める条件（[`stop_rule.py`](stop_rule.py)）

どれかに掛かったら、本走の前に止めて報告する。

1. どれかの本の `dat/` が #25 本走とバイト一致しない（md5 一覧の sha256 を
   `results/25_huge_retreat/bytecompare.txt` の値と照合）、件数の列（`n_in`・`n_win`・`n_lose`・`n_uk`・`n_new_post`）が
   `results/25_huge_retreat/forward.tsv` と違う、またはオラクル174行で落ちた
2. F1 か P2 の `new − old` の 95% 区間が 0 をまたがずに上（遅くなった）
3. どれかの本で `/proc/vmstat` の `thp_fault_fallback` の前後差が 0 でない、または巨大ページが表と配列の全部に付かない
   （両腕とも、発見済み表 `anonhuge_seen_kB` 4,194,304 kB・索引 `anonhuge_index_kB` 8,388,608 kB・後退解析の配列
   `anonhuge_loop_kB` 4,972,544 kB 以上。#25 の門番の12本と本走はどれもこの値以上）

ほかに、落ちた本が無いことも見る。1・3 は `run_one.sh` が毎本その場で見る。

## 予測（門番を回す前に書いた）

gen_bench の換算は「生成器だけの差 × 本番の件数」。生成器を温めて測った値で、本番では F1 の発見済み表への挿入・
P2 の索引引きと並ぶ。gen_bench の中では `invBoard()` 単体の差（−42.1 ns）が生成器の差（−38〜−40 ns）にほとんどそのまま
出たので、本番でも大半は出ると見る。ただし本番の F1・P2 は表を引く待ちが長く、その待ちのあいだに反転の計算が
いくらか隠れていた（ループの分岐の読み違いは隠れにくいが、計算そのものは隠れうる）と考え、換算の 6〜10 割を見込む。

| | 予測（`new − old`） | 根拠 |
|---|---|---|
| **F1** | 下がる。区間が 0 をまたがない。**−6〜−10 秒**（換算 −9.72 と同じ桁） | 3種類の局面すべてで 38〜40 ns ずつ下がった × 246,803,167 |
| **P2** | 下がる。区間が 0 をまたがない。**−2.5〜−4 秒**（換算 −3.98 と同じ桁） | 未知局面で −40.0 ns × 99,485,568 |
| F1・P2 の内訳 | ほぼ全部ユーザー時間から。カーネル時間は区間が 0 をまたぐ | 計算を減らす変更で、確保もページも変えない |
| それ以外の段 | 誤差内。置き場所で ±1 秒程度動いても数えない | コードは同じ |
| minor fault ／ 全体のピーク RSS | 変わらない（minor fault は差が数百回以内、ピーク RSS は数 MiB 以内） | 確保を変えない |
| 巨大ページ | 両腕の12本とも、表と配列の全部に付く | #25 と同じ確保 |
| `dat/` | 12本とも #25 本走とバイト一致 | 出力が同じ |
| 完走タイム | 幅を出さない（参考の見込みは −9〜−14 秒） | |

下回っても外れとしない（gen_bench は生成器だけのマイクロベンチなので、本番でどこまで出るかを測るのがこの門番の役目）。
**F1 と P2 の実測が換算の何割だったかを、記録ノートに残す。**

## 集計

```bash
python3 experiments/gate_26_inv_bits/stop_rule.py    # 止める条件
python3 experiments/gate_26_inv_bits/f1p2_split.py   # F1 と P2 の内訳と、予測に登録した量
python3 experiments/gate_stats.py gate_26_inv_bits forward
python3 experiments/gate_stats.py gate_26_inv_bits spans
python3 experiments/gate_26_inv_bits/symbols.py runs/exp_g26_r1a_old/animal_shogi.so runs/exp_g26_r1b_new/animal_shogi.so
```

## ファイル

| | |
|---|---|
| [`build_arm.sh`](build_arm.sh) | 腕のソースを写してビルドし、`.so` の sha256 の先頭を出す |
| [`run_one.sh`](run_one.sh) | 走る前にノード0の空きを確かめ、完走を1本測って検査し、生ログを `logs/` に写す |
| [`run_all.sh`](run_all.sh) | 12本を上の順で回す。進行は `logs/console.log`（回す前の負荷は load average と CPU 使用率の合計だけ） |
| [`free_snapshot.sh`](free_snapshot.sh) | 起動する前やキャッシュを落とす前後の空きメモリを `logs/free_<名前>.txt` に残す |
| [`stop_rule.py`](stop_rule.py) / [`f1p2_split.py`](f1p2_split.py) | 止める条件 / 判定の量の内訳 |
| [`symbols.py`](symbols.py) | 2腕の `.so` の関数の番地のずれ |
| [`lib.sh`](lib.sh) | 周波数の標本・vmstat・md5 一覧・空きブロックの読み（`gate_25_huge_retreat` の写し） |
