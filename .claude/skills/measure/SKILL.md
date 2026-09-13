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
ベースラインなら `baseline`。改善実装なら `01_o3` のように梯子の段数を入れる。

ラベルは `results/<番号>_<ラベル>/` と README 記録表の `#` 列にもそのまま使う。

## 1. 事前確認

```bash
git status --porcelain          # 作業ツリーがクリーンか (git_commit が env.txt に載る)
df -BG --output=avail . | tail -1   # 40GB 以上あるか
make check                      # ハーネスが壊れていないか
```

`tools/run.sh` 自体も 40GB 未満なら止まる。

## 2. 起動する

**必ず `dangerouslyDisableSandbox: true` で実行すること。**

```bash
setsid nohup tools/run.sh <ラベル> > runs.out 2>&1 < /dev/null & disown
```

サンドボックス内から起動すると、その Bash 呼び出しが終わった瞬間に
サンドボックスの PID 名前空間ごと破棄され、`setsid nohup ... & disown` でデタッチしていても
プロセスは SIGKILL される。数時間後に「何も残っていない」ことに気づく事故になる。

## 3. 生存確認（飛ばさない）

起動から数秒おいて、**別の Bash 呼び出しで**確認する。

```bash
pgrep -af animal_shogi
```

- ホストの PID（6〜7桁）が出ていれば成功。
- PID が `1` や `2` に見えるならサンドボックスの名前空間の中で、必ず死ぬ。やり直す。
- 何も出なければ既に死んでいる。`runs.out` を読む。

失敗していたら、中途半端な `runs/<日時>_<ラベル>/` を消してから起動し直す。

## 4. 完了を待つ

`run_in_background` で完了だけ拾う。進捗の垂れ流しは要らない。

```bash
while true; do
  if grep -q '計測終了' runs.out 2>/dev/null; then echo "=== 計測プロセス終了を検出 ==="; break; fi
  log=$(ls runs/*/kaiseki_log/kaiseki_log7.txt 2>/dev/null | head -1)
  if [ -n "$log" ]; then
    age=$(( $(date +%s) - $(stat -c %Y "$log") ))
    if [ "$age" -gt 3600 ]; then echo "=== STALL: サブログが ${age}s 更新されていない ==="; break; fi
  fi
  sleep 60
done
tail -40 runs.out
```

`計測終了` は成功でも失敗でも出る（`exit=N` が付く）ので、沈黙したまま見落とすことはない。
ストール検知も入れてあるのは、プロセスが消えても `計測終了` が書かれないケースがあるため。

途中経過を見たいときは `runs/*/kaiseki_log/kaiseki_log7.txt` の末尾を読む。
サンドボックス内からでも見える。`pgrep` はサンドボックス内からはホストのプロセスを見つけられない。

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

**`PASS` が出ていなければ記録として無効。** タイムを報告する前に検証結果を確認する。

`time.txt` から拾っておくと報告が厚くなるもの:

- `Percent of CPU this job got` — カテゴリ（1スレッド / 全コア）の裏付け
- `File system outputs` — 512バイト単位。ディスク書き込み量に換算する
- `Maximum resident set size` — KB 単位

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

`env.txt` には終了時刻を追記しておく（`run.sh` は開始時刻しか書かない）。

**`env.txt` にホスト名を入れないこと。** `tests/test_run_harness.py` が落とす。

サブログ（`kaiseki_log7.txt`）は1万行規模になるので入れない。
`runs/` は `.gitignore` 済みなので、残すものだけをここへコピーする。

## 7. README の記録表を更新する

```
| # | 実装 | カテゴリ | タイム | 対ベースライン | 日付 | 備考 |
```

- **タイム** — `完全解析にかかった時間` を `H:MM:SS` で
- **対ベースライン** — 8:55:31 (32,131秒) との比。速くなったら `N.NN×`
- **備考** — `results/` へのリンクと、全探索 / 後退解析の内訳

結果が予想と違ったらそれも書く。README は「実際にやってみて外れたらそれも記録する」と宣言している。

## 8. コミットする

メッセージにはタイムと検証結果と内訳を入れる。`Claude-Session:` の URL 行は付けない
（[CLAUDE.md](../../../CLAUDE.md) 参照）。push は指示されるまでしない。

## 9. 後片付け

`runs/<日時>_<ラベル>/dat/` が数GB残る。消してよいが、**勝手に消さず確認を取る**。
