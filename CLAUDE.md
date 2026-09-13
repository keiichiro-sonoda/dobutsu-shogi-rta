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

**既存の内容は末尾空白の除去すら禁止。** 新規アテンプトの証拠は `results/` に追加する。
`.pre-commit-config.yaml` の `exclude` は自動修正の対象外にする設定で、編集自体は防がない。
`tests/test_baseline_frozen.py` は baseline のソースのハッシュとビルド設定の一部を検査する。

改善実装は `baseline/` の外に新しいディレクトリを作って置く。
`-O3` を付けるだけの1段目も例外ではない。

## 計測

手順の全体は [`.claude/skills/measure/SKILL.md`](.claude/skills/measure/SKILL.md) にある。
要点だけ:

- README に記載した計測機上の作業コピーでは、SSH や再 clone は不要。
  他の環境に clone した場合は実機を照合する。別の計測機なら README のルールどおり記録表を分ける。
- 第1引数が計測する実装ディレクトリ。無指定なら `baseline/`。
  ビルドと実行のコマンドは実装側の `impl.env` で差し替える（詳細は README）。
- **数時間かかる**（ベースラインで約9時間）。フォアグラウンドで待たない。

  ```bash
  setsid nohup tools/run.sh <実装ディレクトリ> > runs.out 2>&1 < /dev/null & disown
  ```

- Claude Code のサンドボックス内で、呼び出し終了時にデタッチしたプロセスも終了した事例がある。
  必要な実行権限を得たうえで `dangerouslyDisableSandbox` を使い、別の呼び出しでも生存を確認する。
  PID の桁数は判定に使わず、今回のコマンド・作業ディレクトリ・ログ更新を照合する。
- 進捗は今回の `runs/<日時>_<ラベル>/kaiseki_log/` のファイル更新で見る。
  `runs.out` の `計測終了` に加え、解析の終了コードと検証結果を確認する。

## 記録に残さないもの

- **ホスト名。** `tools/run.sh` からは削除済み。`results/` に置く `env.txt` にも入れない。
  計測機の同一性は `cpu` / `cores` / `mem_total` で足りる。
  `tests/test_run_harness.py` が守っている。

## コミット

- メッセージは日本語。何をしたかだけでなく **なぜそうしたか** を書く。
- `Co-Authored-By: Claude ...` の行は付けてよい。
- **`Claude-Session:` の URL 行は付けない。** 公開リポジトリなので、コミットログに
  会話ログへの恒久的なポインタを残さない。
- push は指示されるまでしない。

## チェック

```bash
make setup && make hooks   # 新しい作業コピーで最初に一度
make check                 # ruff / shellcheck / mypy / pytest。CI と同じ
```

pre-commit フックは `.git/hooks` にあって clone に付いてこない。
clone 直後は `make hooks` を忘れないこと（CI はその保険でもある）。
