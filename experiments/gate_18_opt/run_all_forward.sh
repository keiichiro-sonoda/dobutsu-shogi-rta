#!/bin/bash
# 5腕 × 4ブロック = 20本 (記録試行ではない)
#
# ⚠️ **ABBA は2腕用.** numa_bind で分かったとおり持ち越しは相殺されないので,
#    5腕では「各腕が各位置に同じ回数来る」ように回す (ラテン方陣).
#
#   block1:  o0  o1  o2  o3  o2n
#   block2:  o1  o2  o3  o2n o0
#   block3:  o2  o3  o2n o0  o1
#   block4:  o3  o2n o0  o1  o2
#
# 各腕は4つの異なる位置に来る.
#
# ⚠️ 1本あたり全探索 3〜4 分なので, 20本で約70分かかる.
#    その間このマシンで他の計算を回さないこと.
set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

ARMS=(o0 o1 o2 o3 o2n)
N=${#ARMS[@]}

for b in 0 1 2 3; do
    for pos in 0 1 2 3 4; do
        arm=${ARMS[$(((b + pos) % N))]}
        # 各腕の1本目だけ dat/ を残す. 5腕がバイト同一になることの照合に要る
        if [ "$b" -eq 0 ]; then
            "$HERE/run_forward.sh" "$arm" "b$((b + 1))_$arm" keep
        else
            "$HERE/run_forward.sh" "$arm" "b$((b + 1))_$arm"
        fi
    done
done
echo "=== 全20本 完了 $(date --iso-8601=seconds) ==="
