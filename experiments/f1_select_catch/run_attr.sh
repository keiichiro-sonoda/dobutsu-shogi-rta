#!/bin/bash
# 束ごとの帰属 (実験 f1_select_catch。記録試行ではない)
#
#   run_attr.sh <腕…>
#
# experiments/bitboard_gen/run_attr.sh の写し. 違いは作業の置き場所と, 本ごとの間引きの記録を足したこと.
# 腕ごとに, -g の bench (build_bench.sh の g/animal_shogi.so. .text は -g なしと一致) を order の 74 ブロックで
# 1プロセス回し, perf record -e br_misp_retired.all_branches_pebs:upp -c 211 で予測ミスの標本を取る (3回).
# 周期は bitboard_gen と同じ 211. bitboard_gen ではカーネルの標本の上限 (kernel.perf_event_max_sample_rate) に当たって
# 間引かれ, 1本 3,000〜3,900 個になった. 同じ周期で回し, 束は標本の割合だけで読む (1局面あたりは
# 割合 × ベンチの予測ミス. summary.py). 本ごとに perf report --stats の THROTTLE の回数と標本の数を logs/attr_stats.txt に残す.
# 標本は perf_branch_34 の aggregate.py pebs で分岐の番地 → ソース行に寄せ, logs/attr_<腕>_r<回>.tsv に残す.
# perf.data は runs/ に置いたまま
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
W="$ROOT/runs/f1_select_catch"
BLOCKS="$ROOT/runs/perf_34/dump/blocks"
NUMA=(numactl --cpunodebind=0 --membind=0)
PERIOD=211
mapfile -t F1 < <(find "$BLOCKS" -name 'f1_*.bin' | LC_ALL=C sort)
ST="$HERE/logs/attr_stats.txt"
echo "# perf report --stats の THROTTLE / UNTHROTTLE と標本の数 (周期 $PERIOD, kernel.perf_event_max_sample_rate = $(cat /proc/sys/kernel/perf_event_max_sample_rate)). 行が無いものは 0" > "$ST"
echo "=== 開始 attr $(date --iso-8601=seconds) ==="
for r in 1 2 3; do
    for a in "$@"; do
        G="$W/bench_$a/g/animal_shogi.so"
        D="$W/attr_${a}_r$r.data"
        perf record -q -o "$D" -e br_misp_retired.all_branches_pebs:upp -c "$PERIOD" -- \
            "${NUMA[@]}" "$W/bench_$a/bench" "$G" fwd 4096 "${F1[@]}" > /dev/null 2> /dev/null
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
