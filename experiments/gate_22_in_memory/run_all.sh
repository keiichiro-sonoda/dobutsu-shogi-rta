#!/bin/bash
# 門番 #22: 3腕 × 6ブロック = 18本 (記録試行ではない). 進行は logs/console.log に残す
#
#   block1:  old   chunk whole
#   block2:  chunk whole old
#   block3:  whole old   chunk
#   block4:  old   whole chunk
#   block5:  whole chunk old
#   block6:  chunk old   whole
#
# 各腕は各位置 (1・2・3番目) に2回ずつ来る. ブロックの中で隣り合う前後の組
# (old→chunk, chunk→whole, whole→old, old→whole, whole→chunk, chunk→old) も2回ずつ.
# ブロックをまたぐ前後 (block1 の最後 → block2 の最初) は揃えていない.
#
# ⚠️ 1本あたり完走 3分半 ＋ 検査で, 18本で約75分かかる.
#    その間このマシンで他の計算を回さないこと
set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
mkdir -p "$HERE/logs"
if [ -e "$HERE/logs/console.log" ]; then
    echo "logs/console.log が残っている. 前回の門番と混ざるので, 退避してから起動すること" >&2
    exit 2
fi
exec > >(tee "$HERE/logs/console.log") 2>&1

BLOCKS=(
    "old chunk whole"
    "chunk whole old"
    "whole old chunk"
    "old whole chunk"
    "whole chunk old"
    "chunk old whole"
)
POS=(a b c)
echo "=== 門番 #22 開始 $(date --iso-8601=seconds) ==="
b=0
for block in "${BLOCKS[@]}"; do
    b=$((b + 1))
    p=0
    for arm in $block; do
        "$HERE/run_one.sh" "$arm" "b${b}${POS[$p]}_$arm"
        p=$((p + 1))
    done
done
echo "=== 全18本 完了 $(date --iso-8601=seconds) ==="
