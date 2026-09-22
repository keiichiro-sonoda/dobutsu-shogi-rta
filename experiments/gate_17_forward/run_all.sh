#!/bin/bash
# old new new old を2回, 計8本 (記録試行ではない)
#
# 対で向きを入れ替えると「対のなかの位置」が片方の腕に乗らない
# (記録 #14 の門番で P0 に出た形).
#
# ⚠️ 空の dat/ から始めるので, 両腕の入力は定義上同一. 揃える小道具が要らない.
#
# ⚠️ 1本あたり全探索 8分20秒ほどなので, 8本で約1.1時間かかる.
#    その間このマシンで他の計算を回さないこと.
set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

for i in 1 2; do
    # 1組目だけ dat/ を残す. 両腕の成果物の指紋照合と, 並びの照合に要る
    if [ "$i" -eq 1 ]; then
        "$HERE/run.sh" old "g${i}a" keep
        "$HERE/run.sh" new "g${i}b" keep
    else
        "$HERE/run.sh" old "g${i}a"
        "$HERE/run.sh" new "g${i}b"
    fi
    "$HERE/run.sh" new "g${i}c"
    "$HERE/run.sh" old "g${i}d"
done
echo "=== 全8本 完了 $(date --iso-8601=seconds) ==="
