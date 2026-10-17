#!/bin/bash
# 束ごとの帰属 (実験 unmove_gen。記録試行ではない)
#
#   run_attr.sh <腕…>
#
# 腕ごとに, -g の bench (build_bench.sh の g/animal_shogi.so. .text は -g なしと一致) を order の 174 ブロックで
# 1プロセス回し, perf record -e br_misp_retired.all_branches_pebs:upp -c 10007 で予測ミスの標本を取る (3回).
# 174 ブロックの並びを4回続けて渡す (1回だと base で標本が 2,600 個ほどにしかならないため).
# 周期 10,007 (素数): base の予測ミスは毎秒約 5,600 万回なので, 標本は毎秒 5,600 個ほど.
# bitboard_gen は周期 211 でカーネルの標本の上限 (kernel.perf_event_max_sample_rate) に当たって間引かれたので,
# 本ごとに perf report --stats の THROTTLE の回数を logs/attr_stats.txt に残す (0 であることを見る).
# 標本は perf_branch_34 の aggregate.py pebs で分岐の番地 → ソース行に寄せ, logs/attr_<腕>_r<回>.tsv に残す.
# perf.data は runs/ に置いたまま
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
W="$ROOT/runs/unmove_gen"
BLOCKS="$ROOT/runs/perf_34/dump/blocks"
NUMA=(numactl --cpunodebind=0 --membind=0)
PERIOD=10007
mapfile -t UL < <(find "$BLOCKS" -name 'u_*.bin' | LC_ALL=C sort)
ST="$HERE/logs/attr_stats.txt"
echo "# perf report --stats の THROTTLE / UNTHROTTLE と標本の数 (周期 $PERIOD, kernel.perf_event_max_sample_rate = $(cat /proc/sys/kernel/perf_event_max_sample_rate)). 行が無いものは 0" > "$ST"
echo "=== 開始 attr $(date --iso-8601=seconds) ==="
for r in 1 2 3; do
    for a in "$@"; do
        G="$W/bench_$a/g/animal_shogi.so"
        D="$W/attr_${a}_r$r.data"
        perf record -q -o "$D" -e br_misp_retired.all_branches_pebs:upp -c "$PERIOD" -- \
            "${NUMA[@]}" "$W/bench_$a/bench" "$G" unmove 4096 "${UL[@]}" "${UL[@]}" "${UL[@]}" "${UL[@]}" \
            > /dev/null 2> /dev/null
        perf script -i "$D" -F ip,sym,symoff,dso 2> /dev/null \
            | python3 "$ROOT/experiments/perf_branch_34/aggregate.py" pebs "$G" > "$HERE/logs/attr_${a}_r$r.tsv"
        {
            printf '%s r%s\t' "$a" "$r"
            perf report -i "$D" --stats 2> /dev/null \
                | awk 'BEGIN {t = 0; u = 0; s = 0}
                       $1 == "THROTTLE" && $2 == "events:" {t = $3}
                       $1 == "UNTHROTTLE" && $2 == "events:" {u = $3}
                       $1 == "SAMPLE" && $2 == "events:" && s == 0 {s = $3}
                       END {printf "THROTTLE %d\tUNTHROTTLE %d\tSAMPLE %d\n", t, u, s}'
        } >> "$ST"
        echo "attr $a r$r: $(head -1 "$HERE/logs/attr_${a}_r$r.tsv")"
    done
done
echo "=== 完了 attr $(date --iso-8601=seconds) ==="
