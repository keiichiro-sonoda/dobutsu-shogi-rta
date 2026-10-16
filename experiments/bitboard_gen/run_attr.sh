#!/bin/bash
# 束ごとの帰属 (実験 bitboard_gen。記録試行ではない)
#
#   run_attr.sh <腕…>
#
# 腕ごとに, -g の bench (build_bench.sh の g/animal_shogi.so. .text は -g なしと一致) を order の 74 ブロックで
# 1プロセス回し, perf record -e br_misp_retired.all_branches_pebs:upp -c 211 で予測ミスの標本を取る (3回).
# 標本は perf_branch_34 の aggregate.py pebs で分岐の番地 → ソース行に寄せ, logs/attr_<腕>_r<回>.tsv に残す.
# perf.data は runs/ に置いたまま. 周期 211 (素数) は, ベンチ1プロセスの予測ミス (約 600 万) から数万の標本を取るため
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
W="$ROOT/runs/bitboard_gen"
BLOCKS="$ROOT/runs/perf_34/dump/blocks"
NUMA=(numactl --cpunodebind=0 --membind=0)
mapfile -t F1 < <(find "$BLOCKS" -name 'f1_*.bin' | LC_ALL=C sort)
echo "=== 開始 attr $(date --iso-8601=seconds) ==="
for r in 1 2 3; do
    for a in "$@"; do
        G="$W/bench_$a/g/animal_shogi.so"
        perf record -q -o "$W/attr_${a}_r$r.data" -e br_misp_retired.all_branches_pebs:upp -c 211 -- \
            "${NUMA[@]}" "$W/bench_$a/bench" "$G" fwd 4096 "${F1[@]}" > /dev/null 2> /dev/null
        perf script -i "$W/attr_${a}_r$r.data" -F ip,sym,symoff,dso 2> /dev/null \
            | python3 "$ROOT/experiments/perf_branch_34/aggregate.py" pebs "$G" > "$HERE/logs/attr_${a}_r$r.tsv"
        echo "attr $a r$r: $(head -1 "$HERE/logs/attr_${a}_r$r.tsv")"
    done
done
echo "=== 完了 attr $(date --iso-8601=seconds) ==="
