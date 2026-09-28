---
name: measure
description: どうぶつしょうぎ完全解析 RTA のアテンプトを1本走らせて記録する。起動・生存確認・完了待ち・オラクル検証・results/ への証拠保存・README 記録表の更新・コミットまでの一連。「計測して」「ベースラインを測って」「アテンプトを走らせて」「タイムを取って」「本走」といった依頼で使う。
---

# アテンプトを1本走らせて記録する

数時間かかりうる（ベースラインは約9時間、#25 は約3分）。**フォアグラウンドで待たない。**
途中で死ぬパターンが決まっているので、手順どおりに生存確認まで済ませること。
規則そのもの（再走・`cd` しない・門番と本走の違いなど）は [CLAUDE.md](../../../CLAUDE.md) の「計測」、
経緯は [`docs/lessons.md`](../../../docs/lessons.md) にある。

対ベースラインの基準は **8:55:31**（記録 #0、2026-09-13。32,131 秒）。

## 0. 何を測るか決める

```
tools/run.sh [実装ディレクトリ] [ラベル]
```

第1引数が計測する実装ディレクトリ。無指定なら `baseline/`。
ラベルを省くとディレクトリ名がそのままラベルになり、`runs/<日時>_<ラベル>/` の名前になる。

改善実装は `impl/<番号>_<名前>/` に置く。ビルド・実行・ログ出力先がベースラインと違うなら、
その実装ディレクトリに `impl.env` を置いて `BUILD_CMD` / `RUN_CMD` / `MAIN_LOG` を上書きする
（README の「実行方法」参照）。
**走らせる前に `impl.env` を読んで、何がビルドされ何が実行されるかを確認する。**

記録番号はラベルとは別に採番し、`results/<番号>_<ラベル>/` と README の `#` 列を揃える。
番号は勝手に取らない（指示を待つ）。

## 1. 事前確認

以下のコマンドはリポジトリのルートで実行する。**計測した `dat/` や `impl/` の中へ `cd` しない**
（`.claude/.cc-writes/` ができて、バイト比較と `impl_sha256` を狂わせる。パスは外から渡す）。

```bash
git status --porcelain                        # 作業ツリーがクリーンか (git_commit が env.txt に載る)
find impl/<番号>_<名前> -name __pycache__     # 何も出ないこと (出たら impl_sha256 に混ざる)
df -BG --output=avail . | tail -1             # 40GB 以上あるか
make check                                    # ハーネスが壊れていないか
```

- `tools/run.sh` 自体も 40GB 未満なら止まる
- README の計測環境と実機を照合する。同時に別の計測や重い計算が動いていないことも確認する
  （load average と CPU 使用率。ほかのプロセスの名前は記録に残さない）
- 本走は `numactl` で固定しない（固定するのは門番だけ）

### 巨大ページに使える空き（記録 #23 から）

`tools/run.sh` は `/proc/buddyinfo` の order 9 以上（2 MiB 以上の空きブロック）を両ノードで足し、
16 GiB（`HUGEFREE_MIN_GIB`）に満たなければ、作業ディレクトリも作らずに止まる。
止まったら次の順で進める。

1. 止まったときの `runs.out`（各ノードの値が出ている）を取っておく。証拠に「落とす前の値」として残す
2. 人かエージェントが root でキャッシュを落とす（`run.sh` 自身はやらない。エージェントは root を
   持たないので、ユーザーに `! sudo sh -c '...'` で頼む）:
   `sync; echo 3 > /proc/sys/vm/drop_caches; echo 1 > /proc/sys/vm/compact_memory`
3. `CACHE_DROP="<いつ・何をしたか>"` を付けて起動し直す。`env.txt` の `cache_drop:` と、
   作業ディレクトリの `hugefree.txt` に落としたあとの値が残る

**判定は走る前だけ。** 走ってから遅かった本を、落として走り直すのは引き直しと同じ。
付かなかった本もそのまま記録にし、`thp_fault_fallback`・`compact_stall` を備考に書く。

## 2. 起動する

Claude Code では、サンドボックス内のバックグラウンドプロセスが呼び出し終了時に終了した事例がある。
必要な実行権限を得たうえで `dangerouslyDisableSandbox: true` を使う。
他の実行環境では、その環境が提供する長時間実行の仕組みと権限設定に従う。

```bash
setsid nohup tools/run.sh <実装ディレクトリ> > runs.out 2>&1 < /dev/null & disown
```

`setsid nohup ... & disown` だけでは実行環境によるプロセス終了を防げない場合がある。
起動呼び出しが終わった後にも生存確認する。

## 3. 生存確認（飛ばさない）

起動から数秒おいて、**別の Bash 呼び出しで、サンドボックスの外で**確認する。
サンドボックス内の `pgrep` は PID 名前空間が別なのでホストのプロセスが見えず、動いているものを
「落ちた」と誤判定する。`pgrep -f '<起動コマンドの一部>'` は自分自身のコマンド行にもマッチする。

```bash
ps -eo pid,etimes,args | awk '/tools\/run.sh|animal_shogi.py/ && !/awk/'
```

コマンドと作業ディレクトリが今回の実行に一致していること、ログが更新されることを確認する。
PID の桁数では生存や名前空間を判定しない。ファイル（`freq.log` や `kaiseki_log/` の更新時刻）で
見るならサンドボックス内でよい。

失敗時のログは原因確認用に残す。プロセスの停止を確認してから、新しい作業ディレクトリで再実行する
（途中からの再開はしない）。

## 4. 完了を待つ

今回作られた `runs/<日時>_<ラベル>/` を特定し、そのパスを `R` に設定する。
過去の実行を拾う `runs/*` は監視に使わない。Claude Code では `run_in_background` で
`runs.out` に `計測終了` が出るまで待つループを回し、他の環境では対応する仕組みを使う。

```bash
R='runs/今回の日時とラベルに置き換える'
tail -40 runs.out
tail -20 "$R/kaiseki_log/kaiseki_log7.txt"
```

`計測終了` は解析プロセスの終了後に出る（`exit=N` が付く）。その後の検証完了も待つ。
ビルド失敗やハーネス自体の終了ではこの行が出ないため、ログだけを待ち続けず、
生存状態も確認する。ログの長時間停止は調査のきっかけとし、それだけで失敗と判定しない。

## 5. 結果を読む

`run.sh` が最後まで走れば `runs.out` に全部出ている。

```
=== 計測終了 <時刻> (exit=0) ===
NN時間NN分NN秒で全探索終了
完全解析にかかった時間： N時間NN分NN秒
	Elapsed (wall clock) time (h:mm:ss or m:ss): N:NN:NN
	Maximum resident set size (kbytes): NNNNNNN
PASS: 174 行すべて一致
```

**解析の `exit=0` と検証の `PASS` が両方必要。**
`tools/run.sh` 自身が両方を見て終了コードを決めるので、`runs.out` の末尾に
`⚠ 解析プロセスが exit=N で終わっている` が出ていないことを確認する。
`time.txt` の `Exit status: 0` も裏取りに使う。`PASS` だけでは成功と判定しない。

段ごとの秒は `kaiseki_log/forward_summary.tsv` と `retreat_summary.tsv` の生値で読む
（`main.log` の表示値は秒未満を切り捨てた下限）。`time.txt` から拾っておくと報告が厚くなるもの:

- `Percent of CPU this job got` — カテゴリ（1スレッド / 全コア）の裏付け
- `Minor (reclaiming a frame) page faults` / `Maximum resident set size`（KiB）
- ユーザー時間・カーネル時間を、最後の境界 `R_uk` の `utime_` / `stime_` / `min_` と突き合わせる

## 6. 証拠を results/ に置く

```bash
R=runs/<日時>_<ラベル>; D=results/<番号>_<ラベル>
mkdir -p "$D"
cp "$R/env.txt" "$D/env.txt"                        # 末尾に finished: / finished_jst: を足す (下)
cp "$R/kaiseki_log/kaizenkaiseki1.txt" "$D/main.log"  # = MAIN_LOG
cp "$R/time.txt" "$R/freq.log" "$R/vmstat.tsv" "$R/hugefree.txt" "$D/"
cp "$R/kaiseki_log/forward.tsv" "$R/kaiseki_log/forward_summary.tsv" \
   "$R/kaiseki_log/retreat_summary.tsv" "$D/"
python3 tools/verify_log.py "$D/main.log" > "$D/verify.txt" 2>&1
python3 tools/fingerprint_dat.py "$R/dat" --against oracle/fingerprint.tsv   # → fingerprint.txt
```

- `env.txt` には `runs.out` の `計測終了` にある実際の終了時刻を `finished:` / `finished_jst:` で追記する
  （`run.sh` は開始時刻しか書かない）。保存作業時の現在時刻で代用しない
- 区切りも順序も動かさない変更なら、直前の記録の `dat/` と `diff -rq` と md5 一覧の sha256
  （`find . -type f -print0 | LC_ALL=C sort -z | xargs -0 md5sum | sha256sum` を `dat/` の外から）で
  突き合わせて `bytecompare.txt` に、合計バイト数 ÷ 8 ＝ 246,803,167 を `sizecheck.txt` に書く。
  見出しは直前の記録の同名ファイルに倣う
- `main.log` の総数から `oracle/totals.tsv` の8項目が出ることも確かめる（`verify.txt` は174行だけを見る）
- **`env.txt` にホスト名を入れない。** `tests/test_run_harness.py` が落とす
- `freq.log` は個々の記録の結論には使わない（ばらつきの原因を追うための蓄積）
- キャッシュを落とした回は、落とす前の値（止まったときの `runs.out`）も残す
- サブログ（`kaiseki_log7.txt`）は1万行規模になるので入れない。`runs/` は `.gitignore` 済み

`results/README.md` のレイアウト表は凍結していて古い（`forward.tsv` 以降の追加が載っていない）。
いまの一式は直前の記録の `results/` を見る。

## 7. README の記録表と記録ノート

```
| # | 実装 | カテゴリ | タイム | 対ベースライン | 日付 | 備考 |
```

- **タイム** — `time.txt` の `Elapsed (wall clock)` を `H:MM:SS` で（秒未満は切り捨て）
- **対ベースライン** — 32,131 秒 ÷ `Elapsed` の秒（小数も使う）。速くなったら `N.NN×`
- **備考** — `results/` と記録ノートへのリンク、全探索 / 後退解析の内訳、門番の結果

分析は `docs/records/NN-<実装名>.md` に書き、`docs/records/README.md` の索引にも足す。
結果が予想と違ったらそれも書く。本走は1本なので、段の差を効果として読まない（判定は門番）。

## 8. コミットする

メッセージにはタイムと検証結果と内訳を入れる。`Claude-Session:` の URL 行は付けない。
push は指示されるまでしない。本走の `env.txt` が指すコミット（とその祖先）は、あとから書き換えない。

## 9. 後片付け

`runs/<日時>_<ラベル>/dat/` が数GB残る。消してよいが、**勝手に消さず確認を取る**。
