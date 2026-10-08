#!/bin/bash
# 門番の前に1本, new を完走させて答えの検査を通す (門番 #34。記録試行ではない. 計時には使わない)
#
#   run_trial.sh
#
# run_one.sh new trial_new と同じ検査 (オラクル・答え・件数の列・巨大ページ). 進行は logs/console_trial.log.
# この本の時間は判定にも予測の照合にも使わない (logs/console.log に入れないので stop_rule.py も読まない)
set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
mkdir -p "$HERE/logs"
if [ -e "$HERE/logs/console_trial.log" ]; then
    echo "logs/console_trial.log が残っている. 退避してから起動すること" >&2
    exit 2
fi
exec > >(tee "$HERE/logs/console_trial.log") 2>&1
echo "=== 門番 #34 の前の確かめ 開始 $(date --iso-8601=seconds) ==="
"$HERE/run_one.sh" new trial_new
echo "=== 門番 #34 の前の確かめ 終了 $(date --iso-8601=seconds) ==="
