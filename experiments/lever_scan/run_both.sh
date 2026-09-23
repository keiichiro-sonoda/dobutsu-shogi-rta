#!/bin/bash
# 2つの門番を続けて回す. 機械時間の上限は2つ合わせて4時間 (測る前に決めた).
#
#   run_both.sh
#
# 全探索 → 後退解析の順 (後退解析の入力は全探索の1本目が作る).
# 上限に届きそうなら, その時点の本数で止める. 途中で腕を足したり,
# 結果を見て本数を増やしたりしない.
set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
DEADLINE=$(($(date +%s) + 4 * 3600))
export DEADLINE
echo "=== 門番2つ 開始 $(date --iso-8601=seconds) / 期限 $(date -d "@$DEADLINE" --iso-8601=seconds) ==="
"$HERE/run_all_forward.sh" 2>&1 | tee "$HERE/logs/console_forward.log"
"$HERE/run_all_retreat.sh" 2>&1 | tee "$HERE/logs/console_retreat.log"
echo "=== 門番2つ 終了 $(date --iso-8601=seconds) ==="
