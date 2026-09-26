#!/bin/bash
# 実験 lever_scan_2: 6腕 × 6ブロック = 36本 (記録試行ではない). 進行は logs/console.log に残す
#
# 配置は 6×6 の Williams 型ラテン方陣 (1行目 0 1 5 2 4 3, 以後の行は +1 ずつ).
#   ARMS = base pf2 pf3 hugeR reuse all (番号 0〜5)
#
#   block1:  base  pf2   all   pf3   reuse hugeR
#   block2:  pf2   pf3   base  hugeR all   reuse
#   block3:  pf3   hugeR pf2   reuse base  all
#   block4:  hugeR reuse pf3   all   pf2   base
#   block5:  reuse all   hugeR base  pf3   pf2
#   block6:  all   base  reuse pf2   hugeR pf3
#
# 各腕は各位置 (1〜6番目) にちょうど1回ずつ来る. ブロックの中で隣り合う前後の順序対
# (30通り) も, どれもちょうど1回ずつ (直前の腕の持ち越しが腕の効果に偏らない).
# ブロックをまたぐ前後 (block1 の最後 → block2 の最初) は揃えていない.
#
# 機械時間の上限は4時間. 次の本を始める前に「経過 + 5 分 > 4 時間」なら止める.
# 途中で腕を足したり, 結果を見て本数を増やしたりしない.
# ⚠️ 1本あたり完走 3分強 + 検査で, 36本で約2時間10分. その間このマシンで他の計算を回さないこと
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
LIMIT_SEC=$((4 * 3600))
MARGIN_SEC=300
mkdir -p "$HERE/logs"
if [ -e "$HERE/logs/console.log" ]; then
    echo "logs/console.log が残っている. 前回と混ざるので, 退避してから起動すること" >&2
    exit 2
fi
if [ -n "$(find "$ROOT/impl/22_in_memory" -name __pycache__)" ]; then
    echo "impl/22_in_memory に __pycache__ がある. 消してから起動すること" >&2
    exit 2
fi
exec > >(tee "$HERE/logs/console.log") 2>&1

ARMS=(base pf2 pf3 hugeR reuse all)
FIRST=(0 1 5 2 4 3)
POS=(a b c d e f)
START=$(date +%s)
echo "=== 実験 lever_scan_2 開始 $(date --iso-8601=seconds) ==="
echo "--- 回す前の負荷 ---"
uptime
ps -eo pcpu,etime,comm --sort=-pcpu | head -6
for b in 0 1 2 3 4 5; do
    for p in 0 1 2 3 4 5; do
        now=$(date +%s)
        if [ $((now - START + MARGIN_SEC)) -gt "$LIMIT_SEC" ]; then
            echo "!!! 機械時間の上限 (4時間) を超えそうなので止める (経過 $((now - START)) 秒)"
            exit 3
        fi
        arm=${ARMS[$(((FIRST[p] + b) % 6))]}
        "$HERE/run_one.sh" "$arm" "b$((b + 1))${POS[$p]}_$arm"
    done
done
echo "=== 全36本 完了 $(date --iso-8601=seconds) (経過 $(($(date +%s) - START)) 秒) ==="
