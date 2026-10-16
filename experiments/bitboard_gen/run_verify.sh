#!/bin/bash
# 一致の検査 (実験 bitboard_gen。記録試行ではない). 計時はしない
#
#   run_verify.sh <base の animal_shogi.so> <bb_nibble の .so> <bb_pext の .so>
#
# 入力は #34 本走の dat/ の全 213 ファイル (到達可能な全 246,803,167 局面. 読むだけ).
# verify.c で, 腕ごとに base と (a) 戻り値 (b) 正のときの後続の列 (並びまで) (c) *non_catch を全局面で比べる.
# 結果は logs/verify_<腕>.txt (不一致は最初の 20 局面まで). 1局面でも外れた腕は計時しない (run_bench.sh が見る)
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
DAT="$ROOT/runs/20261008-050345_34_unmove/dat"
W="$ROOT/runs/bitboard_gen"
NUMA=(numactl --cpunodebind=0 --membind=0)
[ -d "$DAT" ] || { echo "#34 本走の dat/ が無い: $DAT" >&2; exit 2; }
mkdir -p "$W"
gcc -O2 -Wall -Wextra "$HERE/verify.c" -o "$W/verify" -ldl
mapfile -t FILES < <(find "$DAT" -name '*.bin' | LC_ALL=C sort)
echo "入力: #34 本走の dat/ の ${#FILES[@]} ファイル"
for i in 2 3; do
    arm=$( [ "$i" = 2 ] && echo bb_nibble || echo bb_pext )
    echo "=== 開始 verify_$arm $(date --iso-8601=seconds) ==="
    set +e
    "${NUMA[@]}" "$W/verify" "$1" "${!i}" "${FILES[@]}" > "$HERE/logs/verify_$arm.txt"
    rc=$?
    set -e
    tail -1 "$HERE/logs/verify_$arm.txt"
    echo "verify_$arm exit=$rc"
    echo "=== 完了 verify_$arm $(date --iso-8601=seconds) ==="
done
