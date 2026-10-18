# f1_select_catch: F1 の生成器に残った分岐を消す試作と、キャッチの先行判定の試作を 2×2 の腕で比べる（記録試行ではない）

番号を取らず、`impl/` を作らず、`results/` にも README の記録表にも載せない。完走の門番・本走はしない（推すところまで）。

## 目的

#37 で段の大きい順は F1 48.0 秒（53.4%）、`U_loop` 32.4 秒（36.0%）になった。F1 の生成器 `nextBoardInvNormalNC()` について、
[`docs/levers.md`](../../docs/levers.md) に残っている2つのレバーを1つの実験で測る。

1. **残った分岐を消す（`select`）**: [`bitboard_gen`](../bitboard_gen/) の帰属で、#35 の生成器（#37 も同じ）に残った予測ミス 4.38 / 局面のうち、
   持ち駒の更新の三項演算 0.58・キャッチ抜きの数を選ぶ三項演算 0.42・左右の正規化 `normalBoard()` 0.82（合わせて約 1.8）を、両方を計算して選ぶ形にする
2. **キャッチの先行判定（`precheck`）**: 生成器の頭で「手番側が相手のライオンを取れるか」だけを先に決め、取れれば後続を作らずに `return 0`。
   [`gen_bench`](../gen_bench/) の候補 A は、判定が外れる局面で 33〜45 ns 増えたので、外れたときの費用を下げた書き方で測り直す

2つは同じ関数を触り、効果が重なる（キャッチ局面は全体の 57%。先行判定が当たると生成器の本体が走らないので、`select` の得もそこでは消える）。
だから2×2の4腕で、組み合わせまで測る。記録にするときは1つの記録試行に1つのレバー。この実験は、どちらを先にするかと2つ目の取り分を推す材料。

## 腕

どの腕も `impl/37_mirror1` の写しにパッチを当てて作る（[`build_arm.sh`](build_arm.sh)）。`impl/37_mirror1` そのものは触らない。
`.py`・`Makefile`・`hot_layout.ld`・`animal_shogi.h` は `impl/37_mirror1` のまま（`build_arm.sh` が `cmp` で確かめる）。

| 腕 | 中身 | パッチ |
|---|---|---|
| `base` | `impl/37_mirror1` のまま（`.so` は #37 本走と同じバイト列、sha256 の先頭 `1730c3fdcb0b`） | — |
| `select` | 下の3か所を、両方を計算して選ぶ形にする | [`patches/select.patch`](patches/select.patch) |
| `precheck` | 生成器の頭にキャッチの先行判定を入れる | [`patches/precheck.patch`](patches/precheck.patch) |
| `both` | `select.patch` と `precheck.patch` をこの順にそのまま重ねる（重ねるために書き方を変えていない） | 2つ |

### `select` の作り（3か所。ほかの分岐は変えない）

- **持ち駒の更新**: `nb ^= ((b >> own_p) & 0b11 ? 0b11 << own_p : 0b01 << own_p) & マスク` を、
  `nb ^= ((u_long)(1 + 2 * (((b >> own_p) & 0b11) != 0)) << own_p) & マスク` にした（持ち駒が既にあるかの 0 / 1 を値にして 0b01 / 0b11 を作る）
- **キャッチ抜きの数を選ぶ**: `c = koma == LION2 ? (ライオンの数え方) : (ほかの駒の数え方)` を、外側のループで
  `isL = -(unsigned)(koma == LION2)` を作り、`c = (ライオンの数え方 & isL) | (ほかの駒の数え方 & ~isL)` にした
- **左右の正規化**: 🔴 `normalBoard()` そのものは書き換えない（逆向きの生成器も呼んでいる）。生成器の中だけで使う `static inline` の
  `normalBoardSel()` を `normalBoard()` の直後に足した。入れ替えた盤 `sw` を先に作り、`m = -(u_long)(col_A > col_C)` で
  `b ^ ((b ^ sw) & m)` を返す。生成器の2か所（動かす手と打つ手）の `normalBoard(…)` を `normalBoardSel(…)` にした

### `precheck` の作り（判定の書き方とその理由。1つに決めて作った）

置き場所は `invBoard` の直後、利きの一覧（`att1` / `atkL` の 12 マスのループ）より前。当たったら `*non_catch = 0` のまま `return 0`（今と同じ戻り値）。
先行判定のあとの本体は `base` のまま（本体の `if (dst_koma == LION1) return 0;` も残した）。

- 判定: 相手のライオンのマス L を `komaSet(b, LION1)` の `ctz` で出す。駒の種類（`CHICK2`〜`CHICKEN2` の5つ）ごとに、表
  `g_reach[駒][L]`（その駒が L へ動ける元のマスの集合）と、`komaSet(b, 駒)`（手番側のその種類の駒がいるマスの集合）の AND を取り、5つを OR でまとめる。
  0 でなければ `return 0`
- `komaSet(b, k)` は、盤を `k` と XOR して 0 になるマスの集合（今の `try_flag` の作りと同じ）。足した `static inline` の下請け
- **選んだ理由**: 狙いは外れたときの費用を下げること。この書き方は、駒の種類が5つで固定なので、ループも、局面ごとに回数が変わる取り出しも無く、
  条件分岐は `if (hit) return 0;` の1つだけになる（下の機械語）。`gen_bench` の候補 A は、ライオンのマスをループで探し、8方向を分岐で見ていた
- **答えが変わらない理由**: `g_reach` は `g_dst` を裏返して作る（s から L へ動ける ⟺ L ∈ `g_dst[駒][s]`）。本体が `return 0` するのは
  「手番側の駒のどれかの行き先の集合 `g_dst[駒][src] & ~own` に L がある」ときで、L は相手の駒なので `~own` で消えない。だから先行判定が当たる局面と、
  本体が `return 0` する局面は同じになる
- 🔴 `g_att` は使わない（生成器だけのベンチは `prepInit()` を呼ばず、`g_att` が空のまま回るため）。`g_reach` は `.bss` に置き、
  `dstTableBuild()` の最後で `g_dst` から作る。`dstTableBuild()` と同じく `.so` を読み込んだときに1回走る。
  表を作る関数を新しく足すとその関数の記号が増える（止める条件 2 が見る）ので、`dstTableBuild()` に4行足す形にした
- 書かなかった書き方: 手番側の駒を種類ごとにずらして利きの集合を作る形（移動の向きの数だけずらしと端のマスクが要る）

## 回す前に数えたこと（静的。本物の局面での計時はしていない）

登録の時点で `logs/` にあるのは、この節のファイルだけ（[`logs/asm_*.txt`](logs/)・[`logs/build_static.txt`](logs/build_static.txt)）。

- **組み立て**: 4腕とも `-Wall -Wextra` の警告 0。`base` は #37 本走の `.so` とバイト一致。`-g` の `.so` の `.text.hot_layout` と `.text` は、中身も番地も `-g` なしと同じ
- **関数の記号**（止める条件 2）: 4腕とも、関数の記号（`nm` の `t` / `T`）が `impl/37_mirror1` の `.so` と同じ 54 個。`normalBoardSel()` と `komaSet()` はインライン展開された
- **`.so` の sha256 の先頭**: `select` `59575c200907`、`precheck` `a712601ee2c9`、`both` `3bddaaf99a6e`
- **生成器の大きさ**: `base` 0x482、`select` 0x4dd、`precheck` 0x5b1、`both` 0x620 バイト。後ろに並ぶ `nextBoardSeenNormal` などの関数は、
  `select` で ＋0x40、`precheck` で ＋0x100、`both` で ＋0x180 ずれる（ベンチは別の `.so` なので、この実験の値には入らない。門番では効きうる）
- **機械語**（[`check_asm.py`](check_asm.py)）:

  | 腕 | 命令 | `cmov` | 条件分岐 | 狙った3か所の条件分岐（持ち駒 / キャッチ抜き / 左右） | 先行判定 |
  |---|---|---|---|---|---|
  | `base` | 297 | 4 | 19 | 1 / 1 / 2 | — |
  | `select` | 320 | 7 | 15 | **0 / 0 / 0** | — |
  | `precheck` | 363 | 4 | 20 | 1 / 1 / 2 | 命令 80、条件分岐 1 |
  | `both` | 392 | 7 | 16 | **0 / 0 / 0** | 命令 80、条件分岐 1 |

  `select` の3か所は、1回目の書き方で条件ジャンプが無くなった（持ち駒は `cmov` 1、キャッチ抜きは `cmov` 1 と `set` 1、`normalBoardSel` は `cmov` 2）。
  3か所以外の三項演算（取った駒の持ち駒の位置 `own_p = dst_koma == CHICKEN1 ? …`・打ったあとの持ち駒の数 `own_num == 2 ? …`）は、
  `base` でもすでに `cmov` で、ジャンプではなかった
- **作りの確かめ**: パッチを書いた段階で、`verify.c` を #37 本走の `dat/` の3ファイル（`win001te_000`・`lose000te_000`・`unknown000`、約 1,268 万局面）
  にだけ通し、3腕とも不一致 0 だった（`bitboard_gen` と同じ3ファイル。ログは残していない。計時はしていない。下の見込みには使っていない）

## 束ね方（回す前に決めた。回したあとで組み替えない）

[`categories_<腕>.tsv`](.)（[`make_categories.py`](make_categories.py) が腕のソースの行の文から作った）。束の名前は `perf_branch_34`・`bitboard_gen` と同じで、
「キャッチの先行判定」（先行判定の区画と `komaSet` の本体）と「表づくり」（`dstTableBuild`・`rankTablesBuild`）を足した。
`select` の新しい行は、持ち駒の更新が「持ち駒の数」、`isL` とキャッチ抜きの数が「駒の種類と空き」、`normalBoardSel` の本体が「左右の正規化」。
`base` の生成器の行の束は、`bitboard_gen` の `categories_bb_nibble.tsv` と行番号まで同じ。ベンチの外枠（`benchFwd`）は別に数える。

## 測るもの（回す前に決めた）

[`run_all.sh`](run_all.sh) が順に回す（進行は `logs/console.log`。開始の行は `date --iso-8601=seconds`）。完走は回さない。

1. **一致の検査**（[`run_verify.sh`](run_verify.sh)、[`verify.c`](verify.c) は `bitboard_gen` の写し）: #37 本走の `dat/`（md5 一覧の sha256 が
   `a982b554596c…` であることを先に確かめる。全 213 ファイル、246,803,167 局面）を q にして、`base` と各腕で (a) 戻り値、(b) 正のときの後続の列（並びまで）、
   (c) `*non_catch`（`return 0` と `-1` のときに 0 のままであることも）を比べる。両方とも `prepInit()` を呼ぶ。外れた局面は最初の 20 個まで `logs/verify_<腕>.txt`。
   局面の内訳（キャッチ / トライ負け / 未知）も数え直す
2. **ベンチ**（[`run_bench.sh`](run_bench.sh)・[`build_bench.sh`](build_bench.sh)。`bitboard_gen` の写し）: `perf_34` の `glue.c`・`bench.c`（`benchFwd`）に腕の
   `animal_shogi.c` を取り込み、`impl/37_mirror1` の `Makefile` の gcc 行で `bench.so` を作る。入力は `bitboard_gen` と同じもの（order・random・catch・other）を
   そのまま使う（#37 の全探索は #34 と同じ局面を同じ順に展開し、到達可能な局面の集合も同じ）。
   `perf stat -e cycles:u,instructions:u,br_inst_retired.all_branches:u,br_misp_retired.all_branches:u`、`numactl --cpunodebind=0 --membind=0`
3. **束ごとの帰属**（[`run_attr.sh`](run_attr.sh)）: 4腕で order の 74 ブロックを1プロセスで回し、`perf record -e br_misp_retired.all_branches_pebs:upp -c 211`、
   `perf_branch_34` の `aggregate.py pebs` で行に寄せ、上の束ね方で束ねる。3回。間引きの回数を `logs/attr_stats.txt` に残す
4. [`summary.py`](summary.py) が `logs/summary.txt` を作る（手で書かない）。腕どうしの差は**同じ周の `base` との差を周ごとに取ってから**、7周の中央値と範囲

### 数（数えて書いた）

| | 数 |
|---|---|
| 腕 × 周 | 4 × 7 ＝ 28（腕ごとに 7 回） |
| 1周・1腕のプロセス | order 74 ＋ catch 72 ＋ other 73 ＋ random 1 ＝ 220（catch は `f1_000`・`f1_001` が空、other は `f1_073` が空で、空のファイルは回さない） |
| ベンチのプロセス | 220 × 28 ＝ 6,160 ＋ 固定の分 5 × 4 腕 ＝ 6,180 |
| 周ごとの腕の順 | 周 r は (`base`, `select`, `precheck`, `both`) を r − 1 だけ回したもの。周 5〜7 は周 1〜3 と同じ順。どの腕も 1〜4 番目に 2・2・2・1 回（1回だけの番目は `base` 2番目、`select` 3番目、`precheck` 4番目、`both` 1番目） |
| 一致の検査 | 3 腕 × 246,803,167 局面 |
| 帰属 | 4 腕 × 3 回 ＝ 12 プロセス |

### 出す差

- `select` − `base`、`precheck` − `base`、`both` − `base`（4入力ごと）
- **重なり** ＝ (`both` − `base`) − (`select` − `base`) − (`precheck` − `base`)（周ごとに取ってから。足し算なら 0、重なれば正）
- `precheck` は catch（浮いた分）と other（判定に払った分）を分けて出し、other の差を ns（cycles ÷ 3.408 GHz）にして `gen_bench` の 33〜45 ns と比べる
- F1 の秒への換算（見込みで、効果量ではない）: 主は order の cycles の差 × 246,803,167 ÷ 3.408 GHz（`bitboard_gen` と同じ式）。
  `precheck` と `both` は「catch の差 × 140,298,614 ＋ other の差 × 106,504,553」÷ 3.408 GHz も並べる。食い違ったら両方を書いて理由を考える

## 推し方（回す前に決めた）

- 腕ごとの判定の量は **order 入力の1局面あたり `cycles`** の `base` との差
- 範囲（7周）が 0 をまたがずに下 → その腕のレバーを、完走の門番にかける候補として推す。0 をまたぐ・上 → 推さない
- 両方とも推せるとき: order の換算が大きいほうを先に記録にする候補とし、もう1つは「先のレバーの上に足したときの取り分」＝ `both` − 先の腕 で見積もる
- 推すところまで。どちらを記録にするか・順番は本人が決める

## 条件と止める条件（回す前に決めた）

- 回す前に `kernel.perf_event_paranoid` が 1、`impl/37_mirror1` に `__pycache__` が無い、CPU 使用率（全 CPU）が 3% 以下を確かめる（`run_all.sh`）。
  合わなければ回さずに本人に知らせる。負荷は load average と CPU 使用率だけを残す。`runs/` の中身はコミットしない

1. どれかの腕で、一致の検査が1局面でも外れる（その腕は計時しない。`select` か `precheck` が外れたら `both` も計時しない。`run_all.sh` が見る）
2. 腕の `.so` に、インライン展開されなかった新しい関数の記号がある（`build_arm.sh` が組むたびに見る）
3. `select` で、3か所のどれかの条件ジャンプが、書き方を変えても消えない（`check_asm.py` が組むたびに見る。直し方を自分で決めずに報告する）
4. `precheck` の判定を、`g_att` を使わずに書けない
5. `kernel.perf_event_paranoid` が 1 でない

## 見込み（回す前に書いた）

`bitboard_gen`（`bb_nibble` は #37 の F1 の生成器と同じ形）・`gen_bench`・#35〜#37 の結果と、上の「回す前に数えたこと」だけから書いた。

| | 見込み | 根拠 |
|---|---|---|
| `base` | order 493 cycles・予測ミス 4.38、catch 222・2.94、other 817・5.53（cycles は ±3%、予測ミスは ±0.15） | `bitboard_gen` の `bb_nibble` と同じ生成器 |
| `select` − `base`（order） | cycles −30〜＋5、予測ミス −1.3〜−1.9、命令 ＋40〜＋100、分岐 −10〜−16 | 予測ミス 1.8 の大半が消える。1回 16 サイクルほど（`bitboard_gen` の `bb_nibble` − `base` の cycles と命令と予測ミスの差から）で −25〜−30。`normalBoardSel` は呼ぶたびに入れ替えた盤を作る（本体に寄った命令は2か所で 44）ので、1局面に約 5.5 回の正規化で命令が増え、その分を戻す。0 をまたぐことはありうる |
| `select` − `base`（catch / other） | catch: cycles −15〜＋5、予測ミス −0.4〜−1.2。other: cycles −50〜＋10、予測ミス −2.0〜−3.2 | キャッチ局面は途中で返るので、狙った3か所を通る回数が少ない |
| `precheck` − `base`（catch） | cycles −140〜−180、予測ミス −2.3〜−2.9、命令 −380〜−420 | キャッチ局面では、反転・先行判定（命令 80）・ベンチの外枠だけになる |
| `precheck` − `base`（other） | cycles ＋10〜＋35（**＋3〜＋10 ns**）、予測ミス −0.1〜＋0.1、命令 ＋70〜＋82 | 外れた局面は先行判定の 80 命令を払う。ループも分岐も無いので、`gen_bench` の 33〜45 ns より小さい。other だけの入力では分岐は毎回取られない側で、外れない |
| `precheck` − `base`（order） | cycles −60〜−105、予測ミス −1.0〜−1.8 | catch と other の 57 : 43。先行判定の分岐は、並びが混ざると外れるが、`base` のキャッチの `return 0` も同じように外れていた |
| `precheck` − `base`（random） | cycles −50〜−130 | 向きは order と同じ |
| 重なり（order / catch / other） | order −3〜＋10、catch −5〜＋15、other −8〜＋8（cycles） | `both` ではキャッチ局面で `select` の得が消える。other は足し算に近い |
| `both` − `base`（order） | cycles −65〜−135 | 上の和から重なりを引く |
| F1 の秒への換算（order） | `select` −2.2〜＋0.4、`precheck` −4.3〜−7.6、`both` −4.7〜−9.8 秒 | cycles の差 × 246,803,167 ÷ 3.408 GHz |
| 換算（catch・other） | `precheck` −4.7〜−7.1 秒。order の換算との食い違いは 1.0 秒以内（向きは決めない） | order の中のキャッチ局面の割合は全体とほぼ同じなので、違いは並びが混ざる効き |
| 推し方 | `precheck` は推せる。`select` はまたぐかもしれない。両方推せたら `precheck` が先、`select` の取り分（`both` − `precheck`）は order で −35〜＋8 cycles | 上の幅 |
| 帰属（`select`） | 左右の正規化 0.82 → 0、駒の種類と空き 0.42 → 0、持ち駒の数 0.58 → 0.25 以下（`if (!own_num) continue;` が残る）。ループの回数・キャッチは ±0.2 | 3か所の条件分岐が機械語から無くなった |
| 帰属（`precheck`） | キャッチの束 0.55 → 0.1 以下。キャッチの先行判定の束 0.3〜0.6。ほかの束はキャッチ局面の分（全体の 3〜4 割）だけ減る | 本体の `return 0` は、先行判定が外れた局面では取られない側にしか行かない |

## 機械時間の見込み

一致の検査 3 腕で 5〜10 分、ベンチ 8〜12 分、帰属 2 分。
