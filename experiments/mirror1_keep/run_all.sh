#!/bin/bash
# 実験 mirror1_keep (前半): 組み立て → 一致の検査 → 完走の答え合わせ → ベンチ → 候補の数え (記録試行ではない).
# 進行は logs/console.log に残す. 完走の比較 (18本) は run_compare.sh が別に回す
#
# 回す前に kernel.perf_event_paranoid が 1 か, impl/36_bb_unmove に __pycache__ が無いか,
# CPU 使用率 (全 CPU) が 3% 以下か (ほかの計算が動いていないか), ノード0の 2 MiB 以上の空きが 16 GiB 以上か
# (完走の前にも run_full.sh が見る) を確かめる. 合わなければ回さない (本人に知らせる).
# 止める条件: mirror1 が一致の検査か完走の答え合わせで外れたら, その場で止める (#37 に使うパッチなので先へ進まない).
# mirror1_keep が外れたら, mirror1_keep は計時しない
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$HERE/lib.sh"
W="$ROOT/runs/mirror1_keep"
mkdir -p "$HERE/logs"
if [ -e "$HERE/logs/console.log" ]; then
    echo "logs/console.log が残っている. 前回と混ざるので, 退避してから起動すること" >&2
    exit 2
fi
if [ -e "$W" ]; then
    echo "前回の $W が残っている. 退避するか消してから起動すること" >&2
    exit 2
fi
if [ -n "$(find "$ROOT/impl/36_bb_unmove" -name __pycache__)" ]; then
    echo "impl/36_bb_unmove に __pycache__ がある. 消してから起動すること" >&2
    exit 2
fi
exec > >(tee "$HERE/logs/console.log") 2>&1
echo "=== mirror1_keep 開始 $(date --iso-8601=seconds) ==="
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
for a in base mirror1 mirror1_keep; do
    "$HERE/build_arm.sh" "$a" "$W/arm_$a"
    "$HERE/build_bench.sh" "$a" "$W/arm_$a" "$W/bench_$a"
done
BENCH_REF="$ROOT/runs/unmove_gen/bench_bb_unmove/bench.so"
if ! cmp -s "$W/bench_base/bench.so" "$BENCH_REF"; then
    echo "!!! base の bench.so が unmove_gen の bb_unmove のもの (impl/36_bb_unmove と同じ C) と違う" >&2
    exit 3
fi
echo "base の bench.so は unmove_gen の bb_unmove のもの (impl/36_bb_unmove と同じ C) とバイト一致"
"$HERE/run_verify.sh" "$W/arm_base/animal_shogi.so" "$W/arm_mirror1/animal_shogi.so" \
    "$W/arm_mirror1_keep/animal_shogi.so"
ARMS=(base)
for a in mirror1 mirror1_keep; do
    if ! tail -1 "$HERE/logs/verify_$a.txt" | grep -q '/ 不一致 0$'; then
        if [ "$a" = mirror1 ]; then
            echo "!!! mirror1: 一致の検査が外れた (止める条件 2). ここで止める (本人に知らせる)"
            exit 1
        fi
        echo "!!! $a: 一致の検査が外れた (止める条件 1). 完走も計時もしない"
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
        if [ "$a" = mirror1 ]; then
            echo "!!! mirror1: 完走の答え合わせが外れた (止める条件 2). ここで止める (本人に知らせる)"
            exit 1
        fi
        echo "!!! $a: 完走の答え合わせが外れた (止める条件 1). 計時しない"
        continue
    fi
    ARMS+=("$a")
done
"$HERE/run_bench.sh" "${ARMS[@]}"
"$HERE/run_counts.sh"
cp "$ROOT/runs/perf_34/dump/blocks/index.tsv" "$HERE/logs/blocks_index.tsv"
printf '%s\n' "${ARMS[@]}" > "$HERE/logs/arms_ok.txt"
echo "=== mirror1_keep 完了 $(date --iso-8601=seconds) ==="
