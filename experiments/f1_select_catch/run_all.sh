#!/bin/bash
# 実験 f1_select_catch: 組み立て → 一致の検査 → ベンチ → 帰属 (記録試行ではない). 進行は logs/console.log に残す
#
# experiments/bitboard_gen/run_all.sh の写しを4腕にしたもの. 完走は回さない (入力の dat/ とブロックは runs/ に残っている).
# 回す前に kernel.perf_event_paranoid が 1 か, impl/37_mirror1 に __pycache__ が無いか,
# CPU 使用率 (全 CPU) が 3% 以下か (ほかの計算が動いていないか) を確かめる.
# 組むたびに check_asm.py を当て, select と both で狙った3か所に条件分岐が残っていたら止める (止める条件 3).
# build_arm.sh は, 足した関数の記号が残っていたら止める (止める条件 2).
# 一致の検査が1局面でも外れた腕は計時しない. select か precheck が外れたら both も計時しない (止める条件 1)
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
W="$ROOT/runs/f1_select_catch"
mkdir -p "$HERE/logs"
if [ -e "$HERE/logs/console.log" ]; then
    echo "logs/console.log が残っている. 前回と混ざるので, 退避してから起動すること" >&2
    exit 2
fi
if [ -e "$W" ]; then
    echo "前回の $W が残っている. 退避するか消してから起動すること" >&2
    exit 2
fi
if [ -n "$(find "$ROOT/impl/37_mirror1" -name __pycache__)" ]; then
    echo "impl/37_mirror1 に __pycache__ がある. 消してから起動すること" >&2
    exit 2
fi
exec > >(tee "$HERE/logs/console.log") 2>&1
echo "=== f1_select_catch 開始 $(date --iso-8601=seconds) ==="
perf --version
PARANOID=$(cat /proc/sys/kernel/perf_event_paranoid)
echo "kernel.perf_event_paranoid = $PARANOID"
if [ "$PARANOID" != 1 ]; then
    echo "!!! kernel.perf_event_paranoid が 1 でない. 回さない (本人に知らせる. 止める条件 5)" >&2
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
ALL=(base select precheck both)
echo "=== 開始 build $(date --iso-8601=seconds) ==="
for a in "${ALL[@]}"; do
    "$HERE/build_arm.sh" "$a" "$W/arm_$a"
    python3 "$HERE/check_asm.py" "$a" "$W/arm_$a" > "$HERE/logs/asm_$a.txt" \
        || { echo "!!! $a: check_asm.py が通らない (止める条件 3)" >&2; exit 3; }
    "$HERE/build_bench.sh" "$a" "$W/arm_$a" "$W/bench_$a"
done
echo "=== 完了 build $(date --iso-8601=seconds) ==="
"$HERE/run_verify.sh" "$W/arm_base/animal_shogi.so" \
    "select=$W/arm_select/animal_shogi.so" "precheck=$W/arm_precheck/animal_shogi.so" "both=$W/arm_both/animal_shogi.so"
pass() { tail -1 "$HERE/logs/verify_$1.txt" | grep -q '/ 不一致 0$'; }
ARMS=(base)
for a in select precheck; do
    if pass "$a"; then ARMS+=("$a"); else echo "!!! $a: 一致の検査が外れた. 計時しない (止める条件 1)"; fi
done
if pass select && pass precheck && pass both; then
    ARMS+=(both)
else
    echo "!!! both は計時しない (both か, select・precheck のどちらかの一致の検査が外れた. 止める条件 1)"
fi
if [ "${#ARMS[@]}" -eq 1 ]; then
    echo "!!! どの腕も一致の検査を通らなかった. ベンチと帰属に進まない"
    exit 1
fi
echo "計時する腕: ${ARMS[*]}"
"$HERE/run_bench.sh" "${ARMS[@]}"
"$HERE/run_attr.sh" "${ARMS[@]}"
cp "$ROOT/runs/perf_34/dump/blocks/index.tsv" "$HERE/logs/blocks_index.tsv"
cp "$ROOT/experiments/perf_branch_34/logs/split_index.tsv" "$HERE/logs/split_index.tsv"
echo "=== f1_select_catch 完了 $(date --iso-8601=seconds) ==="
