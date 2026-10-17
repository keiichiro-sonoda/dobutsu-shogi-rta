#!/bin/bash
# ベンチ (実験 mirror1_keep。記録試行ではない)
#
#   run_bench.sh <腕…>      (一致の検査を通った腕だけを渡す. base は必ず含める)
#
# 腕ごとに build_bench.sh で作った bench.so の benchUnmove (逆向きの生成器 ＋ 候補ごとの rankOf) を,
# perf stat -e cycles:u,instructions:u,br_inst_retired.all_branches:u,br_misp_retired.all_branches:u の下で回す.
# 入力 (どれも perf_34 が runs/ に残したもの. #36 は後退解析の並びが #34・#35 と同じなので, そのまま使える):
#   order   U_loop の各段の真ん中の連続した 4,096 局面 (perf_34 の dump の本の u_*.bin. ファイルごとに1プロセス)
#   random  #34 本走の dat/ から一様に抜いた 262,144 局面 (perf_34 の sample_unmove.bin)
# 7周. 周ごとに腕の順を1つずつずらす. 腕ごとに, 1局面だけのファイルで固定の分を5回測る.
# numactl でノード0に固定する. 出力は logs/bench.tsv と logs/bench_overhead.tsv.
# ベンチ本体が出す1局面あたりの候補の数 (cand) と番号の和 (sum. 候補の多重集合が同じなら腕によらず同じ) も残す
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
W="$ROOT/runs/mirror1_keep"
BLOCKS="$ROOT/runs/perf_34/dump/blocks"
SAMPLE="$ROOT/runs/perf_34/bench/sample_unmove.bin"
NUMA=(numactl --cpunodebind=0 --membind=0)
EVENTS=cycles:u,instructions:u,br_inst_retired.all_branches:u,br_misp_retired.all_branches:u
ARMS=("$@")
[ "${#ARMS[@]}" -ge 1 ] || { echo "腕を渡すこと" >&2; exit 2; }
[ -d "$BLOCKS" ] || { echo "入力が無い: $BLOCKS" >&2; exit 2; }
[ -f "$SAMPLE" ] || { echo "入力が無い: $SAMPLE" >&2; exit 2; }
head -c 8 "$SAMPLE" > "$W/one_unmove.bin"
mapfile -t UL < <(find "$BLOCKS" -name 'u_*.bin' | LC_ALL=C sort)
[ "${#UL[@]}" = 174 ] || { echo "u_*.bin が 174 個でない: ${#UL[@]}" >&2; exit 2; }

stat_one() {  # stat_one <出力> <周> <腕> <入力> <ファイル>
    local n=$(( $(stat -c %s "$5") / 8 ))
    [ "$n" -gt 0 ] || return 0
    perf stat -x, -o "$W/pstat.csv" -e "$EVENTS" -- \
        "${NUMA[@]}" "$W/bench_$3/bench" "$W/bench_$3/bench.so" unmove 4096 "$5" > "$W/bench_out.txt"
    printf '%s\t%s\t%s\t%s\t%s' "$2" "$3" "$4" "$(basename "$5")" "$n" >> "$1"
    for e in cycles:u instructions:u br_inst_retired.all_branches:u br_misp_retired.all_branches:u; do
        printf '\t%s' "$(awk -F, -v e="$e" '$3 == e {print $1}' "$W/pstat.csv")" >> "$1"
    done
    printf '\t%s' "$(awk -F, '$3 ~ /:u$/ {if (m == "" || $5 < m) m = $5} END {print m}' "$W/pstat.csv")" >> "$1"
    printf '\t%s\t%s\n' "$(cut -f6 "$W/bench_out.txt")" "$(cut -f7 "$W/bench_out.txt")" >> "$1"
}
HDR='rep\tarm\tinput\tfile\tn\tcycles_u\tinstructions_u\tbr_inst_u\tbr_misp_u\tmin_pct\tcand\tsum\n'
OH="$HERE/logs/bench_overhead.tsv"
OUT="$HERE/logs/bench.tsv"
# shellcheck disable=SC2059
printf "$HDR" > "$OH"
# shellcheck disable=SC2059
printf "$HDR" > "$OUT"
echo "=== 開始 bench $(date --iso-8601=seconds) ==="
for a in "${ARMS[@]}"; do
    for rep in 1 2 3 4 5; do stat_one "$OH" "$rep" "$a" one "$W/one_unmove.bin"; done
done
for rep in 1 2 3 4 5 6 7; do
    k=${#ARMS[@]}
    for j in $(seq 0 $((k - 1))); do
        a=${ARMS[$(( (j + rep - 1) % k ))]}
        for f in "${UL[@]}"; do stat_one "$OUT" "$rep" "$a" order "$f"; done
        stat_one "$OUT" "$rep" "$a" random "$SAMPLE"
    done
    echo "周 $rep 完了 $(date --iso-8601=seconds)"
done
echo "=== 完了 bench $(date --iso-8601=seconds) ==="
