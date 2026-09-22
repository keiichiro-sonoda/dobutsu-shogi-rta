#!/bin/bash
# old と new を4本ずつ, old new new old を2回 = 8本 (記録試行ではない)
#
# ⚠️ 1本あたり後退解析 3〜4 分なので, 8本で約30分かかる.
#    その間このマシンで他の計算を回さないこと.
set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

for i in 1 2; do
    # 1組目だけ dat/ を残す. 腕どうしがバイト同一になることの照合に要る
    if [ "$i" -eq 1 ]; then
        "$HERE/run.sh" old "r${i}a_old" keep
        "$HERE/run.sh" new "r${i}b_new" keep
    else
        "$HERE/run.sh" old "r${i}a_old"
        "$HERE/run.sh" new "r${i}b_new"
    fi
    "$HERE/run.sh" new "r${i}c_new"
    "$HERE/run.sh" old "r${i}d_old"
done
echo "=== 全8本 完了 $(date --iso-8601=seconds) ==="
