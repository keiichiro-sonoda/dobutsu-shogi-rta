#!/bin/bash
# 門番 #34: old new new old を3回 = 12本 (記録試行ではない). 進行は logs/console.log に残す
#
#   block1:  old new new old
#   block2:  old new new old
#   block3:  old new new old
#
# 各腕6本. どの本も numactl でノード0に固定し, 走る前にノード0の空きメモリを確かめる (run_one.sh).
# 回す前の負荷は load average と CPU 使用率の合計だけを残す (プロセスの名前は残さない. CLAUDE.md)
#
# 門番の前の確かめ (run_trial.sh) が通っていなければ回さない.
# ⚠️ 1本あたり完走 2〜3分 + 検査 (指紋に1分) で, 12本で約45分. その間このマシンで他の計算を回さないこと
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
mkdir -p "$HERE/logs"
if [ -e "$HERE/logs/console.log" ]; then
    echo "logs/console.log が残っている. 前回と混ざるので, 退避してから起動すること" >&2
    exit 2
fi
if [ -n "$(find "$ROOT/impl/33_hot_layout" "$ROOT/impl/34_unmove" -name __pycache__)" ]; then
    echo "impl/33_hot_layout か impl/34_unmove に __pycache__ がある. 消してから起動すること" >&2
    exit 2
fi
if ! grep -qx '答えの検査: PASS' "$HERE/logs/trial_new_answer.txt" 2>/dev/null \
    || ! grep -q '^=== 完了 trial_new ' "$HERE/logs/console_trial.log" 2>/dev/null; then
    echo "!!! 門番の前の確かめ (run_trial.sh) が通っていない. 先に回すこと" >&2
    exit 1
fi
exec > >(tee "$HERE/logs/console.log") 2>&1

echo "=== 門番 #34 開始 $(date --iso-8601=seconds) ==="
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
