#!/bin/bash
# 計時 (実験 unmove_bench。記録試行ではない). run_verify.sh のあとに回す
#
#   run_time.sh
#
# 5つの版 (cand / sieve / visit / degw / gen. bench.c の timing) を1本ずつ別のプロセスで測る
# (.so は1つだけ開く. 本番の CDLL と同じ RTLD_LOCAL). 5周まわし, 周ごとに版の順番を1つずつずらす.
# どの本も numactl でノード0に固定する. 版ごとに unknown / catch / try / mixed を1周温めてから1周測る.
# logs/verify.txt が PASS でなければ測らない (止める条件).
# 回す前の負荷は load average と CPU 使用率の合計だけを残す (CLAUDE.md「記録に残さないもの」)
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$HERE/lib.sh"
W="$ROOT/runs/unmove_bench"
ROUNDS=5
VARIANTS=(cand sieve visit degw gen)
NUMA=(numactl --cpunodebind=0 --membind=0)
if [ -e "$HERE/logs/timing.tsv" ]; then
    echo "logs/timing.tsv が残っている. 前回と混ざるので, 退避してから起動すること" >&2
    exit 2
fi
if ! grep -q '食い違い 0 局面 => PASS' "$HERE/logs/verify.txt"; then
    echo "!!! 一致の検査が PASS でないので測らない (止める条件)" >&2
    exit 1
fi
exec > >(tee "$HERE/logs/console.log") 2>&1
echo "=== unmove_bench 計時 開始 $(date --iso-8601=seconds) ==="
echo "unmove.so sha256 $(sha256sum "$W/build/unmove.so" | cut -c1-12) / bench sha256 $(sha256sum "$W/build/bench" | cut -c1-12)"
awk '{print "load average:", $1 ",", $2 ",", $3}' /proc/loadavg
vmstat 1 2 | awk 'NR == 2 {for (i = 1; i <= NF; i++) if ($i == "id") c = i}
                  END {print "CPU 使用率 (全 CPU, 1秒):", 100 - $c "%"}'
FB0=$(awk '$1 == "thp_fault_fallback" {print $2}' /proc/vmstat)
freq_header > "$HERE/logs/freq.log"
sample_hw >> "$HERE/logs/freq.log" 2>/dev/null &
SPID=$!
trap 'kill "$SPID" 2>/dev/null || true' EXIT
printf 'version\tround\tsample\tn\tns_per_q\tout_per_q\n' > "$HERE/logs/timing.tsv"
for r in $(seq 1 "$ROUNDS"); do
    for i in 0 1 2 3 4; do
        v="${VARIANTS[$(( (i + r - 1) % 5 ))]}"
        echo "--- r${r} $v ($(date +%H:%M:%S)) ---"
        "${NUMA[@]}" "$W/build/bench" time "$W/build/unmove.so" "$W" "$v" "$r" | tee -a "$HERE/logs/timing.tsv"
    done
done
FB1=$(awk '$1 == "thp_fault_fallback" {print $2}' /proc/vmstat)
echo "thp_fault_fallback の前後差: $((FB1 - FB0))"
echo "=== unmove_bench 計時 完了 $(date --iso-8601=seconds) ==="
