#!/bin/bash
# 一致の検査と抜き出し (実験 gen_bench。記録試行ではない). 計時はしない
#
#   run_verify.sh
#
# 4つの版を build.sh で .so にし, 全局面 (#25 本走の dat/, 246,803,167) で次を見る:
#   - B:  invBoard の出力が1ビットも違わない / 生成器の戻り値と後続の列が一致する
#   - A:  nextBoardCatchFirst の戻り値が一致し, 正のときは後続の列が順番まで一致する
#   - AB: 同上
# どれかが1局面でも外れたら, その版は計時しない (run_time.sh が logs/verify.txt を見る).
# 最後に, いまの生成器の戻り値で種類を決めて 1,000万局面を固定シードで抜き出す.
# dat/ と抜き出した局面は git に入れない (runs/gen_bench/ に置く)
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
DAT="${DAT:-$ROOT/runs/20260927-161144_25_huge_retreat/dat}"
W="$ROOT/runs/gen_bench"
SEED=20260928
N_SAMPLE=10000000
mkdir -p "$W/so" "$W/sample" "$HERE/logs"
for v in base B A AB; do "$HERE/build_so.sh" "$v" "$W/so/$v"; done | tee "$HERE/logs/build.txt"
gcc -O2 -Wall -Wextra -o "$W/bench" "$HERE/bench.c" -ldl
B="$W/bench"
{
    echo "# 全局面での一致の検査 (入力は #25 本走の dat/). 0 以外で終わった行の版は計時しない"
    rc=0; "$B" verify-inv "$DAT" "$W/so/base/animal_shogi.so" "$W/so/B/animal_shogi.so" || rc=$?; echo "exit=$rc B invBoard"
    rc=0; "$B" verify-gen "$DAT" "$W/so/base/animal_shogi.so" "$W/so/B/animal_shogi.so" nextBoardInvNormal || rc=$?; echo "exit=$rc B"
    rc=0; "$B" verify-gen "$DAT" "$W/so/base/animal_shogi.so" "$W/so/A/animal_shogi.so" nextBoardCatchFirst || rc=$?; echo "exit=$rc A"
    rc=0; "$B" verify-gen "$DAT" "$W/so/base/animal_shogi.so" "$W/so/AB/animal_shogi.so" nextBoardCatchFirst || rc=$?; echo "exit=$rc AB"
} 2>&1 | tee "$HERE/logs/verify.txt"
"$B" sample "$DAT" "$W/so/base/animal_shogi.so" "$W/sample" "$N_SAMPLE" "$SEED" 2>&1 | tee "$HERE/logs/sample.txt"
