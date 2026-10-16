#!/bin/bash
# 実験 bitboard_gen: 組み立て → 一致の検査 → ベンチ → 帰属 (記録試行ではない). 進行は logs/console.log に残す
#
# 完走は回さない (入力の dat/ とブロックは runs/ に残っている). 回す前に kernel.perf_event_paranoid が 1 か,
# impl/34_unmove に __pycache__ が無いか, CPU 使用率 (全 CPU) が 3% 以下か (ほかの計算が動いていないか) を確かめる.
# 一致の検査が1局面でも外れた腕は計時しない. 両方外れたらベンチと帰属に進まない
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
W="$ROOT/runs/bitboard_gen"
mkdir -p "$HERE/logs"
if [ -e "$HERE/logs/console.log" ]; then
    echo "logs/console.log が残っている. 前回と混ざるので, 退避してから起動すること" >&2
    exit 2
fi
if [ -e "$W" ]; then
    echo "前回の $W が残っている. 退避するか消してから起動すること" >&2
    exit 2
fi
if [ -n "$(find "$ROOT/impl/34_unmove" -name __pycache__)" ]; then
    echo "impl/34_unmove に __pycache__ がある. 消してから起動すること" >&2
    exit 2
fi
exec > >(tee "$HERE/logs/console.log") 2>&1
echo "=== bitboard_gen 開始 $(date --iso-8601=seconds) ==="
perf --version
PARANOID=$(cat /proc/sys/kernel/perf_event_paranoid)
echo "kernel.perf_event_paranoid = $PARANOID"
if [ "$PARANOID" != 1 ]; then
    echo "!!! kernel.perf_event_paranoid が 1 でない. 回さない (本人に知らせる)" >&2
    exit 5
fi
echo "--- 回す前の負荷 ---"
awk '{print "load average:", $1 ",", $2 ",", $3}' /proc/loadavg
BUSY=$(vmstat 1 2 | awk 'NR == 2 {for (i = 1; i <= NF; i++) if ($i == "id") c = i} END {print 100 - $c}')
echo "CPU 使用率 (全 CPU, 1秒): ${BUSY}%"
if [ "$BUSY" -gt 3 ]; then
    echo "!!! CPU 使用率が ${BUSY}% (3% を超える). ほかの計算が動いているので回さない (本人に知らせる)" >&2
    exit 6
fi
mkdir -p "$W"
echo "=== 開始 build $(date --iso-8601=seconds) ==="
for a in base bb_nibble bb_pext; do
    "$HERE/build_arm.sh" "$a" "$W/arm_$a"
    python3 "$HERE/check_asm.py" "$a" "$W/arm_$a" > /dev/null || { echo "!!! $a: check_asm.py が通らない" >&2; exit 3; }
    "$HERE/build_bench.sh" "$a" "$W/arm_$a" "$W/bench_$a"
done
BENCH_REF="$ROOT/runs/perf_branch_34/bench/bench.so"
if ! cmp -s "$W/bench_base/bench.so" "$BENCH_REF"; then
    echo "!!! base の bench.so が perf_branch_34 のものと違う" >&2
    exit 3
fi
echo "base の bench.so は perf_branch_34 のものとバイト一致"
"$HERE/run_verify.sh" "$W/arm_base/animal_shogi.so" "$W/arm_bb_nibble/animal_shogi.so" "$W/arm_bb_pext/animal_shogi.so"
ARMS=(base)
for a in bb_nibble bb_pext; do
    if tail -1 "$HERE/logs/verify_$a.txt" | grep -q '/ 不一致 0$'; then
        ARMS+=("$a")
    else
        echo "!!! $a: 一致の検査が外れた. 計時しない"
    fi
done
if [ "${#ARMS[@]}" -eq 1 ]; then
    echo "!!! 両方の腕で一致の検査が外れた. ベンチと帰属に進まない"
    exit 1
fi
"$HERE/run_bench.sh" "${ARMS[@]}"
"$HERE/run_attr.sh" "${ARMS[@]}"
cp "$ROOT/runs/perf_34/dump/blocks/index.tsv" "$HERE/logs/blocks_index.tsv"
cp "$ROOT/experiments/perf_branch_34/logs/split_index.tsv" "$HERE/logs/split_index.tsv"
echo "=== bitboard_gen 完了 $(date --iso-8601=seconds) ==="
