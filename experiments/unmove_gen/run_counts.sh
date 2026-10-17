#!/bin/bash
# ベンチの入力での, 1局面あたりの候補の数と戻した数 (実験 unmove_gen。記録試行ではない). 計時はしない
#
#   run_counts.sh       (mirror1 が一致の検査を通ったときだけ run_all.sh が呼ぶ)
#
# ベンチと同じ入力 (order の u_*.bin 174 個と random の sample_unmove.bin) を, ファイルごとに
# verify multiset <base> <mirror1> に通し, 最後から2行目 (候補の数と, 式で出した戻した数) を
# logs/counts.tsv に残す. 戻した数の式は verify.c の頭の注記 (鏡像の q から戻した候補が q から戻した候補の
# 鏡像になること. それは全局面の一致の検査で確かめてある). base と bb_unmove は「q と鏡像の両方から」,
# mirror1 は「q だけから」
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
W="$ROOT/runs/unmove_gen"
BLOCKS="$ROOT/runs/perf_34/dump/blocks"
SAMPLE="$ROOT/runs/perf_34/bench/sample_unmove.bin"
OUT="$HERE/logs/counts.tsv"
mapfile -t UL < <(find "$BLOCKS" -name 'u_*.bin' | LC_ALL=C sort)
printf 'input\tfile\tn\tsym_q\tcand_base\tcand_mirror1\traw_both\traw_one\n' > "$OUT"
echo "=== 開始 counts $(date --iso-8601=seconds) ==="
for f in "${UL[@]}" "$SAMPLE"; do
    inp=order
    [ "$f" = "$SAMPLE" ] && inp=random
    "$W/verify" multiset "$W/arm_base/animal_shogi.so" "$W/arm_mirror1/animal_shogi.so" "$f" > "$W/count_out.txt"
    tail -2 "$W/count_out.txt" | python3 -c '
import re, sys
a, b = sys.stdin.read().splitlines()
m = re.match(r"q が左右対称な局面 (\d+) / 候補 base (\d+)・腕 (\d+) / 戻した数 \(式\) q と鏡像の両方から (\d+)・q だけから (\d+)", a)
n = re.match(r"局面 (\d+) / 不一致 0$", b)
if not m or not n:
    sys.exit("verify の出力が読めないか, 不一致がある: " + a + " / " + b)
print("\t".join([sys.argv[1], sys.argv[2], n.group(1), *m.groups()]))
' "$inp" "$(basename "$f")" >> "$OUT"
done
echo "=== 完了 counts $(date --iso-8601=seconds) ==="
