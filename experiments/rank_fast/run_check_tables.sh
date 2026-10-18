#!/bin/bash
# tables.py の「ロードの命令 → 読む表」の決め方を, perf mem の本物のデータの番地と照らす (実験 rank_fast。記録試行ではない)
#
#   run_check_tables.sh
#
# base のベンチ (impl/38_precheck の rankOf. build_bench.sh) の rank_bench を fwd・thr で回し,
# perf record -d -e cpu/mem-loads,ldlat=8/P で読み込み遅延が 8 サイクル以上のロードの標本を取る.
# check_tables.py が命令ごとに本物の番地の表と静的に決めた表を比べ, logs/check_tables.txt に残す. 数は集計に使わない
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
W="$ROOT/runs/rank_fast_tables"
OUT="$HERE/logs/check_tables.txt"
mkdir -p "$W" "$HERE/logs"
"$HERE/build_bench.sh" "$ROOT/impl/38_precheck" "$W/bench_base" > "$W/build.txt"
mapfile -t FWD < <(find "$ROOT/runs/perf_34/dump/blocks" -name 'f1_*.bin' | LC_ALL=C sort)
{
    echo "=== 開始 check_tables $(date --iso-8601=seconds) ==="
    echo "# $(cat "$W/build.txt")"
    perf record -q -d -o "$W/mem.data" -e "cpu/mem-loads,ldlat=8/P" -- \
        numactl --cpunodebind=0 --membind=0 "$W/bench_base/rank_bench" "$W/bench_base/rank.so" fwd thr 100000000 \
        "${FWD[@]}" 2> /dev/null | sed -e 's/^/# rank_bench: /'
    set +e
    perf script -i "$W/mem.data" -F ip,sym,symoff,dso,addr 2> /dev/null \
        | python3 "$HERE/check_tables.py" "$W/bench_base/rank.so"
    RC=$?
    set -e
    echo "=== 完了 check_tables $(date --iso-8601=seconds) (exit=$RC) ==="
} > "$OUT"
cat "$OUT"
exit "$RC"
