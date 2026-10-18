#!/bin/bash
# 実験 rank_fast の段2: 腕を組み, 一致の検査を通った腕だけをベンチで比べる (記録試行ではない). 進行は logs/console_stage2.log
#
# 腕は base (impl/38_precheck のまま) と lean (patches/lean.patch). 順は:
#   1. 組む (build_arm2.sh. 警告 0・関数の記号が base と同じ・.bss に足した表) → logs/build_<腕>.txt
#   2. 一致の検査 (run_verify.sh) → logs/verify_<腕>.txt. 外れたら止める (止める条件 2. 計時しない)
#   3. ベンチをビルド (build_bench.sh). base の bench.so と rank.so が段1と同じバイト列であることを見る
#   4. 文脈の中のベンチ (run_bench2.sh) → logs/bench2.tsv
#   5. rankOf だけのベンチ (run_rankbench.sh) → logs/rankbench_stage2.tsv
# 回す前の負荷は load average と CPU 使用率の合計だけを残す
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
W="$ROOT/runs/rank_fast/s2"
ARMS=(base lean)
if [ -e "$HERE/logs/console_stage2.log" ]; then
    echo "logs/console_stage2.log が残っている. 前回と混ざるので, 退避してから起動すること" >&2
    exit 2
fi
if [ -e "$W" ]; then
    echo "前回の runs/rank_fast/s2 が残っている. 退避するか消してから起動すること" >&2
    exit 2
fi
if [ -n "$(find "$ROOT/impl/38_precheck" -name __pycache__)" ]; then
    echo "impl/38_precheck に __pycache__ がある. 消してから起動すること" >&2
    exit 2
fi
exec > >(tee "$HERE/logs/console_stage2.log") 2>&1

echo "=== rank_fast 段2 開始 $(date --iso-8601=seconds) ==="
PARANOID=$(cat /proc/sys/kernel/perf_event_paranoid)
echo "kernel.perf_event_paranoid = $PARANOID"
if [ "$PARANOID" != 1 ]; then
    echo "!!! kernel.perf_event_paranoid が 1 でない. 回さない (本人に知らせる. 止める条件 5)" >&2
    exit 5
fi
awk '{print "load average:", $1 ",", $2 ",", $3}' /proc/loadavg
BUSY=$(vmstat 1 2 | awk 'NR == 2 {for (i = 1; i <= NF; i++) if ($i == "id") c = i} END {print 100 - $c}')
echo "CPU 使用率 (全 CPU, 1秒): ${BUSY}%"
if [ "$BUSY" -gt 3 ]; then
    echo "!!! CPU 使用率が ${BUSY}% (3% を超える). ほかの計算が動いているので回さない (本人に知らせる)" >&2
    exit 6
fi

mkdir -p "$W"
for a in "${ARMS[@]}"; do
    echo "=== 開始 build_$a $(date --iso-8601=seconds) ==="
    "$HERE/build_arm2.sh" "$a" "$W/arm_$a" | tee "$HERE/logs/build_$a.txt"
done
echo "=== 開始 verify $(date --iso-8601=seconds) ==="
if ! "$HERE/run_verify.sh" "$W/arm_base/animal_shogi.so" "lean=$W/arm_lean/animal_shogi.so"; then
    echo "!!! 一致の検査が外れた (止める条件 2). 計時しない. 直し方は決めずに報告する" >&2
    exit 1
fi
SPECS=()
for a in "${ARMS[@]}"; do
    "$HERE/build_bench.sh" "$W/arm_$a" "$W/bench_$a" | tee -a "$HERE/logs/build_$a.txt"
    SPECS+=("$a=$W/bench_$a")
done
for f in bench.so:dd26c973f5a7 rank.so:a1c69d5f26e0; do
    GOT=$(sha256sum "$W/bench_base/${f%%:*}" | cut -c1-12)
    if [ "$GOT" != "${f#*:}" ]; then
        echo "!!! base の ${f%%:*} が段1と違う ($GOT, 段1は ${f#*:})" >&2
        exit 3
    fi
done
echo "=== 開始 bench2 $(date --iso-8601=seconds) ==="
"$HERE/run_bench2.sh" "${SPECS[@]}"
echo "=== 開始 rankbench_stage2 $(date --iso-8601=seconds) ==="
"$HERE/run_rankbench.sh" "$HERE/logs/rankbench_stage2.tsv" "${SPECS[@]}"
echo "=== rank_fast 段2 完了 $(date --iso-8601=seconds) ==="
