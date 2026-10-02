# 門番 #29: 移動表4本を `static const` にする（記録試行ではない）

`impl/29_static_const_moves` は、`impl/28_march_native` の移動表4本（`GIRAFFE_MOVE` / `ELEPHANT_MOVE` / `LION_MOVE` /
`CHICKEN2_MOVE`）を外部リンケージの非 `const` グローバルから **`static const int`** にし、`nextBoardInvNormal()` の `moves` を
`const int *` にした版（#20 で入れた `= NULL` とその理由のコメントは残す）。`.h` からは4本の `extern` 宣言を消した。
`.py` と `Makefile`（`-O2 -fno-semantic-interposition -march=native`）は #28 とバイト同一。
#27・#28 と違って C のソースが変わる（#26 以来）。

過去の実測は [`lever_scan`](../lever_scan/) の `const` 腕だけで、#19 のコード・各腕3本・多重比較未補正の値:
F1 −0.57 s（区間 −2.15〜+1.02）、P2 −0.39 s（区間 −2.00〜+1.22）。どちらも区間が 0 をまたぎ、lever_scan の README は
「速さのレバーとしては推奨しない」と結論していた。その後、門番の作り（12本、`numactl` で固定）で #27・#28 の区間が
±0.2〜0.4 秒まで狭まったので、この大きさでも白黒が付くかを測る。**同点で終わる可能性は十分ある**（下の予測）。

## 移動表の読み方がどう変わるか（回す前に数えた）

2腕を門番と同じ手順（その実装の `Makefile`）でビルドし、[`tables.py`](tables.py) で数えた
（回したあとで、門番の本が作った `.so` で数え直して `logs/tables.txt` に残す）。

| | #28（`old`） | #29（`new`） |
|---|---|---|
| `readelf -r` の再配置 | `R_X86_64_GLOB_DAT` が4本（表ごとに1本） | **0 本** |
| `nm` の種類 | `D`（書き換えられるデータ） | **`r`（読み出し専用）** |
| 生成器で表を選ぶ命令 | `mov 0x…(%rip), %rdx` で **GOT から表の番地を読む**（4か所） | `lea 0x…(%rip), %rdx` で **表の番地を直接作る**（4か所） |
| 生成器の命令の数 | 285 | 282 |

- **表そのものを引く読み（`dst = src + moves[i]`）は残り、定数には畳み込まれない。** `moves` は `switch` で4本のどれかを
  指すポインタなので、gcc は表の中身を命令に埋め込まなかった。消えるのは「駒の種類を見て表を選ぶたびの GOT の読み1回」
- GOT の読みはほぼ確実に L1 キャッシュに当たる。ただし `moves[i]` の読みはその結果の番地を待つので、依存の鎖が1段短くなる
- 生成器のあとの関数は全部 **+16 バイト**ずれる（`nextBoardInvNormal` が 1102 → 1107 バイト。[`symbols.py`](symbols.py)。
  回したあとで `logs/symbols.txt`）。生成器より前の関数と、`call` の行き先（[`calls.py`](calls.py)）は変わらない。
  ほかの関数の命令の数も変わらない（[`insns.py`](insns.py)）

2腕とも `-march=native` でビルドするので、何に解決されたかを [`march.sh`](march.sh) で `logs/march.txt` に残す。

## 腕と配置

| 腕 | 中身 |
|---|---|
| `old` | `impl/28_march_native` |
| `new` | `impl/29_static_const_moves` |

差分の範囲は `tests/test_impl_29_static_const_moves.py` が固定している（`.py` と `Makefile` は #28 とバイト同一、`.h` の差は
`extern` 4行だけ、`.c` のコードの差は表4本の `static const` と `moves` の型だけ、`.so` の外の Python から表を読んでいる所が
無いこと。2腕をそれぞれの `Makefile` でビルドしたときに `GLOB_DAT` から4本が消え、生成器が `lea` で表の番地を作ること、
打ち切って回した成果物のバイト一致）。[`build_arm.sh`](build_arm.sh) は毎本 `.so` の sha256 の先頭を進行ログに出す
（回す前にビルドして読んだ値は `old` が `5128798ef4a5`（#28 本走と同じ）、`new` が `02852e36584f`）。

単位は完走（空の `dat/` から `python3 ./animal_shogi.py` を1本）。`old new new old` を3ブロック、計12本（各腕6本）。
どの本も `numactl --cpunodebind=0 --membind=0` でノード0に固定する（[`run_all.sh`](run_all.sh)）。
各本の前に、ノード0の 2 MiB 以上の空きブロックが 16 GiB 以上あるかを見る（[`run_one.sh`](run_one.sh)）。足りなければ自分で回避せず、
止めて人にキャッシュを落としてもらう。起動する前やキャッシュを落とす前後の値は [`free_snapshot.sh`](free_snapshot.sh) で `logs/` に残す。

## 判定に使う量

**主な判定の量は F1 のユーザー時間と P2 のユーザー時間**（[`f1p2_split.py`](f1p2_split.py)）。#28 と同じく、2つなので
「下がった」と言うのは **95% 区間の上端が 0 より下で、かつ p < 0.025**（Bonferroni 補正）のとき。
2つのうち少なくとも1つが下がったと言えれば記録に進む。

**同点の扱い**: どちらも下がったと言えなければ同点とみなし、記録にしない（本走しない）。門番の結果だけをコミットして報告し、
README のレバー表の `static const` の行には「12本の門番でも確定できなかった」と書いて候補から外す。

## 止める条件（[`stop_rule.py`](stop_rule.py)）

どれかに掛かったら、本走の前に止めて報告する。

1. どれかの本の `dat/` が #28 本走とバイト一致しない（md5 一覧の sha256 を `results/28_march_native/bytecompare.txt` の値と照合）、
   件数の列が `results/28_march_native/forward.tsv` と違う、またはオラクル174行で落ちた
2. F1 と P2 のユーザー時間の**どちらも**下がったと言えない（同点）
3. 動かないはずの段（F2・F5・F6・P0・P1・P4・`loop174`）のどれかが、区間が 0 をまたがず、かつ差の大きさが **0.2 秒以上**
   （向きは問わない）。移動表を読むのは生成器だけなので、ほかの段は動かないはず。掛かったら本走の前に原因を調べる
   （関数の配置が +16 バイト動く影響など）。段の数だけ比べるので多重比較は未補正（安全側の条件）
4. どれかの本で `thp_fault_fallback` の前後差が 0 でない、または巨大ページが表と配列の全部に付かない
   （両腕とも、`anonhuge_seen_kB` 4,194,304・`anonhuge_index_kB` 8,388,608・`anonhuge_loop_kB` 4,972,544 kB 以上）

ほかに、落ちた本が無いことも見る。1・4 は `run_one.sh` が毎本その場で見る。

## 予測（門番を回す前に書いた）

| | 予測（`new − old`） | 根拠 |
|---|---|---|
| **F1 のユーザー時間** | 下がる向き。**0〜−1 秒**。同点（区間が 0 をまたぐ）もありうる | 消えるのは駒ごとの GOT の読み1回（L1 に当たる）と命令3つ。依存の鎖が1段短くなるぶんは効きうるが、表を引く待ちに隠れやすい。lever_scan（#19 のコード）は −0.57 で 0 をまたいだ。#27・#28 とも古いコードで測った値の半分前後に目減りした |
| **P2 のユーザー時間** | 下がる向き。**0〜−0.7 秒**。同点もありうる | 生成器は P2 も通るが、局面の数は F1 の約 4 割。lever_scan は −0.39 で 0 をまたいだ |
| F1・P2 のカーネル時間 | 区間が 0 をまたぐ | 確保もページも変えない |
| 動かないはずの段（F2・F5・F6・P0・P1・P4・`loop174`） | 止める条件3に掛からない | 移動表を読むのは生成器だけ。#26〜#28 で関数の番地が動いても、生成器を通らない段は動かなかった |
| minor fault ／ 全体のピーク RSS | 変わらない | |
| 巨大ページ | 12本とも表と配列の全部に付く | |
| `dat/` | 12本とも #28 本走とバイト一致 | 表の値も並びも同じ |
| 完走タイム | 幅を出さない（参考の見込みは 0〜−1.5 秒） | |

## 集計

```bash
python3 experiments/gate_29_static_const_moves/stop_rule.py    # 止める条件
python3 experiments/gate_29_static_const_moves/f1p2_split.py   # 判定の量と、予測に登録した量
python3 experiments/gate_stats.py gate_29_static_const_moves forward
python3 experiments/gate_stats.py gate_29_static_const_moves spans
O=runs/exp_g29_r1a_old/animal_shogi.so N=runs/exp_g29_r1b_new/animal_shogi.so
python3 experiments/gate_29_static_const_moves/tables.py "$O" "$N"
python3 experiments/gate_29_static_const_moves/insns.py "$O" "$N"
python3 experiments/gate_29_static_const_moves/calls.py "$O" "$N"
python3 experiments/gate_29_static_const_moves/symbols.py "$O" "$N"
```

## ファイル

| | |
|---|---|
| [`build_arm.sh`](build_arm.sh) | 腕のソースを写し、その実装の `Makefile` でビルドし、`.so` の sha256 の先頭を出す |
| [`march.sh`](march.sh) | `-march=native` が何に解決されるか（2腕とも #28 から `-march=native`） |
| [`run_one.sh`](run_one.sh) | 走る前にノード0の空きを確かめ、完走を1本測って検査し、生ログを `logs/` に写す |
| [`run_all.sh`](run_all.sh) | `march.sh` を残してから12本を上の順で回す。進行は `logs/console.log`（回す前の負荷は load average と CPU 使用率の合計だけ） |
| [`free_snapshot.sh`](free_snapshot.sh) | 起動する前やキャッシュを落とす前後の空きメモリを `logs/free_<名前>.txt` に残す |
| [`stop_rule.py`](stop_rule.py) / [`f1p2_split.py`](f1p2_split.py) | 止める条件 / 判定の量と内訳 |
| [`tables.py`](tables.py) | 2腕の `.so` で移動表がどう読まれているか（再配置・シンボルの種類・生成器の命令） |
| [`insns.py`](insns.py) / [`calls.py`](calls.py) / [`symbols.py`](symbols.py) | 2腕の `.so` の命令 / `call` の行き先 / 関数の番地のずれ |
| [`lib.sh`](lib.sh) | 周波数の標本・vmstat・md5 一覧・空きブロックの読み（`gate_28_march_native` の写し） |
