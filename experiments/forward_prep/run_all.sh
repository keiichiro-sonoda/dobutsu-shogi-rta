#!/bin/bash
# 計時の門番 (実験 forward_prep。記録試行ではない). run_verify.sh が PASS のあとに回す
#
#   run_all.sh
#
# 3腕 (old / recalc / carry) を6本ずつ, 計18本. 3本ずつの組を6つ並べ, 組の中の並びを3腕の6通りの並べ方に1回ずつ当てる.
# どの腕も, 組の中の1番目・2番目・3番目にちょうど2回ずつ来る (位置の偏りが腕に乗らない):
#   t1  old recalc carry      t2  recalc carry old      t3  carry old recalc
#   t4  old carry recalc      t5  carry recalc old      t6  recalc old carry
# どの本も run_one.sh (numactl でノード0に固定, 走る前に空きを確かめて残す, 走ったあとの照合). 1本でも止まったらそこで止める.
# 進行は logs/console.log (experiments/gate_stats.py が腕とラベルを読む)
# 回す前の負荷は load average と CPU 使用率の合計だけを残す (CLAUDE.md「記録に残さないもの」)
set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
if [ -e "$HERE/logs/console.log" ]; then
    echo "logs/console.log が残っている. 退避してから起動すること" >&2
    exit 2
fi
if ! grep -qx '一致の検査: PASS' "$HERE/logs/verify.txt"; then
    echo "!!! 一致の検査が PASS でないので測らない (止める条件)" >&2
    exit 1
fi
exec > >(tee "$HERE/logs/console.log") 2>&1
echo "=== forward_prep 門番 開始 $(date --iso-8601=seconds) ==="
awk '{print "load average:", $1 ",", $2 ",", $3}' /proc/loadavg
vmstat 1 2 | awk 'NR == 2 {for (i = 1; i <= NF; i++) if ($i == "id") c = i}
                  END {print "CPU 使用率 (全 CPU, 1秒):", 100 - $c "%"}'
echo "THP enabled: $(cat /sys/kernel/mm/transparent_hugepage/enabled)"
ORDER=(
    "t1 old recalc carry" "t2 recalc carry old" "t3 carry old recalc"
    "t4 old carry recalc" "t5 carry recalc old" "t6 recalc old carry"
)
for row in "${ORDER[@]}"; do
    read -r grp a b c <<< "$row"
    k=0
    for arm in "$a" "$b" "$c"; do
        k=$((k + 1))
        "$HERE/run_one.sh" "$arm" "${grp}${k}_$arm" time
    done
done
echo "=== forward_prep 門番 全18本 完了 $(date --iso-8601=seconds) ==="
