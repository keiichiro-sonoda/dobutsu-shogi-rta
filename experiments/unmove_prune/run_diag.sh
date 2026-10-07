#!/bin/bash
# 診断 (実験 unmove_prune。記録試行ではない). 一致の検査の (e)・(f) が外れたあとに足した
#
#   run_diag.sh [dat/]
#
# 候補ごとの判定を, cls ではなく候補そのものをいまの生成器に通した戻り値と比べる (bench.c の diag).
# ベンチ本体だけを作り直す (prune.so は run_verify.sh で作ったものを使う). 出力は logs/diag.txt と logs/console_diag.log
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
DAT="${1:-$ROOT/runs/20261004-091929_33_hot_layout/dat}"
W="$ROOT/runs/unmove_prune"
if [ -e "$HERE/logs/console_diag.log" ]; then
    echo "logs/console_diag.log が残っている. 退避してから起動すること" >&2
    exit 2
fi
echo "=== unmove_prune 診断 開始 $(date --iso-8601=seconds) ===" > "$HERE/logs/console_diag.log"
cp "$HERE/bench.c" "$W/build/bench.c"
(cd "$W/build" && gcc -O2 -Wall -Wextra bench.c -o bench -ldl)
echo "prune.so sha256 $(sha256sum "$W/build/prune.so" | cut -c1-12) / bench sha256 $(sha256sum "$W/build/bench" | cut -c1-12)" | tee "$HERE/logs/diag.txt"
set +e
"$W/build/bench" diag "$W/build/prune.so" "$DAT" "$W" | tee -a "$HERE/logs/diag.txt"
RC=${PIPESTATUS[0]}
set -e
echo "diag の終了コード: $RC" | tee -a "$HERE/logs/diag.txt"
echo "=== unmove_prune 診断 終了 $(date --iso-8601=seconds) (diag の終了コード $RC) ===" >> "$HERE/logs/console_diag.log"
exit "$RC"
