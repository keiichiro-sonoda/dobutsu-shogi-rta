#!/bin/bash
# 回す前の確かめ (実験 perf_39。記録試行ではない). run_all.sh と run_trial.sh が呼ぶ.
# perf の版と設定, 負荷 (load average と CPU 使用率の合計だけ), ノード0のメモリを出し,
# kernel.perf_event_paranoid が 1 でない (止める条件 4) か, CPU 使用率が 3% を超える (ほかの計算が動いている) なら止める
set -euo pipefail
echo "--- perf と設定 ---"
perf --version
PARANOID=$(cat /proc/sys/kernel/perf_event_paranoid)
echo "kernel.perf_event_paranoid = $PARANOID"
echo "kernel.perf_event_max_sample_rate = $(cat /proc/sys/kernel/perf_event_max_sample_rate)"
echo "kernel.nmi_watchdog = $(cat /proc/sys/kernel/nmi_watchdog)"
if [ "$PARANOID" != 1 ]; then
    echo "!!! kernel.perf_event_paranoid が 1 でない. 回さない (本人に知らせる. 止める条件 4)" >&2
    exit 5
fi
echo "--- 回す前の負荷 ---"
awk '{print "load average:", $1 ",", $2 ",", $3}' /proc/loadavg
BUSY=$(vmstat 1 2 | awk 'NR == 2 {for (i = 1; i <= NF; i++) if ($i == "id") c = i} END {print 100 - $c}')
echo "CPU 使用率 (全 CPU, 1秒): ${BUSY}%"
if [ "$BUSY" -gt 3 ]; then
    echo "!!! CPU 使用率が ${BUSY}% (3% を超える). ほかの計算が動いているので回さない (本人に知らせる)" >&2
    exit 6
fi
echo "--- 回す前のノード0のメモリ (/proc/buddyinfo と meminfo) ---"
grep "Node 0" /proc/buddyinfo
grep -E "MemFree|FilePages" /sys/devices/system/node/node0/meminfo
