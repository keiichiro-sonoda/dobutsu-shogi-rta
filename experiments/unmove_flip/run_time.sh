#!/bin/bash
# 生成器だけの計時 (実験 unmove_flip。記録試行ではない). run_verify.sh のあとに回す
#
#   run_time.sh
#
# 6つの版 (pcand / psieve / pvisit = 絞った版の 1〜3 段階, fcand / fsieve / fvisit = 反転を1回にした版の 1〜3 段階) を
# 1本ずつ別のプロセスで測る (.so は1つだけ開く. RTLD_LOCAL). 5周まわし, 周ごとに順番を1つずつずらす.
# どの本も numactl でノード0に固定する. 版ごとに unknown / try / expand を1周温めてから1周測る (unmove_bench と同じ形).
# 一致の検査が PASS でなければ測らない (gate.sh). 回す前に巨大ページに使える空きを logs/free.txt に残し, ノード0 が 12 GiB に満たなければ止める
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$HERE/lib.sh"
# shellcheck source-path=SCRIPTDIR source=gate.sh
source "$HERE/gate.sh"
W="$ROOT/runs/unmove_flip"
ROUNDS=5
VARIANTS=(pcand psieve pvisit fcand fsieve fvisit)
NUMA=(numactl --cpunodebind=0 --membind=0)
if [ -e "$HERE/logs/timing.tsv" ]; then
    echo "logs/timing.tsv が残っている. 退避してから起動すること" >&2
    exit 2
fi
check_verify "$HERE"
if ! free_snapshot "$HERE/logs/free.txt" "生成器の計時の前" 12; then
    echo "!!! ノード0の巨大ページに使える空きが足りない. キャッシュを落としてから起動し直すこと (logs/free.txt)" >&2
    exit 1
fi
exec > >(tee "$HERE/logs/console_time.log") 2>&1
echo "=== unmove_flip 生成器の計時 開始 $(date --iso-8601=seconds) ==="
echo "flip.so sha256 $(sha256sum "$W/build/flip.so" | cut -c1-12) / bench sha256 $(sha256sum "$W/build/bench" | cut -c1-12)"
awk '{print "load average:", $1 ",", $2 ",", $3}' /proc/loadavg
vmstat 1 2 | awk 'NR == 2 {for (i = 1; i <= NF; i++) if ($i == "id") c = i}
                  END {print "CPU 使用率 (全 CPU, 1秒):", 100 - $c "%"}'
echo "先読み: 絞った版・反転を1回にした版とも, 候補のランクで cls の行を, 残った前任で状態の行を取り寄せる (unmove_bench と同じ)"
echo "THP enabled: $(cat /sys/kernel/mm/transparent_hugepage/enabled)"
FB0=$(awk '$1 == "thp_fault_fallback" {print $2}' /proc/vmstat)
freq_header > "$HERE/logs/time_freq.log"
sample_hw >> "$HERE/logs/time_freq.log" 2>/dev/null &
SPID=$!
trap 'kill "$SPID" 2>/dev/null || true' EXIT
printf 'version\tround\tsample\tn\tns_per_q\tout_per_q\n' > "$HERE/logs/timing.tsv"
for r in $(seq 1 "$ROUNDS"); do
    for i in 0 1 2 3 4 5; do
        v="${VARIANTS[$(( (i + r - 1) % 6 ))]}"
        echo "--- r${r} $v ($(date +%H:%M:%S)) ---"
        "${NUMA[@]}" "$W/build/bench" time "$W/build/flip.so" "$W" "$v" "$r" | tee -a "$HERE/logs/timing.tsv"
    done
done
FB1=$(awk '$1 == "thp_fault_fallback" {print $2}' /proc/vmstat)
echo "thp_fault_fallback の前後差: $((FB1 - FB0))"
echo "=== unmove_flip 生成器の計時 完了 $(date --iso-8601=seconds) ==="
