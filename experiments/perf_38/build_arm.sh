#!/bin/bash
# 腕のソースを写し, perf の切り替えのパッチを当ててビルドする (実験 perf_38。記録試行ではない)
#
#   build_arm.sh <r37|r38> <出力先ディレクトリ>
#
#   r37   impl/37_mirror1 (.so の sha256 の先頭 1730c3fdcb0b)
#   r38   impl/38_precheck (.so の sha256 の先頭 a712601ee2c9)
#
# 実装の写しに experiments/perf_34/patches/perf_ctl.patch (animal_shogi.py だけ. F1 の境界で perf の数えを
# 止めたり動かしたりする) を写さずに当てる. .py は #34〜#38 でバイト同一なので, そのまま当たる.
# C・ヘッダ・Makefile・hot_layout.ld は実装とバイト同一で, .so はその実装の Makefile でビルドし,
# 記録の .so とバイト一致することを見る (止める条件 2).
# 行に寄せるために, gcc 行に -g を足した .so を出力先/g/ に作り, .text.hot_layout と .text の中身と番地・大きさが
# -g なしと同じことを確かめる (perf record は -g なしの .so で取り, 番地 → 行の対応にだけ -g の .so を使う).
# PERF_CTL_* を渡さなければパッチは何もしない
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
ARM="${1:?腕を指定すること (r37|r38)}"
DST="${2:?出力先を指定すること}"
case "$ARM" in
    r37) SRC="$ROOT/impl/37_mirror1"; WANT=1730c3fdcb0b ;;
    r38) SRC="$ROOT/impl/38_precheck"; WANT=a712601ee2c9 ;;
    *) echo "腕は r37 / r38: $ARM" >&2; exit 2 ;;
esac
mkdir -p "$DST/g"
find "$SRC" -maxdepth 1 -type f -exec cp {} "$DST/" \;
patch --quiet --fuzz=0 -d "$DST" -p1 < "$ROOT/experiments/perf_34/patches/perf_ctl.patch"
for f in animal_shogi.c animal_shogi.h Makefile hot_layout.ld; do
    cmp -s "$SRC/$f" "$DST/$f" || { echo "!!! $f が ${SRC#"$ROOT"/} と違う" >&2; exit 3; }
done
(cd "$DST" && make --quiet animal_shogi.so)
SHA=$(sha256sum "$DST/animal_shogi.so" | cut -c1-12)
if [ "$SHA" != "$WANT" ]; then
    echo "!!! $ARM の .so が記録の .so と違う ($SHA, 記録は $WANT. 止める条件 2)" >&2
    exit 3
fi
cp "$DST/animal_shogi.c" "$DST/animal_shogi.h" "$DST/hot_layout.ld" "$DST/g/"
LINE=$(grep -E '^\s+gcc ' "$SRC/Makefile" | sed -e 's/^\s*//')
(cd "$DST/g" && eval "${LINE/ -O2 / -O2 -g }")
for sec in .text.hot_layout .text; do
    objcopy -O binary --only-section="$sec" "$DST/animal_shogi.so" "$DST/sec.bin"
    objcopy -O binary --only-section="$sec" "$DST/g/animal_shogi.so" "$DST/g/sec.bin"
    cmp -s "$DST/sec.bin" "$DST/g/sec.bin" || { echo "!!! $ARM: $sec の中身が -g の有無で違う" >&2; exit 3; }
    A=$(readelf -SW "$DST/animal_shogi.so" | awk -v s="$sec" '$2 == s {print $4, $6}')
    B=$(readelf -SW "$DST/g/animal_shogi.so" | awk -v s="$sec" '$2 == s {print $4, $6}')
    [ -n "$A" ] && [ "$A" = "$B" ] || { echo "!!! $ARM: $sec の番地か大きさが -g の有無で違う" >&2; exit 3; }
done
rm -f "$DST/sec.bin" "$DST/g/sec.bin"
echo "$ARM: ${SRC#"$ROOT"/} (so sha256 $SHA, py sha256 $(sha256sum "$DST/animal_shogi.py" | cut -c1-12), -g の .text は一致)"
