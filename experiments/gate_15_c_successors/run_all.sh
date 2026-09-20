#!/bin/bash
# 旧版 (impl/14) と新版 (impl/15) を old new new old の順で8本ずつ走らせる
#
# ⚠️ 並びを ABBA にするのは, 対のなかで後に走るほうへ系統的に乗る何かを
#    相殺するため. gate_12 と gate_14 は old new の固定順で, gate_14 では
#    P0 が3本とも新版のほうが高く出た (+2.3 秒 / +2.5%). loadForwardResult は
#    1行も変えていないので効果ではありえず, 位置の効きと分離できていない.
#
# ⚠️ 3本ずつでは足りない. gate_14 が取った同一コード6本で P2 は
#    190/193/194/197/220/222 秒 (平均 202.7 / sd 14.4 / 変動係数 7.1%) と振れており,
#    見込む効果量 30〜70 秒に対して, 3本ずつだと低い側で区間が 0 を跨ぐ.
#
# ⚠️ 1本あたり後退解析 ≈ 10〜13 分なので, 16本で約3時間かかる.
#    その間このマシンで他の計算を回さないこと.
set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

for i in 1 2 3 4; do
    "$HERE/run.sh" impl/14_c_retreat    "old${i}a"
    "$HERE/run.sh" impl/15_c_successors "new${i}a"
    "$HERE/run.sh" impl/15_c_successors "new${i}b"
    "$HERE/run.sh" impl/14_c_retreat    "old${i}b"
done
echo "=== 全16本 完了 $(date --iso-8601=seconds) ==="
