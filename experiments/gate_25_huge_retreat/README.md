# 門番 #25: 後退解析の配列を巨大ページにする（記録試行ではない）

`impl/25_huge_retreat` は、後退解析の4つの配列を Python の `array` / `bytearray`（4 KiB ページ）ではなく、
索引と同じ C の `hugeAlloc()` で確保する（`hugeFill()`）。

| 配列 | 大きさ | 使う段 |
|---|---|---|
| `pred` | 辺 938,671,869 × 4 B ≒ 3.5 GiB | P4・174段ループ |
| `pred_off` | (246,803,167 ＋ 1) × 4 B ≒ 0.9 GiB | P4・174段ループ |
| `cnt` | 99,485,568 B ≒ 95 MiB | P2・174段ループ |
| `dtm` | 246,803,167 B ≒ 235 MiB | 174段ループ |

コードは [`lever_scan_2`](../lever_scan_2/)（記録ではない）の [`hugeR.patch`](../lever_scan_2/patches/hugeR.patch) のまま。
lever_scan_2 は6腕を `base`（#22 ＋ 計装）に対して引いていて、多重比較は未補正。この門番で、記録にする版そのものを
1対1で測り直す。

## 腕と配置

| 腕 | 中身 |
|---|---|
| `old` | `impl/24_reuse_buffers` ＋ 計装（lever_scan_2 の [`instr.patch`](../lever_scan_2/patches/instr.patch)）＋ 受け皿の片付け（[`patches/release.patch`](patches/release.patch)） |
| `new` | `impl/25_huge_retreat`（`old` に `hugeR.patch` を足したもの） |

**`old` を #24 そのものにしない。** 計装（段ごとの minor fault と、後退解析の配列の巨大ページの読み）と、受け皿を全探索の
終わりで手放す片付けは、どちらも #25 で入れるが変数に数えない。片方の腕にだけ入ると、その差が `hugeR` の効果に混ざる
（#21 の門番が `old` を「#20 ＋ 計装」にしたのと同じ理由）。`old` ＋ `hugeR.patch` が `impl/25` とコード（コメントを除く）で
一致することは `tests/test_impl_25_huge_retreat.py` が固定している。[`build_arm.sh`](build_arm.sh) は毎本 `.so` の sha256 の
先頭を進行ログに出す（`old` の `.so` は #23・#24 と同じはず。`new` は `hugeFill()` を足したぶん違う）。

単位は完走（空の `dat/` から `python3 ./animal_shogi.py` を1本）。`old new new old` を3ブロック、計12本（各腕6本）。
どの本も `numactl --cpunodebind=0 --membind=0` でノード0に固定する（[`run_all.sh`](run_all.sh)）。

**各本の前に、ノード0の 2 MiB 以上の空きブロック（`/proc/buddyinfo` の order 9 以上）が 16 GiB 以上あるかを見る**
（[`run_one.sh`](run_one.sh)。記録は `logs/<ラベル>_hugefree.txt`）。足りなければその本を走らせずに止める。
起動する前に空きを確かめるとき、キャッシュを落とす前と後には [`free_snapshot.sh`](free_snapshot.sh) で
`logs/free_<名前>.txt` に残す。

## 判定に使う量

**P4（`P4_count`・`P4_scatter`）と `loop174`**（`retreat_summary.tsv` の生値）と、それぞれのユーザー時間・カーネル時間
（境界の差。[`p4_split.py`](p4_split.py)）。比較は `old` 対 `new` の1本だけ。
段ごとの全表は `gate_stats.py`（`forward` / `spans`）。完走の壁時計も出すが、判定には使わない。

## 止める条件（[`stop_rule.py`](stop_rule.py)）

どれかに掛かったら、本走の前に止めて報告する。

1. どれかの本の `dat/` が #24 本走とバイト一致しない（md5 一覧の sha256 を
   `results/24_reuse_buffers/bytecompare.txt` の値と照合）、件数の列（`n_in`・`n_win`・`n_lose`・`n_uk`・`n_new_post`）が
   `results/24_reuse_buffers/forward.tsv` と違う、またはオラクル174行で落ちた
2. P4 か `loop174` の `new − old` の 95% 区間が 0 をまたがずに上（遅くなった）
3. どれかの本で `/proc/vmstat` の `thp_fault_fallback` の前後差が 0 でない
4. `new` のどれか1本で `anonhuge_loop_kB` が 4,972,544 kB に届かない（4配列をそれぞれ 2 MiB に切り上げた量:
   `pred` 3,667,968 ＋ `pred_off` 964,608 ＋ `cnt` 98,304 ＋ `dtm` 241,664。lever_scan_2 の `hugeR` の12本はどれもちょうどこの値）

ほかに、落ちた本が無いことも見る。1・3・4 は `run_one.sh` が毎本その場で見る。

## 予測（門番を回す前に書いた）

lever_scan_2 の値は `hugeR − base`（単独。6本ずつ）と、先読みの上に重ねた `all − pf3`（`all` は `pf3` ＋ `hugeR` ＋ `reuse`）。
`base` は #22 ＋ 計装で、この門番の `old` とは174段ループの先読みと受け皿の使い回しのぶん違う。

| | 予測（`new − old`） | 根拠 |
|---|---|---|
| **P4** | 下がる。区間が 0 をまたがない。lever_scan_2 の −3.48 と同じ桁 | P4 の先読みは `P4_scatter` にしか無く、lever_scan_2 の `all − pf3` でも −3.47 とほぼ単独と同じ |
| P4 の内訳 | `P4_count` と `P4_scatter` の両方が下がり、どちらもユーザー時間とカーネル時間の両方から | lever_scan_2 は `P4_count` −1.12（ユーザー −0.96、カーネル −0.15）、`P4_scatter` −2.37（ユーザー −1.81、カーネル −0.56）。番地の翻訳が速くなるぶんと、ページを用意する回数が減るぶん |
| **`loop174`** | 下がる。**ただし −1.5 秒前後と小さい**（単独の −7.91 より大きく目減りする） | #23 の先読みと待ちを取り合う。lever_scan_2 の `all − pf3` は −1.54（ユーザー −1.58） |
| `loop174` の内訳 | ユーザー時間から下がる。カーネル時間は区間が 0 をまたぐ | lever_scan_2 は単独でもカーネル +0.02（区間が 0 をまたぐ） |
| `R_dtm` | 少し下がる（−0.2 秒前後。ほとんどカーネル時間） | `dtm` の確保の段。lever_scan_2 は −0.24（カーネル −0.19） |
| P2 | ±1.5 秒程度動くかもしれない。**動いてもレバーの効果に数えない** | C に `hugeFill()` を足すと後ろの関数の番地がずれる。lever_scan_2 の `hugeR` で `P2_loop` が −1.28 動いたが、番地のずれか `cnt` の巨大ページかは分けていない |
| F1 | ±1 秒程度。同じ理由で数えない | lever_scan_2 の `hugeR` で F1 +0.62（区間が 0 をまたぐ） |
| minor fault の合計 | 約 131 万回減る | lever_scan_2 の `hugeR` は −1,308,401（P4 −1,155,425、`R_dtm` −128,641、`P2_alloc` −24,239）。2 MiB ページ1枚で 4 KiB ページ 512 枚ぶんのフォルトが1回になる |
| `anonhuge_loop_kB` | `new` は6本とも 4,972,544 kB、`old` は6本とも 0 | lever_scan_2 |
| 全体のピーク RSS | `old` と `new` で変わらない | 配列の大きさは同じ。lever_scan_2 の `hugeR` は +657 kB |
| `dat/` | 12本とも #24 本走とバイト一致 | 確保の仕方だけが違う |
| 完走タイム | 幅を出さない（参考の見込みは −4〜−6 秒） | |

lever_scan_2 の値は多重比較未補正（6本）で、#24 では狙った段の効果が2割目減りした。下回っても外れとしない。

**`loop174` の「−1.5 秒前後」がこの門番でいちばん確かめたい予測。** 単独の −7.91 がそのまま出たら、
「先読みと巨大ページは待ちを取り合う」という lever_scan_2 の読みが外れていることになる。

## 集計

```bash
python3 experiments/gate_25_huge_retreat/stop_rule.py   # 止める条件
python3 experiments/gate_25_huge_retreat/p4_split.py    # P4 と loop174 の内訳と、予測に登録した量
python3 experiments/gate_stats.py gate_25_huge_retreat forward
python3 experiments/gate_stats.py gate_25_huge_retreat spans
```

## ファイル

| | |
|---|---|
| [`build_arm.sh`](build_arm.sh) | 腕のソースを組んでビルドし、`.so` の sha256 の先頭を出す（`old` は `impl/24` に2つのパッチを当てる） |
| [`patches/release.patch`](patches/release.patch) | 受け皿を全探索の終わりで手放す（`impl/24` ＋ `instr.patch` に当てる。`impl/25` にも同じものが入っている） |
| [`run_one.sh`](run_one.sh) | 走る前にノード0の空きを確かめ、完走を1本測って検査し、生ログを `logs/` に写す |
| [`run_all.sh`](run_all.sh) | 12本を上の順で回す。進行は `logs/console.log`（回す前の負荷は load average と CPU 使用率の合計だけ） |
| [`free_snapshot.sh`](free_snapshot.sh) | 起動する前やキャッシュを落とす前後の空きメモリを `logs/free_<名前>.txt` に残す |
| [`stop_rule.py`](stop_rule.py) / [`p4_split.py`](p4_split.py) | 止める条件 / 判定の量の内訳 |
| [`lib.sh`](lib.sh) | 周波数の標本・vmstat・md5 一覧・空きブロックの読み（`gate_24_reuse_buffers` の写し） |
