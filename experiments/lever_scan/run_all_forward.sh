#!/bin/bash
# 全探索の門番: 7腕 × 3ブロック = 21本 (記録試行ではない)
#
# ブロック b の位置 p に ARMS[(b + p) % 7] を置く巡回の配置 (gate_18_opt と同じ形).
# 各腕は3つの異なる位置に来る. 各腕に一度も来ない位置が4つあるので, ラテン方陣ではない.
#
#   block1:  base   fnsi   const  native huge   pf     all
#   block2:  fnsi   const  native huge   pf     all    base
#   block3:  const  native huge   pf     all    base   fnsi
#
# ⚠️ 巡回では「直前の腕」が固定される (huge の次は毎回 pf). 持ち越しがあると
#    分けられない. vmstat の前後の行で兆候だけ見る.
#
# 1本目 (b1_base) の dat/ を後退解析の門番の入力にする (runs/g19_fixture_bin/dat).
# 全探索は決定的なので, 本走の retreatAnalysis() が読むのと同じバイト列になる.
#
# 期限 (DEADLINE, epoch 秒) を渡されたら, 次の1本が収まらないときに止める.
# ⚠️ 約50分かかる. その間このマシンで他の計算を回さないこと
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ARMS=(base fnsi const native huge pf all)
N=${#ARMS[@]}
PER_RUN=180
DEADLINE="${DEADLINE:-0}"
FIX="$ROOT/runs/g19_fixture_bin/dat"

done_n=0
for b in 0 1 2; do
    for pos in 0 1 2 3 4 5 6; do
        arm=${ARMS[$(((b + pos) % N))]}
        label="b$((b + 1))_$arm"
        if [ "$DEADLINE" -gt 0 ] && [ $(($(date +%s) + PER_RUN)) -gt "$DEADLINE" ]; then
            echo "=== 期限で打ち切り: $done_n 本で止めた $(date --iso-8601=seconds) ==="
            exit 0
        fi
        if [ "$b" -eq 0 ] && [ "$pos" -eq 0 ]; then
            "$HERE/run_forward.sh" "$arm" "$label" keep
            if [ -e "$FIX" ]; then
                echo "!!! ${FIX#"$ROOT"/} が既にある. 上書きしない" >&2
                exit 2
            fi
            mkdir -p "$(dirname "$FIX")"
            mv "$ROOT/runs/exp_lsf_$label/dat" "$FIX"
            echo "後退解析の入力を作った: ${FIX#"$ROOT"/} ($(find "$FIX" -type f | wc -l) ファイル)"
        else
            "$HERE/run_forward.sh" "$arm" "$label"
        fi
        done_n=$((done_n + 1))
    done
done
echo "=== 全探索 全21本 完了 $(date --iso-8601=seconds) ==="
