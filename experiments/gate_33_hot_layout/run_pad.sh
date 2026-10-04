#!/bin/bash
# 門番 #33 の追加: 置き場所の振れの大きさを測る (判定には使わない. 記録試行ではない)
#
# .c の頭に 24・40・1000 バイトの詰め物の関数を足した版を, #32 の配置 (old_pad<N>) と
# #33 の配置 (new_pad<N>) で各3本 = 18本. 進行は logs/pad_console.log に残す (判定の console.log と混ぜない)
#
#   block1:  old_pad24   new_pad24   old_pad40   new_pad40   old_pad1000 new_pad1000
#   block2:  new_pad40   old_pad40   new_pad1000 old_pad1000 new_pad24   old_pad24
#   block3:  old_pad1000 new_pad1000 old_pad24   new_pad24   old_pad40   new_pad40
#
# 腕ごとの位置はブロックごとに変える (6腕が1ブロックの中で前半・後半に偏らないように).
# #32 の配置では詰め物の大きさに応じて熱い関数がずれ (24 → 32 バイト, 40 → 48, 1000 → 1008),
# #33 の配置ではずれない (tests/test_impl_33_hot_layout.py と logs/layout.txt).
# 命令は詰め物の関数のほかは同じで, 詰め物の関数は呼ばれない. 本ごとの検査は run_one.sh のまま.
#
# ⚠️ 18本で約55分. その間このマシンで他の計算を回さないこと
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
mkdir -p "$HERE/logs"
if [ -e "$HERE/logs/pad_console.log" ]; then
    echo "logs/pad_console.log が残っている. 前回と混ざるので, 退避してから起動すること" >&2
    exit 2
fi
if [ -n "$(find "$ROOT/impl/32_inline_rank" "$ROOT/impl/33_hot_layout" -name __pycache__)" ]; then
    echo "impl/32_inline_rank か impl/33_hot_layout に __pycache__ がある. 消してから起動すること" >&2
    exit 2
fi
exec > >(tee "$HERE/logs/pad_console.log") 2>&1

echo "=== 門番 #33 の詰め物の本 開始 $(date --iso-8601=seconds) ==="
echo "--- 回す前の負荷 ---"
awk '{print "load average:", $1 ",", $2 ",", $3}' /proc/loadavg
vmstat 1 2 | awk 'NR == 2 {for (i = 1; i <= NF; i++) if ($i == "id") c = i}
                  END {print "CPU 使用率 (全 CPU, 1秒):", 100 - $c "%"}'
echo "--- 回す前のノード0のメモリ (/proc/buddyinfo と meminfo) ---"
grep "Node 0" /proc/buddyinfo
grep -E "MemFree|FilePages" /sys/devices/system/node/node0/meminfo
ORDER=(
    "old_pad24 new_pad24 old_pad40 new_pad40 old_pad1000 new_pad1000"
    "new_pad40 old_pad40 new_pad1000 old_pad1000 new_pad24 old_pad24"
    "old_pad1000 new_pad1000 old_pad24 new_pad24 old_pad40 new_pad40"
)
for b in 1 2 3; do
    i=0
    for arm in ${ORDER[$((b - 1))]}; do
        i=$((i + 1))
        "$HERE/run_one.sh" "$arm" "p${b}${i}_${arm}"
    done
done
echo "=== 詰め物の本 全18本 完了 $(date --iso-8601=seconds) ==="
