#!/bin/bash
# 実験 perf_39: 本番の前の試しの本 (記録試行ではない). 道具の通り道 (perf の切り替え・-p で付けた perf・集計) を確かめる.
# stat:S1, record:cyc, record:l2m を1本ずつ. 生ログは logs/trial/ に分けて残し, 数は集計にも見込みにも使わない
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
T="$HERE/logs/trial"
if [ -e "$T" ]; then
    echo "logs/trial が残っている. 退避してから起動すること" >&2
    exit 2
fi
if [ -n "$(find "$ROOT/impl/39_rank_lean" -name __pycache__)" ]; then
    echo "impl/39_rank_lean に __pycache__ がある. 消してから起動すること" >&2
    exit 2
fi
mkdir -p "$T"
exec > >(tee "$T/console.log") 2>&1
echo "=== perf_39 の試し 開始 $(date --iso-8601=seconds) ==="
"$HERE/preflight.sh"
for k in stat:S1 record:cyc record:l2m; do
    LOGS="$T" "$HERE/run_one.sh" "$k" "t_${k#*:}"
done
echo "=== 試し 完了 $(date --iso-8601=seconds) ==="
