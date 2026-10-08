#!/bin/bash
# 実験 perf_34: 完走 26 本とベンチ (記録試行ではない). 進行は logs/console.log に残す
#
#   base                         perf を付けない (段の秒の基準)
#   dump                         ベンチの入力を書き出す (段の秒は比べない)
#   r1〜r3: stat:T1 … stat:C2, record を, 回ごとに3つずつずらした順で (各 8 本)
#   ベンチ (run_bench.sh)
#
# どの本も numactl でノード0に固定し, 走る前にノード0の空きメモリを確かめる (run_one.sh).
# 回す前の負荷は load average と CPU 使用率の合計だけを残す (プロセスの名前は残さない. CLAUDE.md)
# ⚠️ 1本あたり完走 2〜3分 + 検査 (指紋に1分) で, 26本で約1時間半. その間このマシンで他の計算を回さないこと
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
mkdir -p "$HERE/logs"
if [ -e "$HERE/logs/console.log" ]; then
    echo "logs/console.log が残っている. 前回と混ざるので, 退避してから起動すること" >&2
    exit 2
fi
if [ -n "$(find "$ROOT/impl/34_unmove" -name __pycache__)" ]; then
    echo "impl/34_unmove に __pycache__ がある. 消してから起動すること" >&2
    exit 2
fi
exec > >(tee "$HERE/logs/console.log") 2>&1

echo "=== perf_34 開始 $(date --iso-8601=seconds) ==="
echo "--- perf と設定 ---"
perf --version
echo "kernel.perf_event_paranoid = $(cat /proc/sys/kernel/perf_event_paranoid)"
echo "kernel.nmi_watchdog = $(cat /proc/sys/kernel/nmi_watchdog)"
echo "--- 回す前の負荷 ---"
awk '{print "load average:", $1 ",", $2 ",", $3}' /proc/loadavg
vmstat 1 2 | awk 'NR == 2 {for (i = 1; i <= NF; i++) if ($i == "id") c = i}
                  END {print "CPU 使用率 (全 CPU, 1秒):", 100 - $c "%"}'
echo "--- 回す前のノード0のメモリ (/proc/buddyinfo と meminfo) ---"
grep "Node 0" /proc/buddyinfo
grep -E "MemFree|FilePages" /sys/devices/system/node/node0/meminfo

"$HERE/run_one.sh" base base
"$HERE/run_one.sh" dump dump
KINDS=(stat:T1 stat:T2 stat:M1 stat:M2 stat:M3 stat:C1 stat:C2 record)
for r in 1 2 3; do
    off=$(( (r - 1) * 3 ))
    for i in $(seq 0 7); do
        k=${KINDS[$(( (i + off) % 8 ))]}
        "$HERE/run_one.sh" "$k" "r${r}_${k#stat:}"
    done
done
"$HERE/run_bench.sh"
echo "=== perf_34 完了 $(date --iso-8601=seconds) ==="
