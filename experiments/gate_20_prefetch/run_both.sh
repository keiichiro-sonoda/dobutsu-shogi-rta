#!/bin/bash
# 2つの門番を続けて回す (全探索 → 後退解析. 後退解析の入力が無いときは全探索が作る)
set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
echo "=== 門番2つ 開始 $(date --iso-8601=seconds) ==="
"$HERE/run_all_forward.sh" 2>&1 | tee "$HERE/logs/console_forward.log"
"$HERE/run_all_retreat.sh" 2>&1 | tee "$HERE/logs/console_retreat.log"
echo "=== 門番2つ 終了 $(date --iso-8601=seconds) ==="
