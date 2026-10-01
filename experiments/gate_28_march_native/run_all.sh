#!/bin/bash
# 門番 #28: old new new old を3回 = 12本 (記録試行ではない). 進行は logs/console.log に残す
#
#   block1:  old new new old
#   block2:  old new new old
#   block3:  old new new old
#
# 各腕6本. どの本も numactl でノード0に固定し, 走る前にノード0の空きメモリを確かめる (run_one.sh).
# 回す前の負荷は load average と CPU 使用率の合計だけを残す (プロセスの名前は残さない. CLAUDE.md)
#
# ⚠️ 1本あたり完走 3分弱 + 検査で, 12本で約40分. その間このマシンで他の計算を回さないこと
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
mkdir -p "$HERE/logs"
if [ -e "$HERE/logs/console.log" ]; then
    echo "logs/console.log が残っている. 前回と混ざるので, 退避してから起動すること" >&2
    exit 2
fi
if [ -n "$(find "$ROOT/impl/27_no_interposition" "$ROOT/impl/28_march_native" -name __pycache__)" ]; then
    echo "impl/27_no_interposition か impl/28_march_native に __pycache__ がある. 消してから起動すること" >&2
    exit 2
fi
exec > >(tee "$HERE/logs/console.log") 2>&1

echo "=== 門番 #28 開始 $(date --iso-8601=seconds) ==="
# -march=native が何に解決されたか (別の CPU では別のバイナリになる. 再現のために残す)
"$HERE/march.sh" | tee "$HERE/logs/march.txt"
echo "--- 回す前の負荷 ---"
awk '{print "load average:", $1 ",", $2 ",", $3}' /proc/loadavg
vmstat 1 2 | awk 'NR == 2 {for (i = 1; i <= NF; i++) if ($i == "id") c = i}
                  END {print "CPU 使用率 (全 CPU, 1秒):", 100 - $c "%"}'
echo "--- 回す前のノード0のメモリ (/proc/buddyinfo と meminfo) ---"
grep "Node 0" /proc/buddyinfo
grep -E "MemFree|FilePages" /sys/devices/system/node/node0/meminfo
for b in 1 2 3; do
    "$HERE/run_one.sh" old "r${b}a_old"
    "$HERE/run_one.sh" new "r${b}b_new"
    "$HERE/run_one.sh" new "r${b}c_new"
    "$HERE/run_one.sh" old "r${b}d_old"
done
echo "=== 全12本 完了 $(date --iso-8601=seconds) ==="
