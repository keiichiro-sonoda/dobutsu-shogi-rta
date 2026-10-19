#!/bin/bash
# 実験 perf_39: 完走 30 本 (記録試行ではない). 進行は logs/console.log に残す
#
# 種類は stat:T1 … stat:S1 (perf_38 と同じ8組), record:cyc, record:l2m の 10 個. 腕は1つ (impl/39_rank_lean).
# 3回 (r1〜r3) まわし, 回ごとに種類の順を3つずつずらす. 10 種類 × 3 回 ＝ 30 本 (perf stat 24 本, perf record 6 本).
# ラベルは r<回>_<種類> (例 r2_S1, r1_cyc).
# どの本も numactl でノード0に固定し, 走る前にノード0の空きを確かめる (run_one.sh).
# 回す前の負荷は load average と CPU 使用率の合計だけを残す (プロセスの名前は残さない. CLAUDE.md)
# ⚠️ 1本あたり完走 1.5 分 + 検査とビルド 約 0.5 分で, 30 本で約 1 時間. その間このマシンで他の計算を回さないこと
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
mkdir -p "$HERE/logs"
if [ -e "$HERE/logs/console.log" ]; then
    echo "logs/console.log が残っている. 前回と混ざるので, 退避してから起動すること" >&2
    exit 2
fi
if [ -n "$(find "$ROOT/impl/39_rank_lean" -name __pycache__)" ]; then
    echo "impl/39_rank_lean に __pycache__ がある. 消してから起動すること" >&2
    exit 2
fi
exec > >(tee "$HERE/logs/console.log") 2>&1

echo "=== perf_39 開始 $(date --iso-8601=seconds) ==="
"$HERE/preflight.sh"
KINDS=(stat:T1 stat:T2 stat:M1 stat:M2 stat:M3 stat:C1 stat:C2 stat:S1 record:cyc record:l2m)
for r in 1 2 3; do
    off=$(( (r - 1) * 3 ))
    for i in $(seq 0 9); do
        k=${KINDS[$(( (i + off) % 10 ))]}
        "$HERE/run_one.sh" "$k" "r${r}_${k#*:}"
    done
done
echo "=== 全30本 完了 $(date --iso-8601=seconds) ==="
