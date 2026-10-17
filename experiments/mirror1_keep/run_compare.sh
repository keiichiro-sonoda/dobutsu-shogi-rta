#!/bin/bash
# 完走の比較 (実験 mirror1_keep。記録試行ではない. 記録の門番でもない). 3腕 × 6本 ＝ 18本.
# 進行は logs/console_compare.log に残す
#
# 配置 (3腕のラテン方陣を2種類, 3ブロックずつ. どの腕もブロックの中の各位置に2回ずつ来る. ブロックの中で
# ある腕のすぐ後ろに来る腕も, ほかの2腕に2回ずつ):
#   b1: base mirror1 mirror1_keep        b4: base mirror1_keep mirror1
#   b2: mirror1 mirror1_keep base        b5: mirror1_keep mirror1 base
#   b3: mirror1_keep base mirror1        b6: mirror1 base mirror1_keep
#
# どの本も numactl でノード0に固定し, 走る前にノード0の空きメモリを確かめる (run_one.sh).
# run_all.sh が通って (logs/arms_ok.txt に3腕とも載って) いなければ回さない
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
mkdir -p "$HERE/logs/compare"
if [ -e "$HERE/logs/console_compare.log" ]; then
    echo "logs/console_compare.log が残っている. 前回と混ざるので, 退避してから起動すること" >&2
    exit 2
fi
if [ -n "$(find "$ROOT/impl/36_bb_unmove" -name __pycache__)" ]; then
    echo "impl/36_bb_unmove に __pycache__ がある. 消してから起動すること" >&2
    exit 2
fi
if [ "$(sort "$HERE/logs/arms_ok.txt" 2>/dev/null | tr '\n' ' ')" != "base mirror1 mirror1_keep " ]; then
    echo "!!! run_all.sh が3腕とも通っていない (logs/arms_ok.txt). 完走の比較は回さない" >&2
    exit 1
fi
exec > >(tee "$HERE/logs/console_compare.log") 2>&1
echo "=== 完走の比較 開始 $(date --iso-8601=seconds) ==="
echo "--- 回す前の負荷 ---"
awk '{print "load average:", $1 ",", $2 ",", $3}' /proc/loadavg
BUSY=$(vmstat 1 2 | awk 'NR == 2 {for (i = 1; i <= NF; i++) if ($i == "id") c = i} END {print 100 - $c}')
echo "CPU 使用率 (全 CPU, 1秒): ${BUSY}%"
if [ "$BUSY" -gt 3 ]; then
    echo "!!! CPU 使用率が ${BUSY}% (3% を超える). ほかの計算が動いているので回さない (本人に知らせる)" >&2
    exit 6
fi
BLOCKS=(
    "base mirror1 mirror1_keep"
    "mirror1 mirror1_keep base"
    "mirror1_keep base mirror1"
    "base mirror1_keep mirror1"
    "mirror1_keep mirror1 base"
    "mirror1 base mirror1_keep"
)
for b in 1 2 3 4 5 6; do
    read -r -a arms <<< "${BLOCKS[$((b - 1))]}"
    for i in 0 1 2; do
        "$HERE/run_one.sh" "${arms[$i]}" "b${b}${i}_${arms[$i]}"
    done
done
echo "=== 全18本 完了 $(date --iso-8601=seconds) ==="
