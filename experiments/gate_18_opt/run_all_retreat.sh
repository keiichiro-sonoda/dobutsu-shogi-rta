#!/bin/bash
# o0 と「全探索側で決めた段」を4本ずつ, old new new old を2回 = 8本 (記録試行ではない)
#
#   run_all_retreat.sh <決めた段>
#
# 段の選択は run_all_forward.sh で終わっている. ここは後退解析が退行していないことの
# 確認なので腕は2つでよく, 2腕なら「対で向きを入れ替える」が書ける.
#
# ⚠️ 1本あたり後退解析 6〜7 分なので, 8本で約50分かかる.
#    その間このマシンで他の計算を回さないこと.
set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PICK="${1:?全探索側で決めた段を指定すること (o1|o2|o3|o2n)}"

for i in 1 2; do
    # 1組目だけ dat/ を残す. 腕どうしがバイト同一になることの照合に要る
    if [ "$i" -eq 1 ]; then
        "$HERE/run_retreat.sh" o0 "r${i}a_o0" keep
        "$HERE/run_retreat.sh" "$PICK" "r${i}b_$PICK" keep
    else
        "$HERE/run_retreat.sh" o0 "r${i}a_o0"
        "$HERE/run_retreat.sh" "$PICK" "r${i}b_$PICK"
    fi
    "$HERE/run_retreat.sh" "$PICK" "r${i}c_$PICK"
    "$HERE/run_retreat.sh" o0 "r${i}d_o0"
done
echo "=== 全8本 完了 $(date --iso-8601=seconds) ==="
