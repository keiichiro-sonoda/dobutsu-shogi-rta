#!/bin/bash
# 準備と一致の検査 (実験 unmove_bench。記録試行ではない)
#
#   run_verify.sh [dat/]      既定は #33 本走の dat/
#
# 1. build_so.sh で unmove.so とベンチ本体を作る (runs/unmove_bench/build/)
# 2. prep: 全局面をいまの生成器で分類し, cls.bin と計時用の抜き出しを runs/unmove_bench/ に書く
# 3. verify: 全局面で, 前任の多重集合を前向きと逆向きで突き合わせる
# 出力は logs/build.txt, logs/prep.txt, logs/verify.txt. 大きいファイル (cls.bin・抜き出し) は git に入れない
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
DAT="${1:-$ROOT/runs/20261004-091929_33_hot_layout/dat}"
OUT="$ROOT/runs/unmove_bench"
mkdir -p "$OUT" "$HERE/logs"
rm -rf "$OUT/build"
"$HERE/build_so.sh" "$OUT/build" | tee "$HERE/logs/build.txt"
"$OUT/build/bench" prep "$OUT/build/unmove.so" "$DAT" "$OUT" | tee "$HERE/logs/prep.txt"
set +e
"$OUT/build/bench" verify "$OUT/build/unmove.so" "$DAT" "$OUT" | tee "$HERE/logs/verify.txt"
RC=${PIPESTATUS[0]}
set -e
echo "verify の終了コード: $RC" | tee -a "$HERE/logs/verify.txt"
exit "$RC"
