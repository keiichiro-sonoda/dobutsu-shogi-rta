#!/bin/bash
# 準備と, 一致の検査 (実験 attack_count。記録試行ではない)
#
#   run_count.sh [dat/]      既定は #33 本走の dat/
#
# 1. build_so.sh で attack.so とベンチ本体を作る (runs/attack_count/build/)
# 2. prep: 全局面をいまの生成器で分類し, cls.bin と計時用の抜き出しを runs/attack_count/ に書く
# 3. count: 全局面で B1′ (相手の利きの一覧) の戻り値がいまの生成器と同じか, 全未知局面で後続の列が順番まで
#    同じで, キャッチ抜きの数が B2 (cls で数え直す) と同じかを見る. 後続の手の種類ごとの件数と食い違いも出す
# 出力は logs/build.txt, logs/prep.txt, logs/count.txt. 開始と終了の時刻は logs/console_count.log
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
DAT="${1:-$ROOT/runs/20261004-091929_33_hot_layout/dat}"
OUT="$ROOT/runs/attack_count"
mkdir -p "$OUT" "$HERE/logs"
if [ -e "$HERE/logs/console_count.log" ]; then
    echo "logs/console_count.log が残っている. 退避してから起動すること" >&2
    exit 2
fi
echo "=== attack_count 準備と突き合わせ 開始 $(date --iso-8601=seconds) ===" > "$HERE/logs/console_count.log"
rm -rf "$OUT/build"
"$HERE/build_so.sh" "$OUT/build" | tee "$HERE/logs/build.txt"
"$OUT/build/bench" prep "$OUT/build/attack.so" "$DAT" "$OUT" | tee "$HERE/logs/prep.txt"
set +e
"$OUT/build/bench" count "$OUT/build/attack.so" "$DAT" "$OUT" | tee "$HERE/logs/count.txt"
RC=${PIPESTATUS[0]}
set -e
echo "count の終了コード: $RC" | tee -a "$HERE/logs/count.txt"
echo "=== attack_count 準備と突き合わせ 終了 $(date --iso-8601=seconds) (count の終了コード $RC) ===" >> "$HERE/logs/console_count.log"
exit "$RC"
