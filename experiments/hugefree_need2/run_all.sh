#!/bin/bash
# 実験 hugefree_need2: pin と free を交互に5本 (記録試行ではない). 進行は logs/console.log に残す
#
# experiments/hugefree_need/run_all.sh の写し (並びも同じ)
#
#   1 p1_pin   2 f2_free   3 p3_pin   4 f4_free   5 p5_pin
#
# pin は numactl でノード0に固定 (門番と同じ), free は固定しない (本走と同じ). 5本のあいだはキャッシュを落とさない
# (本を重ねたときの空きの減り方と, 次の本への持ち越しを見るため). 回す前の負荷は load average と CPU 使用率の合計だけを残す.
# 1本の完走 約1.5分 + 答えの検査 約1分で, 5本で約15分. その間このマシンで他の計算を回さないこと
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
mkdir -p "$HERE/logs"
if [ -e "$HERE/logs/console.log" ]; then
    echo "logs/console.log が残っている. 前回と混ざるので, 退避してから起動すること" >&2
    exit 2
fi
if [ -e "$ROOT/runs/hugefree_need2" ]; then
    echo "前回の runs/hugefree_need2 が残っている. 退避するか消してから起動すること" >&2
    exit 2
fi
if [ -n "$(find "$ROOT/impl/38_precheck" -name __pycache__)" ]; then
    echo "impl/38_precheck に __pycache__ がある. 消してから起動すること" >&2
    exit 2
fi
exec > >(tee "$HERE/logs/console.log") 2>&1
echo "=== hugefree_need 開始 $(date --iso-8601=seconds) ==="
echo "--- 回す前の負荷 ---"
awk '{print "load average:", $1 ",", $2 ",", $3}' /proc/loadavg
BUSY=$(vmstat 1 2 | awk 'NR == 2 {for (i = 1; i <= NF; i++) if ($i == "id") c = i} END {print 100 - $c}')
echo "CPU 使用率 (全 CPU, 1秒): ${BUSY}%"
if [ "$BUSY" -gt 3 ]; then
    echo "!!! CPU 使用率が ${BUSY}% (3% を超える). ほかの計算が動いているので回さない (本人に知らせる)" >&2
    exit 6
fi
"$HERE/run_one.sh" pin p1_pin 1
"$HERE/run_one.sh" free f2_free 2
"$HERE/run_one.sh" pin p3_pin 3
"$HERE/run_one.sh" free f4_free 4
"$HERE/run_one.sh" pin p5_pin 5
echo "=== 全5本 完了 $(date --iso-8601=seconds) ==="
