#!/bin/bash
# 実験 perf_branch_34 (副): 生成器だけのベンチで, 予測ミスを数える (記録試行ではない)
#
#   run_bench.sh      → logs/bench_branch.tsv, logs/bench_overhead.tsv, logs/split.txt, logs/split_index.tsv
#
# experiments/perf_34 のベンチ (build_bench.sh・bench.c・glue.c. 生成器と番号の計算だけ) を
# perf stat -e cycles:u,instructions:u,br_misp_retired.all_branches:u,br_inst_retired.all_branches:u の下で回す.
# 入力 (どれも perf_34 が runs/ に残したもの):
#   order   F1 の各ラウンド・U_loop の各段の真ん中の連続した 4,096 局面 (並びは本物のまま. ファイルごとに1プロセス)
#   random  #34 本走の dat/ から一様に抜いた 262,144 局面
#   catch / other   order の F1 のブロックを, キャッチ局面だけ / それ以外だけに分けたもの (split.py. 並びは保つ)
# 3周. 1局面だけのファイルで固定の分を5回測る. numactl でノード0に固定する.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
W="$ROOT/runs/perf_branch_34/bench"
BLOCKS="$ROOT/runs/perf_34/dump/blocks"
SAMPLE="$ROOT/runs/perf_34/bench"
NUMA=(numactl --cpunodebind=0 --membind=0)
EVENTS=cycles:u,instructions:u,br_misp_retired.all_branches:u,br_inst_retired.all_branches:u
[ -d "$BLOCKS" ] || { echo "perf_34 のブロックが無い: $BLOCKS" >&2; exit 2; }
if [ -e "$W" ]; then
    echo "前回の $W が残っている. 退避するか消してから起動すること" >&2
    exit 2
fi
mkdir -p "$W"
echo "=== 開始 bench $(date --iso-8601=seconds) ==="
"$ROOT/experiments/perf_34/build_bench.sh" "$W"
cp "$SAMPLE/sample_fwd.bin" "$SAMPLE/sample_unmove.bin" "$W/"
head -c 8 "$W/sample_fwd.bin" > "$W/one_fwd.bin"
head -c 8 "$W/sample_unmove.bin" > "$W/one_unmove.bin"
python3 "$HERE/split.py" "$W/bench.so" "$BLOCKS" "$W/split" | tee "$HERE/logs/split.txt"
cp "$W/split/split_index.tsv" "$HERE/logs/split_index.tsv"
cp "$BLOCKS/index.tsv" "$HERE/logs/blocks_index.tsv"
mapfile -t F1 < <(find "$BLOCKS" -name 'f1_*.bin' | LC_ALL=C sort)
mapfile -t UL < <(find "$BLOCKS" -name 'u_*.bin' | LC_ALL=C sort)

stat_one() {  # stat_one <出力> <周> <入力> <mode> <ファイル>
    local n=$(( $(stat -c %s "$5") / 8 ))
    [ "$n" -gt 0 ] || return 0
    perf stat -x, -o "$W/pstat.csv" -e "$EVENTS" -- \
        "${NUMA[@]}" "$W/bench" "$W/bench.so" "$4" 4096 "$5" > /dev/null
    printf '%s\t%s\t%s\t%s\t%s' "$2" "$3" "$4" "$(basename "$5")" "$n" >> "$1"
    for e in cycles:u instructions:u br_misp_retired.all_branches:u br_inst_retired.all_branches:u; do
        printf '\t%s' "$(awk -F, -v e="$e" '$3 == e {print $1}' "$W/pstat.csv")" >> "$1"
    done
    printf '\n' >> "$1"
}
HDR='rep\tinput\tmode\tfile\tn\tcycles_u\tinstructions_u\tbr_misp_u\tbr_inst_u\n'
OH="$HERE/logs/bench_overhead.tsv"
# shellcheck disable=SC2059
printf "$HDR" > "$OH"
for rep in 1 2 3 4 5; do
    stat_one "$OH" "$rep" one fwd "$W/one_fwd.bin"
    stat_one "$OH" "$rep" one unmove "$W/one_unmove.bin"
done
OUT="$HERE/logs/bench_branch.tsv"
# shellcheck disable=SC2059
printf "$HDR" > "$OUT"
for rep in 1 2 3; do
    for f in "${F1[@]}"; do stat_one "$OUT" "$rep" order fwd "$f"; done
    for f in "${UL[@]}"; do stat_one "$OUT" "$rep" order unmove "$f"; done
    for f in "${F1[@]}"; do
        b=$(basename "$f")
        stat_one "$OUT" "$rep" catch fwd "$W/split/catch/$b"
        stat_one "$OUT" "$rep" other fwd "$W/split/other/$b"
    done
    stat_one "$OUT" "$rep" random fwd "$W/sample_fwd.bin"
    stat_one "$OUT" "$rep" random unmove "$W/sample_unmove.bin"
    echo "周 $rep 完了 $(date --iso-8601=seconds)"
done
echo "=== 完了 bench $(date --iso-8601=seconds) ==="
