#!/bin/bash
# 実験 perf_34: ベンチを perf stat の下で回し, サイクルと命令を数える (記録試行ではない. 回したあとで足した)
#
#   run_bench_cycles.sh     → logs/bench_cycles.tsv
#
# run_bench.sh の秒は1回の呼び出しが数十ミリ秒と短く, 周の間で 20% 以上振れた (周波数の立ち上がり).
# サイクルと命令は周波数に依らない. 数えるのはユーザー側 (:u) で, プロセス全体 (読み込み・温める周・測る周).
# 温める周と測る周は同じ仕事なので, 2 × 局面数で割った値を1局面あたりの近似にする (読み込みのぶん重めに出る).
# 入力は order (dump の本のブロック. ファイルごとに1プロセス) と random. 3周. numactl でノード0に固定する.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
W="$ROOT/runs/perf_34/bench"
BLOCKS="$ROOT/runs/perf_34/dump/blocks"
NUMA=(numactl --cpunodebind=0 --membind=0)
mapfile -t F1 < <(find "$BLOCKS" -name 'f1_*.bin' | LC_ALL=C sort)
mapfile -t UL < <(find "$BLOCKS" -name 'u_*.bin' | LC_ALL=C sort)
OUT="$HERE/logs/bench_cycles.tsv"
printf 'rep\tinput\tmode\tfile\tn\tcycles_u\tinstructions_u\n' > "$OUT"
one() {  # one <周> <入力> <mode> <ファイル>
    local n=$(( $(stat -c %s "$4") / 8 ))
    perf stat -x, -o "$W/pstat.csv" -e cycles:u,instructions:u -- \
        "${NUMA[@]}" "$W/bench" "$W/bench.so" "$3" 4096 "$4" > /dev/null
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$(basename "$4")" "$n" \
        "$(awk -F, '$3 == "cycles:u" {print $1}' "$W/pstat.csv")" \
        "$(awk -F, '$3 == "instructions:u" {print $1}' "$W/pstat.csv")" >> "$OUT"
}
# order はラウンド (段) ごとに1プロセス (summary.py がラウンドの局面数で重みを付ける)
for rep in 1 2 3; do
    for f in "${F1[@]}"; do one "$rep" order fwd "$f"; done
    for f in "${UL[@]}"; do one "$rep" order unmove "$f"; done
    one "$rep" random fwd "$W/sample_fwd.bin"
    one "$rep" random unmove "$W/sample_unmove.bin"
    echo "周 $rep 完了"
done
wc -l "$OUT"
