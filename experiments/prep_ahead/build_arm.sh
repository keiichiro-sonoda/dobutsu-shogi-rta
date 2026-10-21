#!/bin/bash
# 腕のソースを写して, その実装の Makefile でビルドする (実験 prep_ahead。記録試行ではない)
#
#   build_arm.sh <base|prep1> <出力先ディレクトリ> [perf]
#
#   base     impl/40_dtm_ahead のまま (.so の sha256 の先頭 db2ea39f8828. 記録 #40 の .so とバイト一致することを見る)
#   prep1    impl/40_dtm_ahead の写しに patches/prep1.patch を当てる (unmoveStep の中だけ. 負けを決める段で g_prep の先読みも1局面先にする)
#
# 3つ目に perf を渡すと, experiments/perf_34/patches/perf_ctl.patch (animal_shogi.py だけ) も当て
# (F1 と U_loop の境界で perf の数えを止めたり動かしたりする. PERF_CTL_* を渡さなければ何もしない),
# gcc 行に -g を足した .so を出力先/g/ に作って, .text.hot_layout と .text の中身と番地・大きさが -g なしと同じことを確かめる
# (perf record は -g なしの .so で取り, 番地 → 行の対応にだけ -g の .so を使う. experiments/perf_39/build_arm.sh と同じ).
# どちらの場合も C・ヘッダ・Makefile・hot_layout.ld 以外 (perf のときは .py も) は実装とバイト同一で,
# .so は perf の有無で変わらない (.py しか変えない) ことを, 腕ごとの sha256 で見る
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ARM="${1:?腕を指定すること (base|prep1)}"
DST="${2:?出力先を指定すること}"
MODE="${3:-}"
SRC="$ROOT/impl/40_dtm_ahead"
case "$ARM" in
    base) WANT=db2ea39f8828 ;;
    prep1) WANT=9680267acfb7 ;;
    *) echo "腕は base / prep1: $ARM" >&2; exit 2 ;;
esac
mkdir -p "$DST"
find "$SRC" -maxdepth 1 -type f -exec cp {} "$DST/" \;
if [ "$ARM" = prep1 ]; then
    patch --quiet --fuzz=0 -d "$DST" -p1 < "$HERE/patches/prep1.patch"
fi
if [ "$MODE" = perf ]; then
    patch --quiet --fuzz=0 -d "$DST" -p1 < "$ROOT/experiments/perf_34/patches/perf_ctl.patch"
fi
for f in animal_shogi.h Makefile hot_layout.ld; do
    cmp -s "$SRC/$f" "$DST/$f" || { echo "!!! $f が ${SRC#"$ROOT"/} と違う" >&2; exit 3; }
done
(cd "$DST" && make --quiet animal_shogi.so)
SHA=$(sha256sum "$DST/animal_shogi.so" | cut -c1-12)
if [ "$SHA" != "$WANT" ]; then
    echo "!!! $ARM の .so が登録した .so と違う ($SHA, 登録は $WANT)" >&2
    exit 3
fi
if [ "$MODE" = perf ]; then
    mkdir -p "$DST/g"
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
fi
echo "$ARM: ${SRC#"$ROOT"/}$([ "$ARM" = prep1 ] && echo " + prep1.patch")$([ "$MODE" = perf ] && echo " + perf_ctl.patch") (so sha256 $SHA, py sha256 $(sha256sum "$DST/animal_shogi.py" | cut -c1-12))"
