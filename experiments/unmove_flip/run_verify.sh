#!/bin/bash
# 準備と一致の検査 (実験 unmove_flip。記録試行ではない)
#
#   run_verify.sh [dat/]      既定は #33 本走の dat/
#
# 1. build_so.sh で flip.so とベンチ本体を作る (runs/unmove_flip/build/)
# 2. prep: cls.bin と計時用の抜き出しを runs/unmove_flip/ に書く (unmove_prune と同じ中身. sha256 を残す)
# 3. verify: 全到達局面で, 反転を1回にした版を絞った版と突き合わせる (bench.c の verify)
# 出力は logs/build.txt, logs/prep.txt, logs/verify.txt. 開始と終了の時刻は logs/console_verify.log
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
DAT="${1:-$ROOT/runs/20261004-091929_33_hot_layout/dat}"
OUT="$ROOT/runs/unmove_flip"
mkdir -p "$OUT" "$HERE/logs"
if [ -e "$HERE/logs/console_verify.log" ]; then
    echo "logs/console_verify.log が残っている. 退避してから起動すること" >&2
    exit 2
fi
echo "=== unmove_flip 準備と一致の検査 開始 $(date --iso-8601=seconds) ===" > "$HERE/logs/console_verify.log"
rm -rf "$OUT/build"
"$HERE/build_so.sh" "$OUT/build" | tee "$HERE/logs/build.txt"
"$OUT/build/bench" prep "$OUT/build/flip.so" "$DAT" "$OUT" | tee "$HERE/logs/prep.txt"
(cd "$OUT" && sha256sum cls.bin sample_*.bin) | tee -a "$HERE/logs/prep.txt"
set +e
"$OUT/build/bench" verify "$OUT/build/flip.so" "$DAT" "$OUT" | tee "$HERE/logs/verify.txt"
RC=${PIPESTATUS[0]}
set -e
echo "verify の終了コード: $RC" | tee -a "$HERE/logs/verify.txt"
echo "=== unmove_flip 準備と一致の検査 終了 $(date --iso-8601=seconds) (verify の終了コード $RC) ===" >> "$HERE/logs/console_verify.log"
exit "$RC"
