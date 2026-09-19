#!/bin/bash
# 旧版 (impl/11) と新版 (impl/12) を交互に3本ずつ走らせる
#
# ⚠️ 交互にするのは, 機械のドリフトが片方に偏らないようにするため.
# ⚠️ 1本あたり後退解析 ≈ 19 分 (旧版) なので, 全部で2時間前後かかる.
#    その間このマシンで他の計算を回さないこと.
set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

for i in 1 2 3; do
    "$HERE/run.sh" impl/11_c_seen "old$i"
    "$HERE/run.sh" impl/12_c_predecessors "new$i"
done
echo "=== 全6本 完了 $(date --iso-8601=seconds) ==="
