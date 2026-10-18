#!/bin/bash
# 段2の文脈の中のベンチ (実験 rank_fast。記録試行ではない)
#
#   run_bench2.sh <腕>=<build_bench.sh の出力先> ...      (一致の検査を通った腕だけを渡す. base は必ず含める)
#
# 腕ごとの bench.so (perf_34 の glue.c. 取り込む animal_shogi.c が腕のもの) を, perf_34 の bench.c で回す:
#   fwd     benchFwd (全探索の生成器 ＋ 後続ごとの rankOf). 入力は F1 の各ラウンドの真ん中の 4,096 局面 (f1_*.bin 74 個)
#   unmove  benchUnmove (逆向きの生成器 ＋ 候補ごとの rankOf). 入力は U_loop の各段の真ん中の 4,096 局面 (u_*.bin 174 個)
# どちらも order の入力で, ファイルごとに1プロセス (bitboard_gen・f1_select_catch・unmove_gen と同じ回し方).
# perf stat -e cycles:u,instructions:u,br_inst_retired.all_branches:u,br_misp_retired.all_branches:u.
# 7周. 周ごとに腕の順を1つずつずらす. 腕ごとに, 1局面だけのファイルで固定の分を5回ずつ測る.
# numactl でノード0に固定する. 出力は logs/bench2.tsv と logs/bench2_overhead.tsv
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
W="$ROOT/runs/rank_fast/s2"
BLOCKS="$ROOT/runs/perf_34/dump/blocks"
NUMA=(numactl --cpunodebind=0 --membind=0)
EVENTS=cycles:u,instructions:u,br_inst_retired.all_branches:u,br_misp_retired.all_branches:u
ARMS=("$@")
[ "${#ARMS[@]}" -ge 1 ] || { echo "腕を渡すこと" >&2; exit 2; }
mkdir -p "$W"
for f in sample_fwd sample_unmove; do
    [ -f "$ROOT/runs/perf_34/bench/$f.bin" ] || { echo "入力が無い: $f" >&2; exit 2; }
done
head -c 8 "$ROOT/runs/perf_34/bench/sample_fwd.bin" > "$W/one_fwd.bin"
head -c 8 "$ROOT/runs/perf_34/bench/sample_unmove.bin" > "$W/one_unmove.bin"
mapfile -t FWD < <(find "$BLOCKS" -name 'f1_*.bin' | LC_ALL=C sort)
mapfile -t UNM < <(find "$BLOCKS" -name 'u_*.bin' | LC_ALL=C sort)
[ "${#FWD[@]}" = 74 ] && [ "${#UNM[@]}" = 174 ] || { echo "入力の数が違う (${#FWD[@]} / ${#UNM[@]})" >&2; exit 2; }
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

stat_one() {  # stat_one <出力> <周> <腕> <ビルド先> <fwd|unmove> <入力の名前> <ファイル>
    local n=$(( $(stat -c %s "$7") / 8 ))
    [ "$n" -gt 0 ] || return 0
    perf stat -x, -o "$TMP/p.csv" -e "$EVENTS" -- \
        "${NUMA[@]}" "$4/bench" "$4/bench.so" "$5" 4096 "$7" > "$TMP/o.txt"
    printf '%s\t%s\t%s\t%s\t%s\t%s' "$2" "$3" "$5" "$6" "$(basename "$7")" "$n" >> "$1"
    for e in cycles:u instructions:u br_inst_retired.all_branches:u br_misp_retired.all_branches:u; do
        printf '\t%s' "$(awk -F, -v e="$e" '$3 == e {print $1}' "$TMP/p.csv")" >> "$1"
    done
    printf '\t%s' "$(awk -F, '$3 ~ /:u$/ {if (m == "" || $5 < m) m = $5} END {print m}' "$TMP/p.csv")" >> "$1"
    printf '\t%s\t%s\n' "$(cut -f6 "$TMP/o.txt")" "$(cut -f7 "$TMP/o.txt")" >> "$1"
}
HDR='rep\tarm\tbench\tinput\tfile\tn\tcycles_u\tinstructions_u\tbr_inst_u\tbr_misp_u\tmin_pct\touts\tsum\n'
OH="$HERE/logs/bench2_overhead.tsv"
OUT="$HERE/logs/bench2.tsv"
# shellcheck disable=SC2059
printf "$HDR" > "$OH"
# shellcheck disable=SC2059
printf "$HDR" > "$OUT"
echo "=== 開始 bench2 $(date --iso-8601=seconds) ==="
for spec in "${ARMS[@]}"; do
    for rep in 1 2 3 4 5; do
        stat_one "$OH" "$rep" "${spec%%=*}" "${spec#*=}" fwd one "$W/one_fwd.bin"
        stat_one "$OH" "$rep" "${spec%%=*}" "${spec#*=}" unmove one "$W/one_unmove.bin"
    done
done
for rep in 1 2 3 4 5 6 7; do
    k=${#ARMS[@]}
    for j in $(seq 0 $((k - 1))); do
        spec=${ARMS[$(( (j + rep - 1) % k ))]}
        a=${spec%%=*}
        d=${spec#*=}
        for f in "${FWD[@]}"; do stat_one "$OUT" "$rep" "$a" "$d" fwd order "$f"; done
        for f in "${UNM[@]}"; do stat_one "$OUT" "$rep" "$a" "$d" unmove order "$f"; done
    done
    echo "周 $rep 完了 $(date --iso-8601=seconds)"
done
echo "=== 完了 bench2 $(date --iso-8601=seconds) ==="
