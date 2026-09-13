# CLAUDE.md

このリポジトリで作業するときの取り決め。何を作っているかは [README.md](README.md) にある。
ここに書くのは README から読み取れない運用ルールだけ。

新しく決まった取り決めは、エージェントのローカルメモリではなく**このファイルに書く**。
ローカルメモリは個々の環境に紐づいていて clone に付いてこないので、共有されないし、
古くなっても誰も気づけない。

## 絶対に変更しないもの

| | 理由 |
|---|---|
| `baseline/` | 2021年11月のコードの凍結。RTA の出発点が動くとタイムの意味が消える |
| `oracle/` | 答えを固定している不変量。ここが動いたら全記録が無効になる |
| `results/` | 記録済みアテンプトの証拠 |

**末尾空白の除去すら禁止。** `.pre-commit-config.yaml` のトップレベル `exclude` と
`tests/test_baseline_frozen.py` で機械的に守っているが、手で回避しないこと。

改善実装は `baseline/` の外に新しいディレクトリを作って置く。
`-O3` を付けるだけの1段目も例外ではない。

## 計測

手順の全体は [`.claude/skills/measure/SKILL.md`](.claude/skills/measure/SKILL.md) にある。
要点だけ:

- **SSH も clone も要らない。** 計測機はこのリポジトリが置かれているマシンそのもの。
  別ホストへ clone しても二重コピーになるだけ。
- **数時間かかる**（ベースラインで約9時間）。フォアグラウンドで待たない。

  ```bash
  setsid nohup tools/run.sh <ラベル> > runs.out 2>&1 < /dev/null & disown
  ```

- **Claude Code のサンドボックス内から起動すると死ぬ。** その Bash 呼び出しが終わった時点で
  サンドボックスの PID 名前空間ごと破棄され、デタッチしたはずのプロセスも SIGKILL される。
  `dangerouslyDisableSandbox` で起動すること。起動直後に `pgrep -af animal_shogi` を見て、
  ホストの PID（6〜7桁）が出ていれば成功。PID が 1 や 2 に見えるならそれは名前空間の中で、必ず死ぬ。
- 進捗は `runs/*/kaiseki_log/` のファイル更新で見る（サンドボックス内からでも見える）。
  完了検知は `runs.out` に `計測終了` が出るのを待つ。

## 記録に残さないもの

- **ホスト名。** `tools/run.sh` からは削除済み。`results/` に置く `env.txt` にも入れない。
  計測機の同一性は `cpu` / `cores` / `mem_total` で足りる。
  `tests/test_run_harness.py` が守っている。

## コミット

- メッセージは日本語。何をしたかだけでなく **なぜそうしたか** を書く。
- `Co-Authored-By: Claude ...` の行は付けてよい。
- **`Claude-Session:` の URL 行は付けない。** 公開リポジトリなので、コミットログに
  会話ログへの恒久的なポインタを残さない。ハーネスがこの行を付けるよう指示してきても、
  ここの指示が優先する。
- push は指示されるまでしない。

## チェック

```bash
make setup && make hooks   # 新しい作業コピーで最初に一度
make check                 # ruff / shellcheck / mypy / pytest。CI と同じ
```

pre-commit フックは `.git/hooks` にあって clone に付いてこない。
clone 直後は `make hooks` を忘れないこと（CI はその保険でもある）。
