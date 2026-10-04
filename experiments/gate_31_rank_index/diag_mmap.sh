#!/bin/bash
# 止める条件3 に掛かったときに, malloc の mmap のしきい値の副作用かを調べる診断
# (門番 #31。記録試行ではない. 判定には使わない. 門番 #30 の同名のスクリプトの写し)
#
#   diag_mmap.sh <old|new> <ラベル>
#
# glibc の malloc は, mmap で確保した塊を free すると mmap のしきい値をその大きさ (最大 32 MiB) に
# 引き上げる. 大きな塊の free の有無や時期が腕で違うと, そのあとの中くらいの配列がヒープから
# 取られるか毎回 mmap されるかが変わり, 触っていない段が動きうる (門番 #30 の F5・F6).
# 確かめ方: しきい値を 32 MiB に固定して (GLIBC_TUNABLES. 固定すると動的な引き上げも止まる) 完走を1本ずつ
# 回し, 動いた段が2腕で揃うかを見る. 生ログは logs/diag/ に置く
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$HERE/lib.sh"
ARM="${1:?腕を指定すること (old|new)}"
LABEL="${2:?ラベルを指定すること}"
W="$ROOT/runs/exp_g31_diag_$LABEL"
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
