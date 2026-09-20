#!/bin/sh
# push しようとしている ref を1つずつ publish_lint に渡す。
#
# ⚠️ HEAD を見てはいけない。`main` にいるまま `git push origin <鍵入りブランチ>` が
#    できるので、HEAD を終点にすると「0コミット・指摘なし」で通ってしまう。
#    git は pre-push フックの標準入力に push 対象を1行ずつ渡す:
#        <ローカルの ref> <ローカルの sha> <リモートの ref> <リモートの sha>
#
# pre-commit の pre-push ステージには載せていない。あれは ref を1つしか渡さないので、
# `git push origin b1 b2` の b2 が検査されないまま通る (実測)。
set -eu

remote="${1:-origin}"
root=$(git rev-parse --show-toplevel)
status=0
# 検査の呼び出し方。テストから別の実行系に差し替えられるようにしてある
: "${PUBLISH_LINT_CMD:=uv run python tools/publish_lint.py}"

while read -r _local_ref local_sha _remote_ref _remote_sha; do
    # ローカルの sha がすべて 0 なら ref の削除。新しく公開されるものは無い
    case "$local_sha" in
        *[!0]*) ;;
        *) continue ;;
    esac
    # shellcheck disable=SC2086  # PUBLISH_LINT_CMD は複数語のコマンドなので分割させる
    if ! (cd "$root" && $PUBLISH_LINT_CMD --to "$local_sha" --remote "$remote")
    then
        status=1
    fi
done

if [ "$status" -ne 0 ]; then
    echo "pre-push: publish_lint で止めた。push しない" >&2
fi
exit "$status"
