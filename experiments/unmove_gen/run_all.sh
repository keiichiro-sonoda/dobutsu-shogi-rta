#!/bin/bash
# 実験 unmove_gen: 組み立て → 一致の検査 → 完走の答え合わせ → ベンチ → 帰属 (記録試行ではない).
# 進行は logs/console.log に残す
#
# 回す前に kernel.perf_event_paranoid が 1 か, impl/35_bitboard に __pycache__ が無いか,
# CPU 使用率 (全 CPU) が 3% 以下か (ほかの計算が動いていないか), ノード0の 2 MiB 以上の空きが 16 GiB 以上か
# (完走の前にも run_full.sh が見る) を確かめる. 合わなければ回さない (本人に知らせる).
# 一致の検査か完走の答え合わせが外れた腕は計時しない. 両方外れたらベンチと帰属に進まない
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$HERE/lib.sh"
W="$ROOT/runs/unmove_gen"
mkdir -p "$HERE/logs"
if [ -e "$HERE/logs/console.log" ]; then
    echo "logs/console.log が残っている. 前回と混ざるので, 退避してから起動すること" >&2
    exit 2
fi
if [ -e "$W" ]; then
    echo "前回の $W が残っている. 退避するか消してから起動すること" >&2
    exit 2
fi
if [ -n "$(find "$ROOT/impl/35_bitboard" -name __pycache__)" ]; then
    echo "impl/35_bitboard に __pycache__ がある. 消してから起動すること" >&2
    exit 2
fi
exec > >(tee "$HERE/logs/console.log") 2>&1
echo "=== unmove_gen 開始 $(date --iso-8601=seconds) ==="
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
FREE0=$(hugefree_gib 0)
echo "ノード0の 2 MiB 以上の空きブロック: $FREE0 GiB (完走の前のしきい値 16)"
if ! awk -v have="$FREE0" 'BEGIN { exit !(have != "-" && have + 0 >= 16) }'; then
    echo "!!! ノード0の巨大ページのための空きが足りない. 回さない (本人に知らせる)" >&2
    exit 4
fi
mkdir -p "$W"
echo "=== 開始 build $(date --iso-8601=seconds) ==="
for a in base mirror1 bb_unmove; do
    "$HERE/build_arm.sh" "$a" "$W/arm_$a"
    python3 "$HERE/check_asm.py" "$a" "$W/arm_$a" > "$W/asm_$a.txt" \
        || { echo "!!! $a: check_asm.py が通らない" >&2; exit 3; }
    "$HERE/build_bench.sh" "$a" "$W/arm_$a" "$W/bench_$a"
done
for a in base mirror1 bb_unmove; do
    cmp -s "$W/asm_$a.txt" "$HERE/logs/asm_$a.txt" \
        || { echo "!!! $a: 機械語の数え (check_asm.py) が登録のときと違う" >&2; exit 3; }
done
BENCH_REF="$ROOT/runs/bitboard_gen/bench_bb_nibble/bench.so"
if ! cmp -s "$W/bench_base/bench.so" "$BENCH_REF"; then
    echo "!!! base の bench.so が bitboard_gen の bb_nibble のものと違う" >&2
    exit 3
fi
echo "base の bench.so は bitboard_gen の bb_nibble のもの (impl/35_bitboard と同じ C) とバイト一致"
"$HERE/run_verify.sh" "$W/arm_base/animal_shogi.so" "$W/arm_mirror1/animal_shogi.so" \
    "$W/arm_bb_unmove/animal_shogi.so"
ARMS=(base)
for a in mirror1 bb_unmove; do
    if ! tail -1 "$HERE/logs/verify_$a.txt" | grep -q '/ 不一致 0$'; then
        echo "!!! $a: 一致の検査が外れた. 完走も計時もしない"
        continue
    fi
    set +e
    "$HERE/run_full.sh" "$a"
    rc=$?
    set -e
    if [ "$rc" != 0 ]; then
        if [ "$rc" = 4 ]; then
            echo "!!! $a: 完走の前の巨大ページの空きが足りない. ここで止める (本人に知らせる)"
            exit 4
        fi
        echo "!!! $a: 完走の答え合わせが外れた. 計時しない"
        continue
    fi
    ARMS+=("$a")
done
if [ "${#ARMS[@]}" -eq 1 ]; then
    echo "!!! 両方の腕が止める条件に掛かった. ベンチと帰属に進まない"
    exit 1
fi
"$HERE/run_bench.sh" "${ARMS[@]}"
"$HERE/run_attr.sh" "${ARMS[@]}"
if [[ " ${ARMS[*]} " == *" mirror1 "* ]]; then
    "$HERE/run_counts.sh"
fi
cp "$ROOT/runs/perf_34/dump/blocks/index.tsv" "$HERE/logs/blocks_index.tsv"
echo "=== unmove_gen 完了 $(date --iso-8601=seconds) ==="
