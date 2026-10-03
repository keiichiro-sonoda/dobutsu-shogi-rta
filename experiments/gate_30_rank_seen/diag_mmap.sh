#!/bin/bash
# 止める条件3 (F6 +0.61 秒) の原因を調べる診断 (門番 #30。記録試行ではない. 判定には使わない)
#
#   diag_mmap.sh <old|new> <ラベル>
#
# 仮説: glibc の malloc は, mmap で確保した塊を free すると mmap のしきい値をその大きさ (最大 32 MiB) に
# 引き上げる. old (#28) は発見済み表を倍々に作り直すたびに古い表を free するので, しきい値が上がり,
# 後の F5・F6 の中くらいの配列がヒープから取られて, 既にページの付いた領域を使い回す.
# new (#30) はビット表を free しないので, しきい値が既定 (128 KiB) のままで, F5・F6 の配列が毎回
# 新しく mmap されてページのフォルトをやり直す.
# 確かめ方: しきい値を 32 MiB に固定して (GLIBC_TUNABLES. 固定すると動的な引き上げも止まる) 完走を1本ずつ
# 回し, F5・F6 の minor fault と時間が2腕で揃うかを見る. 生ログは logs/diag/ に置く
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$HERE/lib.sh"
ARM="${1:?腕を指定すること (old|new)}"
LABEL="${2:?ラベルを指定すること}"
W="$ROOT/runs/exp_g30_diag_$LABEL"
OUT="$HERE/logs/diag"
TUNE="glibc.malloc.mmap_threshold=33554432"
[ -e "$W" ] && { echo "$W が残っている" >&2; exit 2; }
mkdir -p "$OUT" "$W/dat" "$W/kaiseki_log"
FREE0=$(hugefree_gib 0)
echo "--- $LABEL: ノード0の 2 MiB 以上の空きブロック $FREE0 GiB ---"
awk -v have="$FREE0" 'BEGIN { exit !(have != "-" && have + 0 >= 16) }' || { echo "空きが足りない" >&2; exit 4; }
BUILD=$("$HERE/build_arm.sh" "$ARM" "$W")
echo "=== 診断 $LABEL ($BUILD) GLIBC_TUNABLES=$TUNE $(date --iso-8601=seconds) ==="
(cd "$W" && GLIBC_TUNABLES="$TUNE" /usr/bin/time -v numactl --cpunodebind=0 --membind=0 \
    python3 ./animal_shogi.py > stdout.txt 2> time.txt)
python3 "$ROOT/tools/verify_log.py" "$W/kaiseki_log/kaizenkaiseki1.txt" | tail -1
cp "$W/kaiseki_log/forward_summary.tsv" "$OUT/${LABEL}_forward_summary.tsv"
cp "$W/kaiseki_log/retreat_summary.tsv" "$OUT/${LABEL}_retreat_summary.tsv"
cp "$W/time.txt" "$OUT/${LABEL}_time.txt"
rm -rf "$W"
echo "=== 完了 $LABEL $(date --iso-8601=seconds) ==="
