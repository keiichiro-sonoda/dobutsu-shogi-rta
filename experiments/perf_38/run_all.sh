#!/bin/bash
# 実験 perf_38: 完走 54 本 (記録試行ではない). 進行は logs/console.log に残す
#
# 種類は stat:T1 … stat:C2 (perf_34 の7組), stat:S1 (書き込みの組), record の 9 つ.
# 3回 (r1〜r3) まわし, 回ごとに種類の順を3つずつずらす. 種類ごとに2腕を続けて回し, 腕の順は
# r1 と r3 が r37 → r38, r2 が r38 → r37 (種類ごとに r37 r38 r38 r37 r37 r38 と交互になる).
# 9 種類 × 2 腕 × 3 回 ＝ 54 本 (perf stat 48 本, perf record 6 本). ラベルは r<回>_<種類>_<腕>.
# どの本も numactl でノード0に固定し, 走る前にノード0の空きを確かめる (run_one.sh).
# 回す前の負荷は load average と CPU 使用率の合計だけを残す (プロセスの名前は残さない. CLAUDE.md)
# ⚠️ 1本あたり完走 1.5 分 + 検査とビルド 約 0.5 分で, 54 本で約 2 時間. その間このマシンで他の計算を回さないこと
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
mkdir -p "$HERE/logs"
if [ -e "$HERE/logs/console.log" ]; then
    echo "logs/console.log が残っている. 前回と混ざるので, 退避してから起動すること" >&2
    exit 2
fi
if [ -e "$ROOT/runs/perf_38" ]; then
    echo "前回の runs/perf_38 が残っている. 退避するか消してから起動すること" >&2
    exit 2
fi
if [ -n "$(find "$ROOT/impl/37_mirror1" "$ROOT/impl/38_precheck" -name __pycache__)" ]; then
    echo "impl/37_mirror1 か impl/38_precheck に __pycache__ がある. 消してから起動すること" >&2
    exit 2
fi
exec > >(tee "$HERE/logs/console.log") 2>&1

echo "=== perf_38 開始 $(date --iso-8601=seconds) ==="
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

KINDS=(stat:T1 stat:T2 stat:M1 stat:M2 stat:M3 stat:C1 stat:C2 stat:S1 record)
for r in 1 2 3; do
    off=$(( (r - 1) * 3 ))
    if [ "$r" = 2 ]; then ARMS=(r38 r37); else ARMS=(r37 r38); fi
    for i in $(seq 0 8); do
        k=${KINDS[$(( (i + off) % 9 ))]}
        for a in "${ARMS[@]}"; do
            "$HERE/run_one.sh" "$a" "$k" "r${r}_${k#stat:}_${a}"
        done
    done
done
echo "=== 全54本 完了 $(date --iso-8601=seconds) ==="
