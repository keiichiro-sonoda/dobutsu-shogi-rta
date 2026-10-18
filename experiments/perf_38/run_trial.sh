#!/bin/bash
# 本番の前の試し (実験 perf_38。記録試行ではない. 集計にも見込みにも使わない)
#
#   run_trial.sh
#
# r38 で stat:S1 と record を1本ずつ回し, perf の切り替え・多重化の確かめ・集計 (attribute.py) と検査が通ることを見る.
# ログは logs/trial/ に分けて残す (logs/ の直下に出たものを移す). 進行は logs/trial/console.log
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
T="$HERE/logs/trial"
if [ -e "$T" ]; then
    echo "logs/trial が残っている. 退避してから起動すること" >&2
    exit 2
fi
mkdir -p "$T"
exec > >(tee "$T/console.log") 2>&1
echo "=== perf_38 の試し 開始 $(date --iso-8601=seconds) ==="
for k in stat:S1 record; do
    lb="trial_${k#stat:}_r38"
    "$HERE/run_one.sh" r38 "$k" "$lb"
    mv "$HERE/logs/${lb}"_* "$T/"
done
rm -rf "$ROOT/runs/perf_38"
echo "=== perf_38 の試し 終了 $(date --iso-8601=seconds) ==="
