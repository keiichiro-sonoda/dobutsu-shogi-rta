#!/bin/bash
# 段2の一致の検査 (実験 rank_fast。記録試行ではない). 計時はしない
#
#   run_verify.sh <base の animal_shogi.so> <腕>=<腕の animal_shogi.so> ...
#
# 入力は #38 本走の dat/ の全ファイル (到達可能な全 246,803,167 局面. 読むだけで, 中へ cd しない).
# 使う前に, dat/ の md5 一覧の sha256 が results/38_precheck/bytecompare.txt の #38 の値と同じことを見る.
# verify.c で, 腕ごとに base と rankBoard の値を (a) 全局面 (b) 全局面を q にした unmoveCandidates の全候補
# (c) 乱数の正しい盤 1 億個 で比べる. 結果は logs/verify_<腕>.txt (不一致は最初の 20 個まで. 最後の行に数).
# 1つでも外れた腕は計時しない (止める条件 2. run_stage2.sh が見る)
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
DAT="$ROOT/runs/20261018-072527_38_precheck/dat"
W="$ROOT/runs/rank_fast/s2"
[ -d "$DAT" ] || { echo "#38 本走の dat/ が無い: $DAT" >&2; exit 2; }
BASE="${1:?base の .so を渡すこと}"
shift
mkdir -p "$W" "$HERE/logs"
WANT=$(sed -nE 's/^\s+#38 ([0-9a-f]{64})$/\1/p' "$ROOT/results/38_precheck/bytecompare.txt")
GOT=$(python3 "$HERE/check.py" answer "$DAT" | sed -nE 's/^md5 一覧の sha256: ([0-9a-f]{64}) .*/\1/p')
echo "入力の dat/ の md5 一覧の sha256: $GOT (#38 本走 ${WANT:-?})"
if [ -z "$WANT" ] || [ "$GOT" != "$WANT" ]; then
    echo "!!! 入力の dat/ が #38 本走と違う" >&2
    exit 2
fi
gcc -O2 -Wall -Wextra "$HERE/verify.c" -o "$W/verify" -ldl
mapfile -t FILES < <(find "$DAT" -name '*.bin' | LC_ALL=C sort)
echo "入力: #38 本走の dat/ の ${#FILES[@]} ファイル"
RC=0
for spec in "$@"; do
    a=${spec%%=*}
    so=${spec#*=}
    {
        echo "=== 開始 verify_$a $(date --iso-8601=seconds) ==="
        echo "# base $(sha256sum "$BASE" | cut -c1-12) / $a $(sha256sum "$so" | cut -c1-12)"
        set +e
        "$W/verify" "$BASE" "$so" 100000000 "${FILES[@]}"
        r=$?
        set -e
        echo "=== 完了 verify_$a $(date --iso-8601=seconds) (exit=$r) ==="
    } > "$HERE/logs/verify_$a.txt"
    tail -2 "$HERE/logs/verify_$a.txt"
    grep -q "(exit=0)" "$HERE/logs/verify_$a.txt" || RC=1
done
exit "$RC"
