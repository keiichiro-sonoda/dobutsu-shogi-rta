#!/bin/bash
# B1・B1′・B2 の計時 (実験 attack_count。記録試行ではない). run_count.sh のあとに回す
#
#   run_time.sh
#
# 4つの版 (gen = いまの前向きの生成器 / b1 = unmove_catch の B1 / b1x = この実験の B1′ / b2 = unmove_catch の B2) を
# 1本ずつ別のプロセスで測る (.so は1つだけ開く. RTLD_LOCAL).
# 5周まわし, 周ごとに順番を1つずつずらす. どの本も numactl でノード0に固定する.
# 版ごとに unknown / catch / try / mixed を1周温めてから1周測る (unmove_bench と同じ形).
# logs/count.txt が PASS でなければ測らない (止める条件. B1′ の判定が1局面でも合わなければ測らない)
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$HERE/lib.sh"
W="$ROOT/runs/attack_count"
ROUNDS=5
VARIANTS=(gen b1 b1x b2)
NUMA=(numactl --cpunodebind=0 --membind=0)
if [ -e "$HERE/logs/timing.tsv" ]; then
    echo "logs/timing.tsv が残っている. 退避してから起動すること" >&2
    exit 2
fi
if ! grep -q '食い違い 0 局面 => PASS' "$HERE/logs/count.txt"; then
    echo "!!! B1′ の一致の検査が PASS でないので測らない (止める条件)" >&2
    exit 1
fi
exec > >(tee "$HERE/logs/console_time.log") 2>&1
echo "=== attack_count B1・B1′・B2 計時 開始 $(date --iso-8601=seconds) ==="
echo "attack.so sha256 $(sha256sum "$W/build/attack.so" | cut -c1-12) / bench sha256 $(sha256sum "$W/build/bench" | cut -c1-12)"
awk '{print "load average:", $1 ",", $2 ",", $3}' /proc/loadavg
vmstat 1 2 | awk 'NR == 2 {for (i = 1; i <= NF; i++) if ($i == "id") c = i}
                  END {print "CPU 使用率 (全 CPU, 1秒):", 100 - $c "%"}'
FB0=$(awk '$1 == "thp_fault_fallback" {print $2}' /proc/vmstat)
freq_header > "$HERE/logs/time_freq.log"
sample_hw >> "$HERE/logs/time_freq.log" 2>/dev/null &
SPID=$!
trap 'kill "$SPID" 2>/dev/null || true' EXIT
printf 'version\tround\tsample\tn\tns_per_q\tout_per_q\n' > "$HERE/logs/timing.tsv"
for r in $(seq 1 "$ROUNDS"); do
    for i in 0 1 2 3; do
        v="${VARIANTS[$(( (i + r - 1) % 4 ))]}"
        echo "--- r${r} $v ($(date +%H:%M:%S)) ---"
        "${NUMA[@]}" "$W/build/bench" time "$W/build/attack.so" "$W" "$v" "$r" | tee -a "$HERE/logs/timing.tsv"
    done
done
FB1=$(awk '$1 == "thp_fault_fallback" {print $2}' /proc/vmstat)
echo "thp_fault_fallback の前後差: $((FB1 - FB0))"
echo "=== attack_count B1・B1′・B2 計時 完了 $(date --iso-8601=seconds) ==="
