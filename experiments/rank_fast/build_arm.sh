#!/bin/bash
# impl/38_precheck を写し, perf の切り替えのパッチを当ててビルドする (実験 rank_fast の段1。記録試行ではない)
#
#   build_arm.sh <出力先ディレクトリ>
#
# experiments/perf_38/build_arm.sh の r38 の腕と同じ作りで, 当てるパッチが2つになった:
#   1. experiments/perf_34/patches/perf_ctl.patch (写さずに当てる. F1 と U_loop の境界で perf の数えを止めたり動かしたりする)
#   2. patches/u_draw_ctl.patch (1 の上に当てる. U_draw の境界にも同じ enable / disable を足す)
# どちらも animal_shogi.py だけを変える. C・ヘッダ・Makefile・hot_layout.ld は impl/38_precheck とバイト同一で,
# .so は記録 #38 の .so とバイト一致することを見る (sha256 の先頭 a712601ee2c9).
# 行に寄せるために, gcc 行に -g を足した .so を出力先/g/ に作り, .text.hot_layout と .text の中身と番地・大きさが
# -g なしと同じことを確かめる (perf record は -g なしの .so で取り, 番地 → 行の対応にだけ -g の .so を使う).
# PERF_CTL_* を渡さなければパッチは何もしない
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
DST="${1:?出力先を指定すること}"
SRC="$ROOT/impl/38_precheck"
WANT=a712601ee2c9
mkdir -p "$DST/g"
find "$SRC" -maxdepth 1 -type f -exec cp {} "$DST/" \;
patch --quiet --fuzz=0 -d "$DST" -p1 < "$ROOT/experiments/perf_34/patches/perf_ctl.patch"
patch --quiet --fuzz=0 -d "$DST" -p1 < "$HERE/patches/u_draw_ctl.patch"
for f in animal_shogi.c animal_shogi.h Makefile hot_layout.ld; do
    cmp -s "$SRC/$f" "$DST/$f" || { echo "!!! $f が ${SRC#"$ROOT"/} と違う" >&2; exit 3; }
done
(cd "$DST" && make --quiet animal_shogi.so)
SHA=$(sha256sum "$DST/animal_shogi.so" | cut -c1-12)
if [ "$SHA" != "$WANT" ]; then
    echo "!!! .so が記録 #38 の .so と違う ($SHA, 記録は $WANT)" >&2
    exit 3
fi
cp "$DST/animal_shogi.c" "$DST/animal_shogi.h" "$DST/hot_layout.ld" "$DST/g/"
LINE=$(grep -E '^\s+gcc ' "$SRC/Makefile" | sed -e 's/^\s*//')
(cd "$DST/g" && eval "${LINE/ -O2 / -O2 -g }")
for sec in .text.hot_layout .text; do
    objcopy -O binary --only-section="$sec" "$DST/animal_shogi.so" "$DST/sec.bin"
    objcopy -O binary --only-section="$sec" "$DST/g/animal_shogi.so" "$DST/g/sec.bin"
    cmp -s "$DST/sec.bin" "$DST/g/sec.bin" || { echo "!!! $sec の中身が -g の有無で違う" >&2; exit 3; }
    A=$(readelf -SW "$DST/animal_shogi.so" | awk -v s="$sec" '$2 == s {print $4, $6}')
    B=$(readelf -SW "$DST/g/animal_shogi.so" | awk -v s="$sec" '$2 == s {print $4, $6}')
    [ -n "$A" ] && [ "$A" = "$B" ] || { echo "!!! $sec の番地か大きさが -g の有無で違う" >&2; exit 3; }
done
rm -f "$DST/sec.bin" "$DST/g/sec.bin"
echo "r38: ${SRC#"$ROOT"/} (so sha256 $SHA, py sha256 $(sha256sum "$DST/animal_shogi.py" | cut -c1-12), -g の .text は一致)"
