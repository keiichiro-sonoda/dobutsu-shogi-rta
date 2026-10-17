# mirror1_keep: 「鏡像を1回にする」を #36 の上で作り直し、候補の並びを保つ版と比べる（記録試行ではない）

番号を取らず、`impl/` を作らず、タイムを `results/` にも README の記録表にも載せない。

**この実験は、次の記録の方針を決めるためのものではない。** 次の記録試行 #37 は、並びを保たない `mirror1` で進めると本人が決めている
（記録が競うのは同じ答えをどれだけ速く出すかで、ファイルの中の並びは答えに入っていない。答えは手数ごとに束ねた集合の比較
[`sorted_compare_34/depth_compare.py`](../sorted_compare_34/depth_compare.py) で確かめられる）。ここでは、並びを保とうとするとどうなるかを**知るため**に回す。
結果がどうであっても #37 の方針は変えない。ここで作り直した `mirror1` のパッチ（[`patches/mirror1.patch`](patches/mirror1.patch)）は、そのまま #37 の実装に使う。

## 腕（3本）

どの腕も `impl/36_bb_unmove` の写しにパッチを当てて作る（[`build_arm.sh`](build_arm.sh)）。変えるのは逆向きの生成器とその下請け（`unmoveCandidates`・`unmoveRaw`・`unmovePiece`・
`unmoveCaptures`・`unmoveEmit`）だけ。`unmoveStep()`・全探索の側・`.py`・`Makefile`・`hot_layout.ld` は触らない（関数名も同じ。新しい熱い関数は無い）。

| 腕 | 中身 | `.so`（sha256 の先頭） |
|---|---|---|
| `base` | `impl/36_bb_unmove` のまま。候補の並びは「q から戻した正規形の候補（q の走査順）→ 鏡像の q から戻した正規形の候補（鏡像の q の走査順）」 | `c7106b9e0aaf`（#36 本走と同じ） |
| `mirror1` | q だけから戻して正規化する。**並びは変わる** | `1730c3fdcb0b` |
| `mirror1_keep` | `mirror1` と同じく q だけを走査し、そのうえで候補の並びを `base` と完全に同じにする | `a5aad0032f39` |

### `mirror1`（#36 の上で作り直した。[`patches/mirror1.patch`](patches/mirror1.patch)）

数え方は [`unmove_gen`](../unmove_gen/) と同じ2つの規則。
1. **q が左右対称でないとき**: 戻した候補 c ごとに正規形 N(c) を出し、**c が左右対称なら2回出す**（`out[n] = out[n+1] = N(c); n += 1 + (c が対称)`）
2. **q が左右対称なとき**: 今と同じく、c が正規形のものだけを残す

#36 の逆向きの生成器（ビットボード型）の `unmoveEmit`・`unmoveCaptures`・`unmovePiece`・`unmoveRaw` に「正規化して出すか」の引数 `nrm` を足し、`unmoveCandidates` が
q の対称で2通りに呼ぶ（定数の引数で、インライン展開で畳まれる）。`unmove_gen` の `mirror1` を #36 のコードに当て直したもので、考え方は同じ。

### `mirror1_keep` の並べ直しの方法（回す前に1つに決めた）

**鍵を作って、溜めた候補だけを小さく並べ替える**方法にした（[`patches/mirror1_keep.patch`](patches/mirror1_keep.patch)）。

- q を1回だけ走査する。戻した候補 c ごとに:
  - c が正規形なら、すぐ `out` に出す（`base` の前半 ＝ q の走査順と同じ）
  - c が正規形でなければ、鏡像 N(c) を**溜める**。c が左右対称なら、`out` に出したうえで、2回目として c も溜める（`base` では鏡像の q からも同じ c が出ていた）
- 溜めるときに、**鏡像の q を走査していたら何番目に出ていたか**を表す鍵を一緒に持つ。鏡像の q では、q のマス d の駒は反転したマス d′（列 c を 2 − c にしたマス）にいて、
  `base` の並び（[`docs/records/36-bb-unmove.md`](../../docs/records/36-bb-unmove.md) の「候補の並びを保つ仕組み」）を鏡像の座標で読むと
  「d′ の番号の小さい順 → 打った手 → 元のマスを反転した s′ の番号の大きい順 → ひよこが成った候補 → 元のマスごとに取っていない版 → 取った駒4種類（`UNMOVE_CAPTURED` の順）」になる。
  そこで 鍵 ＝ (d′ × 14 ＋ 枠) × 5 ＋ 取った駒、枠は 打った手 0・元のマス 12 − s′（1〜12）・成りを戻す候補 13、取った駒は 取っていない版 0・4種類 1〜4
- q の走査が終わったら、溜めた候補を鍵の順に挿入ソートで並べ、`out` の後ろに足す（`base` の後半と同じ並び）
- q が左右対称なときは、`base` も q しか走査しないので、`base` と同じ処理（正規形だけを残す）

選んだ理由: 並びを保つ方法の別案は「鏡像の順で2回目の走査をして、生成だけを省く」だが、2回目の走査そのもの（A を作る・X の駒のマスを取り出す・元のマスの集合を作る）が
`mirror1` で省いた仕事の大半なので、それでは仕事を減らした意味が薄い。鍵は駒のマスと元のマスから足し算と掛け算だけで出せ、溜める候補は局面あたり数個（`unmove_gen` の
order 入力で、候補 5.45 個のおよそ半分）なので、挿入ソートで足りる。1つの (マス, 枠, 取った駒) からは候補が1つしか出ないので、鍵は q ごとに重ならない。

### 機械語の大きさ（`nm`。`.text.hot_layout` の中）

`unmoveCandidates` は `base` 0x1183・`mirror1` 0x1139・`mirror1_keep` 0x1513 バイト（`unmove_gen` の `check_asm.py` で数えた条件分岐は 88・80・106。数は機械語の中の個数）。
後ろに並ぶ `unmoveInit`・`unmoveStep`・`unmoveDraws` は、`base` から `mirror1` で −0x80（−128 バイト）、`mirror1_keep` で ＋0x380（＋896 バイト）ずれる。前に並ぶ全探索の関数は動かない。
3腕とも `-Wall -Wextra` の警告 0、`-g` を足しても `.text` は同じ。

## 回す前に確かめたこと

- **作りの確かめ**: パッチを書いた段階で、`verify.c` を #36 本走の `dat/` の `unknown000.bin`（2,682,700 局面）にだけ通した。`mirror1_keep` は並びまで、`mirror1` は多重集合で、
  どちらも不一致 0（ログは残していない。計時はしていない）。下の見込みには使っていない。全局面の検査は登録のあとに回す
- `check_full.py` を #36 本走の `dat/` 自身に当てて、md5 一覧の形で PASS することを確かめた。`summary.py` と `compare_stats.py` は、`unmove_gen` と門番 #36 のログを入れ替えて
  動くことだけを確かめた（出た数は使わない）

## 一致の検査と完走の答え合わせ（計時の前に。[`run_all.sh`](run_all.sh)）

- 一致の検査（[`run_verify.sh`](run_verify.sh)、[`verify.c`](verify.c) は `unmove_gen` の写しで注記だけを直した）: #36 本走の `dat/`（全 213 ファイル、到達可能な全 246,803,167 局面）を q にして、
  `base` と腕の `unmoveCandidates()` を比べる。`mirror1_keep` は候補の数と列（並びまで）、`mirror1` は候補の数と並べ替えた列（多重集合。食い違ったら q が対称か × A の大きさで分けて数え、
  片方にだけある候補が対称かも数え、最初の 20 個を残す）
- 完走の答え合わせ（[`run_full.sh`](run_full.sh)、[`check_full.py`](check_full.py)。計時には使わない）: 両腕を1本ずつ。`mirror1_keep` は `dat/` の md5 一覧の sha256 が #36 本走と同じ
  （`851de9569efc…`）。`mirror1` はオラクル174行・指紋 176 項目・全探索の側のファイルのバイト一致・ファイルの名前と件数・手数ごとに束ねた集合の一致。
  後退解析の側のファイルのうち #36 とバイトまで同じものの数も出す

## 測るもの

### 1. 生成器だけのベンチ（並べ直しの費用。[`run_bench.sh`](run_bench.sh)）

`unmove_gen` と同じ作り。`perf_34` の `glue.c`・`bench.c` の `benchUnmove`（逆向きの生成器 ＋ 候補ごとの `rankOf`）を、腕ごとにその腕の `animal_shogi.c` を取り込んだ `bench.so` で回す。
`base` の `bench.so` は `unmove_gen` の `bb_unmove` のもの（同じ C）とバイト一致することを見る。入力は order（`perf_34` の `u_*.bin` 174 個）と random（`sample_unmove.bin`）。
`perf stat -e cycles:u,instructions:u,br_inst_retired.all_branches:u,br_misp_retired.all_branches:u`、3腕 × 7周、周ごとに腕の順を1つずつずらす。
`numactl --cpunodebind=0 --membind=0`。差は同じ周の差を周ごとに取ってから、中央値と範囲。候補の数と番号の和、戻した数（[`run_counts.sh`](run_counts.sh)）も出す。
**並べ直しの費用 ＝ `mirror1_keep` − `mirror1`**（ベンチは局面を処理する順が腕で同じなので、並びの効果は入らず、並べ直しの仕事だけが出る）。集計は [`summary.py`](summary.py)

### 2. 完走での比較（並びの効果を分ける。[`run_compare.sh`](run_compare.sh)）

**記録の門番ではない**（判定・本走はしない）。3腕 × 6本 ＝ 18本、どれも `numactl --cpunodebind=0 --membind=0`。各本の前にノード0の 2 MiB 以上の空きを読んで
`logs/compare/<ラベル>_hugefree.txt` に残し、16 GiB に満たなければ走らせずに止める（[`run_one.sh`](run_one.sh)。門番 #36 の写し）。

| ブロック | 1本目 | 2本目 | 3本目 |
|---|---|---|---|
| b1 | `base` | `mirror1` | `mirror1_keep` |
| b2 | `mirror1` | `mirror1_keep` | `base` |
| b3 | `mirror1_keep` | `base` | `mirror1` |
| b4 | `base` | `mirror1_keep` | `mirror1` |
| b5 | `mirror1_keep` | `mirror1` | `base` |
| b6 | `mirror1` | `base` | `mirror1_keep` |

どの腕もブロックの中の各位置に2回ずつ来る。ブロックの中で、ある腕のすぐ後ろに来る腕も、ほかの2腕に2回ずつ。

- 各本の答えの検査: `base`・`mirror1_keep` は `dat/` の md5 一覧が #36 本走と同じ、`mirror1` は指紋・全探索の側のバイト一致・名前と件数・手数ごとの集合。どれもオラクル174行、
  `forward.tsv` の件数の列が `results/36_bb_unmove/forward.tsv` と一致、`thp_fault_fallback` 0、巨大ページが表と配列に付いている。外れたら `dat/` を残して止める
- 出すもの（[`compare_stats.py`](compare_stats.py)）: 完走・ユーザー時間・カーネル時間・minor fault・ピーク RSS、全探索・F1、後退解析（完走 − 全探索）と段の合計 `retreat_total`、
  `U_init`・`U_loop`（ユーザー時間とカーネル時間）・`U_draw`・`U_uk` の腕ごとの平均と範囲、腕どうしの差の Welch の 95% 区間（3つの比較で、多重比較は未補正）

### 分け方（回す前に決めた）

- `mirror1_keep` − `base` ＝ 仕事が減った効果 ＋ 並べ直しの費用（並びは同じ）
- `mirror1` − `base` ＝ 仕事が減った効果 ＋ 並びが変わった効果
- `mirror1` − `mirror1_keep` ＝ 並びが変わった効果 − 並べ直しの費用。**並びが変わった効果の見積もり ＝ (`mirror1` − `mirror1_keep`) ＋ 並べ直しの費用**。
  並べ直しの費用は、ベンチの `mirror1_keep` − `mirror1` の cycles を `U_loop` の秒に換算した値（× 103,821,853 ÷ 周波数。`unmove_gen` と同じ式）で置く。
  ベンチの費用は生成器だけの文脈の値なので、本物の `U_loop` での費用とは違いうる。**見積もりとして書く**。完走の差の区間に、換算の費用の範囲（7周の最小〜最大）を足した幅も並べる

## 条件

- 回す前に、`kernel.perf_event_paranoid` が 1、`impl/36_bb_unmove` に `__pycache__` が無い、CPU 使用率（全 CPU）が 3% 以下（ほかの計算が動いていない）を確かめる。
  load average と CPU 使用率だけを残す。合わなければ回さずに本人に知らせる
- 巨大ページの空きが足りなければ止めて本人に知らせる（キャッシュは本人が落とす）
- `runs/` の中身（`dat/`・入力）はコミットしない

## 止める条件（回す前に決めた）

1. `mirror1_keep` の一致の検査で、候補の列が1局面でも `base` と違う（並びも含む）。または完走の `dat/` が #36 本走とバイト一致しない → `mirror1_keep` は計時しない
2. `mirror1` の一致の検査で、多重集合が1局面でも `base` と違う。または完走でオラクル・指紋・手数ごとの集合のどれかが外れる → **止めて報告する**（#37 に使うパッチなので、外れたまま先に進まない）
3. `mirror1_keep` で、並びを保つ方法が決められない・作れない箇所が見つかる（直し方を自分で決めずに報告する）
4. 巨大ページの空きが足りない、`perf_event_paranoid` が 1 でない

## 見込み（回す前に書いた）

`unmove_gen`・`gate_36_bb_unmove` の結果と、ソースの構造だけから書いた。`base` の order の手がかりは `unmove_gen` の `bb_unmove`（cycles 937.2・予測ミス 7.61 / 局面）。
`unmove_gen` の見積もり（生成器の外 R ≈ 306 cycles、`bb_unmove` の生成器 G′ ≈ 631 cycles。`mirror1` が生成器の仕事をちょうど半分にするなら −316 cycles）を中心に置く。

| | 見込み | 根拠 |
|---|---|---|
| 一致の検査・完走 | 2腕とも通る。`mirror1` の後退解析の側で #36 とバイトまで同じファイルは 3〜12 個 | `unmove_gen` の `mirror1`（#35 の上）で 7 個 |
| `base` の order | cycles 910〜965、予測ミス 7.4〜7.8（`unmove_gen` の `bb_unmove` の ±3%） | 同じ C（`bench.so` もバイト一致するはず） |
| 候補の数・番号の和 | 3腕で同じ。戻した数は `mirror1`・`mirror1_keep` が `base` の約半分 | 多重集合が同じ |
| `mirror1` − `base`（order） | cycles −220〜−380、予測ミス −2.5〜−4.0 | 上の中心 −316 に幅。予測ミスは生成器の分（`bb_unmove` の 7.61 のうち、ベンチの外枠 0.6 を除いた 7.0）が半分になる |
| **`mirror1_keep` − `mirror1`（並べ直しの費用、order）** | **cycles ＋60〜＋200、予測ミス ＋1.0〜＋3.0** | 候補ごとに鏡像を作る・正規形かで出し先が分かれる（`mirror1` は分かれずに N(c) を書く）・鍵を作って溜める仕事と、q ごとの挿入ソート（溜めるのは数個。比べる分岐はデータで転ぶ）と写し |
| `mirror1_keep` − `base`（order） | cycles −40〜−300 | 上の2行の和 |
| `U_loop` の秒への換算 | `mirror1` − `base` −6.7〜−11.6 秒、並べ直しの費用 ＋1.8〜＋6.1 秒 | cycles × 103,821,853 ÷ 約 3.42 GHz |
| 完走 `mirror1` − `base` | −6〜−13 秒、区間の上端は 0 より下 | 換算の中心 −9.6 秒に、門番で換算の 90〜111% が出たこと（#35・#36）と、並びの効果（下）の幅 |
| 完走 `mirror1_keep` − `base` | −2〜−10 秒 | 上から並べ直しの費用を引いた分 |
| 完走 `mirror1` − `mirror1_keep` | −1〜−7 秒 | 並べ直しの費用（換算 ＋1.8〜＋6.1）と、並びの効果 ±1.5 秒 |
| 並びが変わった効果（見積もり） | ±1.5 秒の中（向きは決めない） | 並びが変わると後退解析の次の段のフロンティアの順が変わり、似た局面が続く度合いと手数の配列を引く順が変わる。ただし `unmove_gen` の `bb_unmove` は、並びを崩した random でも order より ＋69 cycles / 局面しか重くなかった（`base` の #35 の生成器では ＋310）。生成器の予測は並びにあまり左右されなくなっている。手数の配列の読みはもともと先読みで隠れている（`perf_34` の memory bound 8.1%） |
| 全探索・`U_init`・`U_draw`・`U_uk`・minor fault・ピーク RSS | ±0.5 秒・±0.5% | コードは同じ。後ろの3関数のずれ（−128・＋896 バイト）の分は `U_init` などに出うる（#36 では ＋576 バイトのずれと一緒に `U_init` が ＋0.13 秒） |
