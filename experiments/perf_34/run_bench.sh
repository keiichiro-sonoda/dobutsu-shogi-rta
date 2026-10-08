#!/bin/bash
# 実験 perf_34: 生成器だけを, キャッシュに乗る小さい集合の局面で回す (記録試行ではない)
#
#   run_bench.sh      (run_all.sh の最後に呼ばれる. dump の本が書き出したブロックを使う)
#
# 入力は2通り:
#   order   dump の本が書き出した, F1 の各ラウンドの入力と U_loop の各段のフロンティアの真ん中の
#           連続した 4,096 局面 (本物の展開の並びのまま)。ファイルごとに1ブロック
#   random  #34 本走の dat/ から固定シードで一様に抜いた 262,144 局面 (sample.py)。4,096 局面ずつのブロック
# 5周まわす. 周ごとに order と random, fwd と unmove の順を入れ替える. numactl でノード0に固定する.
# 出力は logs/bench.tsv (周, 入力, bench の1行)
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
W="$ROOT/runs/perf_34/bench"
BLOCKS="$ROOT/runs/perf_34/dump/blocks"
DAT34="$ROOT/runs/20261008-050345_34_unmove/dat"
NUMA=(numactl --cpunodebind=0 --membind=0)
[ -d "$BLOCKS" ] || { echo "dump の本のブロックが無い: $BLOCKS" >&2; exit 2; }
[ -d "$DAT34" ] || { echo "#34 本走の dat/ が無い: $DAT34" >&2; exit 2; }
if [ -e "$W" ]; then
    echo "前回の $W が残っている. 退避するか消してから起動すること" >&2
    exit 2
fi
mkdir -p "$W"
echo "=== ベンチ 開始 $(date --iso-8601=seconds) ==="
"$HERE/build_bench.sh" "$W"
python3 "$HERE/sample.py" "$DAT34" "$W" | tee "$HERE/logs/sample.txt"
cp "$BLOCKS/index.tsv" "$HERE/logs/blocks_index.tsv"
mapfile -t F1 < <(find "$BLOCKS" -name 'f1_*.bin' | LC_ALL=C sort)
mapfile -t UL < <(find "$BLOCKS" -name 'u_*.bin' | LC_ALL=C sort)
echo "ブロック: F1 ${#F1[@]} 個 / U_loop ${#UL[@]} 個"
OUT="$HERE/logs/bench.tsv"
printf 'rep\tinput\tmode\tfile\tn\tsec\tns_per_pos\touts_per_pos\tchecksum\n' > "$OUT"
for rep in 1 2 3 4 5; do
    order=(order random)
    modes=(fwd unmove)
    if [ $((rep % 2)) -eq 0 ]; then order=(random order); modes=(unmove fwd); fi
    for input in "${order[@]}"; do
        for mode in "${modes[@]}"; do
            if [ "$input" = order ]; then
                if [ "$mode" = fwd ]; then files=("${F1[@]}"); else files=("${UL[@]}"); fi
            else
                files=("$W/sample_$mode.bin")
            fi
            "${NUMA[@]}" "$W/bench" "$W/bench.so" "$mode" 4096 "${files[@]}" \
                | sed "s/^/$rep\t$input\t/" >> "$OUT"
        done
    done
    echo "周 $rep 完了 $(date --iso-8601=seconds)"
done
echo "=== ベンチ 完了 $(date --iso-8601=seconds) ==="
