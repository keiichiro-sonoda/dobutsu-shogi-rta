#!/bin/bash
# 一致の検査 (実験 mirror1_keep。記録試行ではない). 計時はしない
#
#   run_verify.sh <base の animal_shogi.so> <mirror1 の .so> <mirror1_keep の .so>
#
# 入力は #36 本走の dat/ の全 213 ファイル (到達可能な全 246,803,167 局面. 読むだけ) を q とする.
# verify.c で, base と腕の unmoveCandidates を全局面で比べる:
#   mirror1       候補の数と, 候補を並べ替えた列 (多重集合) が同じ (multiset)
#   mirror1_keep  候補の数と, 候補の列 (並びまで) が同じ (seq)
# 結果は logs/verify_<腕>.txt (不一致は最初の 20 局面まで). 1局面でも外れた腕は計時しない (run_all.sh が見る)
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
DAT="$ROOT/runs/20261017-105455_36_bb_unmove/dat"
W="$ROOT/runs/mirror1_keep"
NUMA=(numactl --cpunodebind=0 --membind=0)
[ -d "$DAT" ] || { echo "#36 本走の dat/ が無い: $DAT" >&2; exit 2; }
mkdir -p "$W"
gcc -O2 -Wall -Wextra "$HERE/verify.c" -o "$W/verify" -ldl
mapfile -t FILES < <(find "$DAT" -name '*.bin' | LC_ALL=C sort)
echo "入力: #36 本走の dat/ の ${#FILES[@]} ファイル"
for spec in "mirror1 multiset $2" "mirror1_keep seq $3"; do
    read -r arm mode so <<< "$spec"
    echo "=== 開始 verify_$arm $(date --iso-8601=seconds) ==="
    set +e
    "${NUMA[@]}" "$W/verify" "$mode" "$1" "$so" "${FILES[@]}" > "$HERE/logs/verify_$arm.txt"
    rc=$?
    set -e
    tail -2 "$HERE/logs/verify_$arm.txt"
    echo "verify_$arm exit=$rc"
    echo "=== 完了 verify_$arm $(date --iso-8601=seconds) ==="
done
