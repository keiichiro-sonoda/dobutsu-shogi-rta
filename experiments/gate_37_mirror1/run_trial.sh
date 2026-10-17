#!/bin/bash
# 門番の前に1本, new を完走させて答えの検査を通す (門番 #37。記録試行ではない. 計時には使わない)
#
#   run_trial.sh
#
# run_one.sh new trial_new と同じ検査 (オラクル・答え・件数の列・巨大ページ). #37 は後退解析の側の並びが
# #36 と変わるので, diff -rq は回さない (答えは手数ごとの集合で見る). 進行は logs/console_trial.log.
# この本の時間は判定にも予測の照合にも使わない (logs/console.log に入れないので stop_rule.py も読まない)
set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
mkdir -p "$HERE/logs"
if [ -e "$HERE/logs/console_trial.log" ]; then
    echo "logs/console_trial.log が残っている. 退避してから起動すること" >&2
    exit 2
fi
exec > >(tee "$HERE/logs/console_trial.log") 2>&1
echo "=== 門番 #37 の前の確かめ 開始 $(date --iso-8601=seconds) ==="
echo "--- 回す前の負荷 ---"
awk '{print "load average:", $1 ",", $2 ",", $3}' /proc/loadavg
BUSY=$(vmstat 1 2 | awk 'NR == 2 {for (i = 1; i <= NF; i++) if ($i == "id") c = i} END {print 100 - $c}')
echo "CPU 使用率 (全 CPU, 1秒): ${BUSY}%"
if [ "$BUSY" -gt 3 ]; then
    echo "!!! CPU 使用率が ${BUSY}% (3% を超える). ほかの計算が動いているので回さない (本人に知らせる)" >&2
    exit 6
fi
"$HERE/run_one.sh" new trial_new
echo "=== 門番 #37 の前の確かめ 終了 $(date --iso-8601=seconds) ==="
