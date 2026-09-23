#!/bin/bash
# 後退解析の門番: 7腕 × 3ブロック = 21本 (記録試行ではない)
#
# 並びは run_all_forward.sh と同じ巡回. ラベルは r<ブロック>_<腕>.
# 入力は runs/g19_fixture_bin/dat (全探索の門番の b1_base が書いたもの).
#
# 1本目の base で確かめること:
#   ① 出力が #19 本走の dat/ とバイト一致する (run_retreat.sh が外れたら止める)
#   ② P4 が本走の 64 秒前後に来る (numactl で固定しているので完全には揃わない.
#      値は記録して先へ進む. 入力が正しいことは①で示せる)
#
# ⚠️ 約75分かかる. その間このマシンで他の計算を回さないこと
set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ARMS=(base fnsi const native huge pf all)
N=${#ARMS[@]}
PER_RUN=240
DEADLINE="${DEADLINE:-0}"

done_n=0
for b in 0 1 2; do
    for pos in 0 1 2 3 4 5 6; do
        arm=${ARMS[$(((b + pos) % N))]}
        if [ "$DEADLINE" -gt 0 ] && [ $(($(date +%s) + PER_RUN)) -gt "$DEADLINE" ]; then
            echo "=== 期限で打ち切り: $done_n 本で止めた $(date --iso-8601=seconds) ==="
            exit 0
        fi
        "$HERE/run_retreat.sh" "$arm" "r$((b + 1))_$arm"
        done_n=$((done_n + 1))
    done
done
echo "=== 後退解析 全21本 完了 $(date --iso-8601=seconds) ==="
