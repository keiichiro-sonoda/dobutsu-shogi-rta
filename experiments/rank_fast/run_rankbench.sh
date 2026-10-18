#!/bin/bash
# rankOf だけのベンチを回す (実験 rank_fast。記録試行ではない)
#
#   run_rankbench.sh <出力.tsv> <腕>=<build_bench.sh の出力先> ...
#
# 入力は2つ (どちらも runs/ に残っているもの. 並びは本物のまま):
#   fwd     F1 の各ラウンドの真ん中の連続した 4,096 局面 (perf_34 の dump の本の f1_*.bin 74 個) から作った後続
#   unmove  U_loop の各段の真ん中の連続した 4,096 局面 (同じく u_*.bin 174 個) から作った前任の候補
# 回し方は none (列を作るだけ. 固定の分) と thr・chain・small (rank_bench.c). 呼び出しの数は 1 億.
# 7周. 周ごとに, 腕の順と回し方の順 (thr・chain・small) を1つずつずらす. 腕ごと・入力ごとに none を先に回す.
# perf stat -e cycles:u,instructions:u,mem_load_uops_retired.l1_miss:u,mem_load_uops_retired.l2_hit:u.
# numactl でノード0に固定する
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
OUT="${1:?出力を指定すること}"
shift
BLOCKS="$ROOT/runs/perf_34/dump/blocks"
NUMA=(numactl --cpunodebind=0 --membind=0)
EVENTS=cycles:u,instructions:u,mem_load_uops_retired.l1_miss:u,mem_load_uops_retired.l2_hit:u
CALLS=100000000
ARMS=("$@")
[ "${#ARMS[@]}" -ge 1 ] || { echo "腕を渡すこと" >&2; exit 2; }
[ -d "$BLOCKS" ] || { echo "入力が無い: $BLOCKS" >&2; exit 2; }
mapfile -t FWD < <(find "$BLOCKS" -name 'f1_*.bin' | LC_ALL=C sort)
mapfile -t UNM < <(find "$BLOCKS" -name 'u_*.bin' | LC_ALL=C sort)
[ "${#FWD[@]}" = 74 ] && [ "${#UNM[@]}" = 174 ] || { echo "入力の数が違う (${#FWD[@]} / ${#UNM[@]})" >&2; exit 2; }
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

one() {  # one <周> <腕> <ビルド先> <入力> <回し方>
    local files
    if [ "$4" = fwd ]; then files=("${FWD[@]}"); else files=("${UNM[@]}"); fi
    perf stat -x, -o "$TMP/p.csv" -e "$EVENTS" -- \
        "${NUMA[@]}" "$3/rank_bench" "$3/rank.so" "$4" "$5" "$CALLS" "${files[@]}" > "$TMP/o.txt"
    printf '%s\t%s\t%s' "$1" "$2" "$(cat "$TMP/o.txt")" >> "$OUT"
    for e in cycles:u instructions:u mem_load_uops_retired.l1_miss:u mem_load_uops_retired.l2_hit:u; do
        printf '\t%s' "$(awk -F, -v e="$e" '$3 == e {print $1}' "$TMP/p.csv")" >> "$OUT"
    done
    printf '\t%s\n' "$(awk -F, '$3 ~ /:u$/ {if (m == "" || $5 < m) m = $5} END {print m}' "$TMP/p.csv")" >> "$OUT"
}
printf 'rep\tarm\tinput\tmode\tnpos\tlen\tset\treps\tcalls\tsum\tcycles_u\tinstructions_u\tl1_miss_u\tl2_hit_u\tmin_pct\n' > "$OUT"
MODES=(thr chain small)
echo "=== 開始 rankbench $(date --iso-8601=seconds) ==="
for rep in 1 2 3 4 5 6 7; do
    k=${#ARMS[@]}
    for j in $(seq 0 $((k - 1))); do
        spec=${ARMS[$(( (j + rep - 1) % k ))]}
        a=${spec%%=*}
        d=${spec#*=}
        for in in fwd unmove; do
            one "$rep" "$a" "$d" "$in" none
            for i in 0 1 2; do
                one "$rep" "$a" "$d" "$in" "${MODES[$(( (i + rep - 1) % 3 ))]}"
            done
        done
    done
    echo "周 $rep 完了 $(date --iso-8601=seconds)"
done
echo "=== 完了 rankbench $(date --iso-8601=seconds) ==="
