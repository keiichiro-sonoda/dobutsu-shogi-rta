#!/bin/bash
# 後退解析の門番: old new new old を2回 = 8本 (記録試行ではない)
#
# 入力は runs/g19_fixture_bin/dat (impl/19 の全探索の出力そのもの).
# 出力は毎本 #19 本走の dat/ と照合する (run_retreat.sh).
#
# ⚠️ 約25分かかる. その間このマシンで他の計算を回さないこと
set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
for i in 1 2; do
    for pos in a b c d; do
        case "$pos" in a|d) arm=old ;; b|c) arm=new ;; esac
        "$HERE/run_retreat.sh" "$arm" "r${i}${pos}_$arm"
    done
done
echo "=== 後退解析 全8本 完了 $(date --iso-8601=seconds) ==="
