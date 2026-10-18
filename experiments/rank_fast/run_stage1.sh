#!/bin/bash
# 実験 rank_fast の段1: 完走 3 本 (perf record) と rankOf だけのベンチ (記録試行ではない). 進行は logs/console_stage1.log
#
# 完走は 3回 (r1〜r3) × 2種類 (l1: cycles と L1 の外れ, l2: cycles と L2 で当たったロード) の6本で, どれも
# impl/38_precheck の写し (run_one.sh). 回ごとの種類の順は r1 と r3 が l1 → l2, r2 が l2 → l1. ラベルは r<回>_<種類>.
# そのあと base のベンチをビルドして run_rankbench.sh を回す (2 入力 × (none ＋ 3 つの回し方) × 7 周 ＝ 56 本).
# 登録のときは完走3本 (1本で3つのイベント) だった. 本番の前の試しで直した (README の「本番の前の試しで直したこと」)
# 回す前の負荷は load average と CPU 使用率の合計だけを残す (プロセスの名前は残さない. CLAUDE.md)
# ⚠️ 完走 1 本が約 2 分 (perf record の後始末を含む), ベンチが約 5 分. その間このマシンで他の計算を回さないこと
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
mkdir -p "$HERE/logs"
if [ -e "$HERE/logs/console_stage1.log" ]; then
    echo "logs/console_stage1.log が残っている. 前回と混ざるので, 退避してから起動すること" >&2
    exit 2
fi
if [ -e "$ROOT/runs/rank_fast" ]; then
    echo "前回の runs/rank_fast が残っている. 退避するか消してから起動すること" >&2
    exit 2
fi
if [ -n "$(find "$ROOT/impl/38_precheck" -name __pycache__)" ]; then
    echo "impl/38_precheck に __pycache__ がある. 消してから起動すること" >&2
    exit 2
fi
exec > >(tee "$HERE/logs/console_stage1.log") 2>&1

echo "=== rank_fast 段1 開始 $(date --iso-8601=seconds) ==="
echo "--- perf と設定 ---"
perf --version
PARANOID=$(cat /proc/sys/kernel/perf_event_paranoid)
echo "kernel.perf_event_paranoid = $PARANOID"
echo "kernel.perf_event_max_sample_rate = $(cat /proc/sys/kernel/perf_event_max_sample_rate)"
echo "kernel.nmi_watchdog = $(cat /proc/sys/kernel/nmi_watchdog)"
if [ "$PARANOID" != 1 ]; then
    echo "!!! kernel.perf_event_paranoid が 1 でない. 回さない (本人に知らせる. 止める条件 5)" >&2
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

for r in 1 2 3; do
    if [ "$r" = 2 ]; then KINDS=(l2 l1); else KINDS=(l1 l2); fi
    for k in "${KINDS[@]}"; do
        echo "=== 開始 r${r}_$k $(date --iso-8601=seconds) ==="
        "$HERE/run_one.sh" "$k" "r${r}_$k"
    done
done

echo "=== 開始 rankbench_base $(date --iso-8601=seconds) ==="
"$HERE/build_bench.sh" "$ROOT/impl/38_precheck" "$ROOT/runs/rank_fast/bench_base"
"$HERE/run_rankbench.sh" "$HERE/logs/rankbench_stage1.tsv" "base=$ROOT/runs/rank_fast/bench_base"
echo "=== rank_fast 段1 完了 $(date --iso-8601=seconds) ==="
