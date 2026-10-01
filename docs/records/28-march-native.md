---
record: 28
impl: impl/28_march_native/
date: 2026-10-01
time: "0:02:27"
speedup: 217.45
---

# 記録 #28 で分かったこと

**`Makefile` の `gcc` 行に `-march=native` を1つ足した**（`-O2 -fno-semantic-interposition` は残した）。変数はこれ1つで、
`animal_shogi.c`・`.h`・`.py` は #27 とバイト同一。

**完走 0:02:31 → 0:02:27（211.95× → 217.45×）。−3.84 秒（−2.5%）。**
内訳は全探索 69.05 → 67.57 秒（−1.48）、後退解析 82.55 → 80.19 秒（−2.36）。
`dat/` は #27 と全213ファイルでバイト一致した（#27 本走の `dat/` と直接 `diff -rq`）。

## `native` が何に解決されたか

⚠️ **`-march=native` の中身は CPU で決まる。別の CPU では別のバイナリになる。** 計測機（gcc 13.3.0）では
`gcc -march=native -Q --help=target` が次のように解決された（[`march.txt`](../../results/28_march_native/march.txt)。門番の
[`logs/march.txt`](../../experiments/gate_28_march_native/logs/march.txt) と同じ）。

| | |
|---|---|
| `-march=` / `-mtune=` | **`broadwell` / `broadwell`** |
| 増える命令セット（事前定義マクロ） | AVX・AVX2・FMA・F16C・BMI・BMI2・LZCNT（ABM）・POPCNT・MOVBE・SSE3〜SSE4.2・ADX・AES・PCLMUL・RDRND・RDSEED・RTM など |

`env.txt` には入れず、`results/` の `march.txt` と門番のログに残した（`env.txt` の欄は `tools/run.sh` が全記録で同じものを書くので、
`-march=native` を使う記録だけの欄を足すより、この記録の証拠として置くほうが筋がよいと判断した）。

## 命令がどう変わったか

門番の本が作った `.so` を `objdump -d` で数えた（[`insns.txt`](../../experiments/gate_28_march_native/logs/insns.txt)。
数え方は [`insns.py`](../../experiments/gate_28_march_native/insns.py)）。x86-64 のベースラインに無い命令は **0 → 69 か所**。

| 関数 | 入った命令 | 命令の総数 #27 → #28 |
|---|---|---|
| `nextBoardInvNormal`（生成器。F1・P2） | **`shlx` 18・`shrx` 6** | **322 → 285** |
| `expandRound`（F1） | AVX の移動 13（`vzeroupper` 5・`vmovdqu` 2 など） | 153 → 168 |
| `buildSuccRange`（P2） | AVX の移動 14（`vzeroupper` 3・`vmovdqu` 2 など） | 190 → 177 |
| `nextBoardIndexNormal`（P2） | `shrx` 2・`vmovd` など 5 | 96 → 99 |
| `indexBuild`（P1）・`seenInsert` | `shlx` 2・`shrx` 2 ずつ（ハッシュのシフト） | 148 → 144 / 変わらず |
| `nextBoardSeenNormal`・`seenContains` | `shrx` 1 ずつ | 変わらず / 29 → 28 |
| `predScatter`（P4）・`retreatStep`（174段ループ） | 無し | 82 → 84 / 192 → 194 |

- 入ったのはほぼ **BMI2 の可変シフト**（`shlx`/`shrx`。シフト量を `cl` に置かなくてよく、Broadwell では `shl r, cl` の 3 µop が 1 µop
  になる）と、**AVX の移動**（16〜32 バイトの塊のコピー）。盤面は 4 ビットずつ詰めた整数なので、生成器はマス番号でずらす可変シフトの塊になっている
- **BMI の `andn`・`blsr`・`tzcnt` や、`popcnt`・`movbe` は1つも入らなかった。** `invBoard()` の `bswap` も `movbe` にならず、大きさも 137 バイトのまま
- `buildSuccRange()` には **`memcpy@plt` への呼び出しが1つ増えた**（[`calls.txt`](../../experiments/gate_28_march_native/logs/calls.txt)）。
  後続を中継バッファへ写すループを gcc が `memcpy` に替えたもの
- 関数の番地は −80〜+32 バイト動いた（[`symbols.txt`](../../experiments/gate_28_march_native/logs/symbols.txt)）

`tests/test_impl_28_march_native.py` が、`Makefile` の差がこのフラグ1つだけであることと、2腕をそれぞれの `Makefile` でビルドしたとき
BMI2 を持つ CPU なら生成器に `shlx`/`shrx` が入ること（持たない CPU では飛ばす）と、その `.so` で打ち切って回した成果物が #27 と
バイト一致することを固定している。

## 門番 — フラグだけを違えた2腕

[`gate_28_march_native`](../../experiments/gate_28_march_native/)。`old` = `impl/27`、`new` = `impl/28`。どちらもその実装の
`Makefile` でビルドした。完走を `old new new old` × 3 ＝ 12本、`numactl` で片ノードに固定。

**主な判定の量は F1 と P2 のユーザー時間の2つ**で、「下がった」と言うのは区間の上端が 0 より下で、かつ **p < 0.025**
（2つの量で Bonferroni 補正）のとき。どちらも下がったと言えなければ同点として記録にしない、と回す前に決めた。
ほかの段は、区間が 0 をまたがずに 0.3 秒以上遅くなったら止める（段の数だけ比べるので多重比較は未補正。安全側の条件）。

| 量 | `old` 6本 | `new` 6本 | `new − old`（95% 区間） | p |
|---|---|---|---|---|
| **F1 のユーザー時間** | 60.73（sd 0.13） | 59.53（sd 0.22） | **-1.20（-1.44 … -0.97）** | 2.2 × 10⁻⁶ |
| **P2 のユーザー時間** | 39.24（sd 0.13） | 37.60（sd 0.26） | **-1.64（-1.92 … -1.36）** | 1.3 × 10⁻⁶ |
| F1 | 63.66（sd 0.15） | 62.47（sd 0.22） | -1.20（-1.44 … -0.95） | < 0.0001 |
| P2 | 41.24（sd 0.11） | 39.61（sd 0.29） | -1.62（-1.93 … -1.32） | < 0.0001 |
| P1 | 7.29（sd 0.05） | 7.18（sd 0.04） | -0.11（-0.17 … -0.05） | 0.0016 |
| P4 | 15.75（sd 0.07） | 15.82（sd 0.11） | +0.07（-0.06 … +0.19） | 0.2559 |
| loop174 | 14.58（sd 0.08） | 14.55（sd 0.12） | -0.03（-0.17 … +0.10） | 0.5886 |
| 後退解析 合計 | 80.95（sd 0.24） | 79.25（sd 0.55） | -1.69（-2.27 … -1.11） | 0.0002 |
| 完走（参考） | 149.64（sd 0.41） | 146.75（sd 0.78） | -2.89（-3.72 … -2.05） | < 0.0001 |

表は [`f1p2_split.py`](../../experiments/gate_28_march_native/f1p2_split.py) の出力の抜き出し。
**止める条件には掛からなかった**（[`stop_rule.py`](../../experiments/gate_28_march_native/stop_rule.py)）。
主な量は2つとも下がったと言え、区間が 0 をまたがずに遅くなった段は無かった。12本とも、オラクル174行 PASS、
`dat/` は #27 本走とバイト一致、件数の列は全74ラウンド一致、`thp_fault_fallback` は 0、巨大ページは表と配列の全部に付いた。
F1・P2 のカーネル時間、minor fault、ピーク RSS は動かなかった。

**P2 のほうが F1 より大きく下がった。** lever_scan（#18 のコード）でも P2 −3.56・F1 −2.40 と同じ形で、大きさはどちらもその
ほぼ半分。`buildSuccRange()` に増えた `memcpy@plt` の呼び出しは、差し引きで P2 を遅くするほどではなかった（その呼び出しだけの
費用は分けていない）。F1・P2 のほかに動いたのは **P1 の −0.11 秒**だけで、`indexBuild()` のハッシュのシフトが `shlx`/`shrx` に
なったぶんと読める（分けていない）。P4・174段ループは命令の並べ方が変わったが、区間が 0 をまたいだ。

`-mtune` も一緒に変わっているので、この差のうち命令セット（BMI2・AVX）のぶんと命令の並べ方のぶんは分けていない
（`-mtune=native` だけの腕は、2腕で本数を確保するために作らなかった）。

## 予測と実測

予測は門番を回す前にコミットした（[門番の README](../../experiments/gate_28_march_native/) の履歴で確かめられる）。

| | 予測（`new − old`） | 門番の実測 | |
|---|---|---|---|
| **F1 のユーザー時間** | 下がる。−0.5〜−3 秒 | −1.20（−1.44 … −0.97） | ✅ |
| **P2 のユーザー時間** | 下がる。−0.5〜−3 秒 | −1.64（−1.92 … −1.36） | ✅ |
| 後退解析の合計 | 下がる。−0.5〜−4 秒 | −1.69（−2.27 … −1.11） | ✅ |
| P1 | 向きを決め打ちしない。大きさは 0.5 秒未満 | −0.11（−0.17 … −0.05） | ✅ |
| P4・174段ループ | 向きを決め打ちしない | +0.07 / −0.03（どちらも 0 をまたぐ） | — |
| F2・F5・F6・P0 | 動かない | 差は 0.01 秒以下 | ✅ |
| カーネル時間・minor fault・ピーク RSS | 変わらない | 0 をまたぐ / 差なし / +25 kB | ✅ |
| `dat/` | 12本と本走が #27 とバイト一致 | 一致 | ✅ |
| 完走タイム | 幅を出さない（参考の見込みは −1〜−6 秒） | 門番 −2.89、本走 −3.84 | — |

外れた予測は無かった。

## 走る前の空きメモリ

門番の前はノード0が 12.53 GiB で 16 GiB に届かず
（[`free_before_launch.txt`](../../experiments/gate_28_march_native/logs/free_before_launch.txt)）、人が root でキャッシュを落として
21.15 GiB にしてから起動した（[`free_after_drop.txt`](../../experiments/gate_28_march_native/logs/free_after_drop.txt)）。
12本の走る前は 21.15〜21.47 GiB。本走はノード0 21.13 / ノード1 25.64 / 合計 46.77 GiB で通った
（[`hugefree.txt`](../../results/28_march_native/hugefree.txt)。本走の前には落としていないので `cache_drop:` は「なし」）。
本走の `thp_fault_fallback` と `compact_stall` は 0、巨大ページは発見済み表 4,194,304・索引 8,486,912・後退解析の配列 4,972,544 kB。

## 本走

| 段 | #27 本走 | #28 本走 | 差 |
|---|---|---|---|
| **F1 展開** | **64.21** | **62.70** | **−1.51** |
| F0 ＋ F2 ＋ F5 / F6 | 2.02 / 1.84 | 2.04 / 1.84 | +0.02 / −0.01 |
| P0 / P1 | 1.39 / 7.48 | 1.39 / 7.24 | −0.01 / −0.23 |
| **P2 後続生成** | **41.93** | **40.03** | **−1.90** |
| P4 前任リスト | 16.07 | 15.99 | −0.08 |
| `R_dtm` | 0.36 | 0.36 | +0.00 |
| 174段ループ | 14.81 | 14.64 | −0.17 |
| `retreat_total` | 82.39 | 80.01 | −2.38 |

秒は `forward_summary.tsv` と `retreat_summary.tsv` の生値。⚠️ **本走は各1本なので、段の差を効果として読まない。**
判定は門番で行った。本走の 174段ループ −0.17 は門番では区間が 0 をまたいだ段。本走は `numactl` で固定しないので、
索引のページの振れを引きうる。門番と本走の値を直接引き算しない（CLAUDE.md）。

本走の F1 のユーザー時間は 61.25 → 59.72（−1.53）、P2 のユーザー時間（境界 P1 → P2）は 39.92 → 38.03（−1.89）。

`time.txt` との突き合わせ: ユーザー時間 132.868 / 132.87 秒（差 0.002）、カーネル時間 14.724 / 14.86 秒（差 0.14）、
minor fault 3,723,965 / 3,723,970（差 5）。

## 検証

| | |
|---|---|
| オラクル | 手数別174行に完全一致（[`verify.txt`](../../results/28_march_native/verify.txt)）。`main.log` の総数から出る `totals.tsv` の8項目も一致 |
| 指紋 | `oracle/fingerprint.tsv` の176項目に一致（[`fingerprint.txt`](../../results/28_march_native/fingerprint.txt)） |
| サイズ検算 | 213 ファイル / 1,974,425,336 バイト ÷ 8 ＝ 246,803,167（端数 0） |
| **バイト比較** | **#27 と全213ファイルが一致**（[`bytecompare.txt`](../../results/28_march_native/bytecompare.txt)。#27 本走の `dat/` と直接 `diff -rq`） |

## 次

段の大きい順に **F1 展開 62.7 s（42.4%）、P2 後続生成 40.0 s（27.1%）、P4 前任リスト 16.0 s（10.8%）、
174段ループ 14.6 s（9.9%）、P1 7.2 s、F0 ＋ F2 ＋ F5 2.0 s、F6 1.8 s、P0 1.4 s**。

- **移動表の `static const`**: #28 のビルドでも、生成器は移動表4本（`GIRAFFE_MOVE` など）を GOT からポインタを読んでから引いている
  （`objdump` で4か所、`readelf -r` にも4本残る）。`-fno-semantic-interposition` も `-march=native` も、この読み方は変えなかった
- **gen_bench の候補 A（キャッチの先行判定）**: B の上に足した換算は −6.85 秒（F1 だけ。生成器だけの値）。判定が外れる局面の費用を
  下げる設計からやり直す必要があり、その設計は #26〜#28 で変わった生成器の上で gen_bench を回し直して確かめることになる
- F1 のカーネル時間 3.0 秒（#25 のノート）は変わっていない
