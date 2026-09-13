---
name: measure
description: どうぶつしょうぎ完全解析 RTA のアテンプトを1本走らせて記録する。起動・生存確認・完了待ち・オラクル検証・results/ への証拠保存・README 記録表の更新・コミットまでの一連。「計測して」「ベースラインを測って」「アテンプトを走らせて」「タイムを取って」といった依頼で使う。
---

# アテンプトを1本走らせて記録する

数時間かかる。**フォアグラウンドで待たない。**
途中で死ぬパターンが決まっているので、手順どおりに生存確認まで済ませること。

対ベースラインの基準は **8:55:31**（記録 #0、2026-09-13）。

## 0. 何を測るか決める

`tools/run.sh <ラベル>` の `<ラベル>` が `runs/<日時>_<ラベル>/` の名前になる。
現行の `tools/run.sh` は常に `baseline/` をコピーして実行する。ラベルでは実装を選べない。
改善実装を測るときは、先にハーネスを対応させ、コピー元・ビルドフラグ・実行対象を確認する。
ベースラインならラベルは `baseline`、改善実装なら `o3` などとする。

記録番号はラベルとは別に採番し、`results/<番号>_<ラベル>/` と README の `#` 列を揃える。

## 1. 事前確認

```bash
git status --porcelain          # 作業ツリーがクリーンか (git_commit が env.txt に載る)
df -BG --output=avail . | tail -1   # 40GB 以上あるか
make check                      # ハーネスが壊れていないか
```

`tools/run.sh` 自体も 40GB 未満なら止まる。
README の計測環境と実機を照合する。同時に別の計測が動いていないことも確認する。
以下のコマンドはリポジトリのルートで実行する。

## 2. 起動する

Claude Code でサンドボックス内のバックグラウンドプロセスが呼び出し終了時に
終了した事例がある。必要な実行権限を得たうえで `dangerouslyDisableSandbox: true` を使う。
他の実行環境では、その環境が提供する長時間実行の仕組みと権限設定に従う。

```bash
setsid nohup tools/run.sh <ラベル> > runs.out 2>&1 < /dev/null & disown
```

`setsid nohup ... & disown` だけでは実行環境によるプロセス終了を防げない場合がある。
起動呼び出しが終わった後にも生存確認する。

## 3. 生存確認（飛ばさない）

起動から数秒おいて、**別の Bash 呼び出しで**確認する。

```bash
pgrep -af animal_shogi
```

起動時と同じプロセスが見える環境で確認し、コマンドと作業ディレクトリが今回の実行に
一致していること、ログが更新されることを確認する。PID の桁数では生存や名前空間を判定しない。
何も出なければ、プロセスの可視性と `runs.out` を確認する。

失敗時のログは原因確認用に残す。プロセスの停止を確認してから、新しい作業ディレクトリで再実行する。

## 4. 完了を待つ

今回作られた `runs/<日時>_<ラベル>/` を特定し、そのパスを `R` に設定する。
過去の実行を拾う `runs/*` は監視に使わない。Claude Code では `run_in_background` で
短い間隔の確認を繰り返し、他の環境では対応するバックグラウンド実行の仕組みを使う。

```bash
R='runs/今回の日時とラベルに置き換える'
tail -40 runs.out
tail -20 "$R/kaiseki_log/kaiseki_log7.txt"
```

`計測終了` は解析プロセスの終了後に出る（`exit=N` が付く）。その後の検証完了も待つ。
ビルド失敗やハーネス自体の終了ではこの行が出ないため、ログだけを待ち続けず、
生存状態も確認する。ログの長時間停止は調査のきっかけとし、それだけで失敗と判定しない。

別の Bash 呼び出しでは `R` を再設定する。名前空間が分離された環境では `pgrep` に
ホスト側のプロセスが見えない場合があるので、起動時と同じ環境で確認する。

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

**解析の `exit=0` と検証の `PASS` が両方必要。** `time.txt` の `Exit status: 0` も確認する。
ハーネスは解析が失敗しても検証を続けるため、`PASS` だけでは成功と判定しない。

`time.txt` から拾っておくと報告が厚くなるもの:

- `Percent of CPU this job got` — カテゴリ（1スレッド / 全コア）の裏付け
- `File system outputs` — 512バイト単位。ディスク書き込み量に換算する
- `Maximum resident set size` — Linux では KiB 単位。GiB にするには 1,048,576 で割る

`kaiseki_log/kaizenkaiseki1.txt` の `所要時間：` 行を集計すると、
後退解析のどのフェーズに時間が寄っているかが出る。改善の方向を決める材料になる。

## 6. 証拠を results/ に置く

レイアウトは [`results/README.md`](../../../results/README.md) のとおり。

```bash
R=runs/<日時>_<ラベル>
mkdir -p results/<番号>_<ラベル>
cp "$R/env.txt"                          results/<番号>_<ラベル>/env.txt
cp "$R/kaiseki_log/kaizenkaiseki1.txt"   results/<番号>_<ラベル>/main.log
cp "$R/time.txt"                         results/<番号>_<ラベル>/time.txt
python3 tools/verify_log.py results/<番号>_<ラベル>/main.log > results/<番号>_<ラベル>/verify.txt 2>&1
```

新規の `env.txt` には `runs.out` の `計測終了` にある実際の終了時刻を追記する
（`run.sh` は開始時刻しか書かない）。保存作業時の現在時刻で代用しない。

**`env.txt` にホスト名を入れないこと。** `tests/test_run_harness.py` が落とす。

サブログ（`kaiseki_log7.txt`）は1万行規模になるので入れない。
`runs/` は `.gitignore` 済みなので、残すものだけをここへコピーする。

## 7. README の記録表を更新する

```
| # | 実装 | カテゴリ | タイム | 対ベースライン | 日付 | 備考 |
```

- **タイム** — README の定義どおり、`time.txt` の `Elapsed (wall clock)` を `H:MM:SS` で
- **対ベースライン** — 8:55:31 (32,131秒) との比。速くなったら `N.NN×`
- **備考** — `results/` へのリンクと、全探索 / 後退解析の内訳

結果が予想と違ったらそれも書く。README は「実際にやってみて外れたらそれも記録する」と宣言している。

## 8. コミットする

メッセージにはタイムと検証結果と内訳を入れる。`Claude-Session:` の URL 行は付けない
（[CLAUDE.md](../../../CLAUDE.md) 参照）。push は指示されるまでしない。

## 9. 後片付け

`runs/<日時>_<ラベル>/dat/` が数GB残る。消してよいが、**勝手に消さず確認を取る**。
