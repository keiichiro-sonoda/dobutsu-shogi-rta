# 門番 #38: 全探索の生成器にキャッチの先行判定を入れた `impl/38_precheck` を、#37 と完走で比べる（記録試行の門番）

`old` ＝ `impl/37_mirror1`（記録 #37）、`new` ＝ `impl/38_precheck`。どちらもその実装の `Makefile` でビルドする（[`build_arm.sh`](build_arm.sh)）。
作りは [`gate_37_mirror1`](../gate_37_mirror1/) を写し、答えの検査を [`gate_36_bb_unmove`](../gate_36_bb_unmove/) の形（`dat/` のバイト比較）に戻した。

## 何を比べるか

`impl/38_precheck` は `impl/37_mirror1` に [`experiments/f1_select_catch/patches/precheck.patch`](../f1_select_catch/patches/precheck.patch) を当て、
前提を述べるコメントを3行足しただけの実装。変わるのは全探索の生成器 `nextBoardInvNormalNC` と、表を作る `dstTableBuild`（表 `g_reach` を足す）と、
足した `static inline` の `komaSet` だけで、`.py`・`Makefile`・`hot_layout.ld`・`nextBoardSeenNormal()`・`normalBoard()`・逆向きの生成器・`unmoveStep()`・ランクは
#37 とバイト同一（[`tests/test_impl_38_precheck.py`](../../tests/test_impl_38_precheck.py)）。

生成器は、反転の直後・利きの一覧より前に「手番側が相手のライオンを取れるか」だけを先に決め、取れれば後続を作らずに `return 0` する。判定は、`g_dst` を裏返した表
`g_reach[駒][L]`（その駒が相手のライオンのマス L へ動ける元のマスの集合）と、駒の種類ごとの手番側の駒のマスの集合の AND を5つ OR でまとめる形で、ループは無い。
**戻り値・後続の列（並びまで）・`*non_catch` は #37 と同じ**なので、全探索の待ち行列も、後退解析が局面を決める順も、`dat/` も #37 と同じになるはず。

## 回す前に確かめたこと

- **`impl/38_precheck` の `.so` は、`f1_select_catch` の腕 `precheck` の `.so` とバイト一致した**（sha256 `a712601ee2c9eab0…`）。前提を述べるコメント3行を足しても一致は崩れなかった。
  だから `f1_select_catch` の全局面の一致の検査（到達可能な全 246,803,167 局面で、戻り値・後続の列（並びまで）・`*non_catch` が #37 と同じ。
  [`logs/verify_precheck.txt`](../f1_select_catch/logs/verify_precheck.txt)）がそのまま当たる。止める条件 2 には掛からない
- **機械語**（`f1_select_catch` の [`check_asm.py`](../f1_select_catch/check_asm.py) を、`impl/38_precheck` に `-g` を足して組んだ `.so` に当てた。`.text` は `-g` なしと一致。
  [`logs/asm_impl38.txt`](logs/asm_impl38.txt)）: 生成器の命令 363、`tzcnt` 6、条件分岐 20。先行判定は命令 80・条件分岐 1（`if (hit) return 0;`）。`-Wall -Wextra` の警告 0。
  行番号がコメントの3行ずれる以外は、実験の `logs/asm_precheck.txt` と同じ
- `tests/test_impl_38_precheck.py`: 打ち切った全探索の出力と、そのあとの後退解析の `dat/` の全ファイルが #37 とバイト一致。展開した全局面で生成器の戻り値・後続の列・
  `*non_catch` が #37 と同じ（キャッチ局面・トライ負けの局面・取れるのにトライの段にもいる局面を、それぞれ1つ以上通す）。展開した全局面で、反転したあとの盤に相手のライオンが
  ちょうど1つ（先行判定の前提）。関数の記号は #37 と同じで、詰め物の検査も通る。`CLAUDE.md` の「次の実装で必ず直すもの」は空だった
- **熱い関数の置き場所のずれ**（`nm`。左が #37、右が #38）: 生成器 `nextBoardInvNormalNC` が 0x482 → 0x5b1 バイト（＋303）に伸び、後ろに並ぶ熱い関数はどれも
  **＋0x100（＋256 バイト、64 バイトの区切り4つ）**ずれる。前に並ぶ `invBoard` 0x2000・`nextBoardInvNormal` 0x20c0・生成器の先頭 0x2540 は動かない

  | 関数 | #37 | #38 |
  |---|---|---|
  | `nextBoardInvNormalNC` | 0x2540（0x482 バイト） | 0x2540（0x5b1 バイト） |
  | `nextBoardSeenNormal`・`expandRound`（全探索） | 0x2a00・0x2f00 | 0x2b00・0x3000 |
  | `unmoveCandidates`・`unmoveInit`・`unmoveStep`・`unmoveDraws`（後退解析） | 0x3200・0x4340・0x4440・0x4940 | 0x3300・0x4440・0x4540・0x4a40 |

- **`.bss` の並び**: 表 `g_reach`（16 × 12 × 8 ＝ 0x600 バイト）が `g_dst` のあった 0xa4e0 に入り、そのあとの `g_dst`・`g_att`・`g_prep` の口・ランクの表
  （`g_rank_half` など）・`g_seen` の口は、どれも **＋0x600（＋1,536 バイト）**ずれる。`.bss` の大きさは 0x3f438 → 0x3fa38。後退解析もランクの表を引くので、
  後退解析の段がこのずれで動くことはありうる（#35〜#37 は `.bss` の並びが同じだった）
- `check_answer.py` を #37 本走の `dat/` に当てて PASS、#36 本走の `dat/`（md5 一覧が違う）に当てて FAIL になることを確かめた

## 判定の量（回す前に決めた）

- **主: 完走の秒**（`/usr/bin/time -v` の Elapsed）の `new − old`。平均の差と Welch の 95% 区間（[`stop_rule.py`](stop_rule.py)。比較は1対1の1本）
- 並べて出す（判定には使わない。[`summary.py`](summary.py)）: 全探索の合計・F1・F1 のユーザー時間とカーネル時間・F5・F6、後退解析（完走 − `forward_total`）と段の合計（`retreat_total`）、
  `U_init`・`U_loop`（ユーザー時間とカーネル時間）・`U_draw`・`U_uk`、ユーザー時間・カーネル時間・minor fault・ピーク RSS

## 記録にするかの取り決め（回す前に決めた）

速さだけのレバーなので、#35〜#37 と同じ扱い。

- 完走の `new − old` の区間の上端が 0 より下 → **本走して記録にする**
- 区間が 0 をまたぐ → **本走せずに止めて報告する**（欠番にするかは本人が決める）
- 区間の下端が 0 より上（遅くなった）→ **本走せずに止めて報告する**

## 配置と条件

- 単位は完走（空の `dat/` から1本）。`old new new old` を3ブロック、計12本（**`old` 6本・`new` 6本**。[`run_all.sh`](run_all.sh)）
- どの本も `numactl --cpunodebind=0 --membind=0`。各本の前にノード0の 2 MiB 以上の空きを読んで `logs/<ラベル>_hugefree.txt` に残し、16 GiB に満たなければ走らせずに止める
- **門番の前に1本、`new` を完走させて答えの検査を通す**（[`run_trial.sh`](run_trial.sh)。`dat/` 全213ファイルを #37 本走の `dat/` と `diff -rq` でも比べる。
  計時には使わない。通らなければ `run_all.sh` は回さない）。**`new` の答えの検査は、この1本と門番の6本で計7本**
- 回す前に、CPU 使用率（全 CPU）が 3% 以下（ほかの計算が動いていない）ことを確かめ、load average と CPU 使用率だけを残す。`impl/37_mirror1`・`impl/38_precheck` に `__pycache__` が無いこと

## 答えの検査（毎本。[`run_one.sh`](run_one.sh)、[`check_answer.py`](check_answer.py)）

**バイト比較で見る。** 後続の列が全局面で #37 と同じなので、全探索の側も後退解析の側も `dat/` は #37 と同じになるはず。

- 両腕: `dat/` の md5 一覧の sha256 が **#37 本走と同じ（`a982b554596c…`。`results/37_mirror1/bytecompare.txt` の最後の行）**
- 両腕: オラクル174行。`forward.tsv` の件数の列が `results/37_mirror1/forward.tsv` と一致。`thp_fault_fallback` の前後差が 0、巨大ページが表と配列に付いている
  （しきい値は門番 #34〜#37 と同じ。配列は変わらない）
- `new` の門番の前の1本では、`dat/` 全213ファイルを #37 本走の `dat/`（`runs/` にある）と `diff -rq` でも比べる

## 止める条件（回す前に決めた）

1. 答えの検査が1本でも外れる（**`dat/` の md5 一覧の sha256 が #37 本走と違うことも含む**。後続の列が同じはずなのに一致しないなら、一致の検査が見落とした違いがある）
2. `impl/38_precheck` の `.so` が `precheck` の `.so` とバイト一致せず、かつ全局面の一致の検査を回し直して1局面でも外れる（上で一致を確かめたので、ここは掛からない）
3. 上の取り決めで「確定しない」「遅くなった」
4. どれかの本で `thp_fault_fallback` の前後差が 0 でない、または巨大ページが表と配列に付かない
5. 巨大ページに使える空きが下限に満たない（走らせずに止めて本人に知らせる。キャッシュは本人が落とす）

## 予測（回す前に書いた）

手がかりは `f1_select_catch` の生成器だけのベンチ（`precheck` − `base` は order で −103.4 cycles / 局面、範囲 −109.6〜−101.1。F1 の換算 −7.49 秒、
範囲 −7.94〜−7.32。catch・other で重みを付けた換算は −8.64 秒）と、生成器だけのベンチの換算が門番で出た割合（`gen_bench` → #26 で 75〜83%、#35 で 90%、#36 で 111%、
#37 は `mirror1_keep` の換算に対して `U_loop` で 101%）。

| | 予測（`new − old`） | 根拠 |
|---|---|---|
| **完走の秒** | **−5〜−9 秒。区間の上端は 0 より下** | order の換算 −7.49 秒 × 75〜111% ＝ −5.6〜−8.3 秒に、catch・other の換算（−8.64 秒）の側の振れと別の日の振れを足した |
| F1 | −5〜−9 秒。ほぼ全部ユーザー時間から（F1 のカーネル時間は ±0.1 秒） | 変わるのは生成器だけ。キャッチ局面は後続を作らないので、後ろの仕事（`g_prep` への書き込み）は #37 でも #38 でも同じ |
| 全探索の合計 | F1 の差 ± 0.3 秒 | F5・F6 はコードが同じ（`nextBoardSeenNormal`・`expandRound` が ＋256 バイトずれる） |
| F5・F6 | ±0.3 秒 | 同上 |
| 後退解析（完走 − 全探索）・`U_init`・`U_loop`・`U_draw`・`U_uk` | どれも ±0.5 秒 | コードは同じ。後ろに並ぶ熱い関数が ＋256 バイト、`.bss` のランクの表などが ＋1,536 バイトずれる。#35（−320 バイト）・#37（−128 バイト）の関数のずれでは ±0.02 秒しか動かなかったが、`.bss` のずれは今回が初めてなので幅を広く取った |
| ユーザー時間の合計 | 完走の差とほぼ同じ | 上の和 |
| カーネル時間の合計 | ±0.3 秒 | 配列もページの付き方も同じ |
| minor fault・ピーク RSS | ±0.5% | 足した表は 1,536 バイトだけ |
| `dat/` | 両腕の13本（`old` 6・`new` 7）とも md5 一覧の sha256 が #37 本走と同じ。門番の前の1本は `diff -rq` で差 0 | 後続の列が全局面で同じ |

**`f1_select_catch` の「言えないこと」を引き継ぐ**:
- 外れる局面（other）で `precheck` がベンチでは −18.4 cycles と軽くなった理由は確かめていない。本物の F1 で同じ向きになるかは分からない
- ベンチは命令が同じでも 20 cycles ほど動くことがあった（`both` のキャッチ局面）
- ベンチは発見済みの表・準備の配列・Python 側を含まない

## 機械時間の見込み

門番の前の1本 約3分、12本 約30分。
