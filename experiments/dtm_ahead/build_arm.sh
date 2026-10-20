#!/bin/bash
# 腕のソースを写して, その実装の Makefile でビルドする (実験 dtm_ahead。記録試行ではない)
#
#   build_arm.sh <base|ahead1> <出力先ディレクトリ> [perf]
#
#   base     impl/39_rank_lean のまま (.so の sha256 の先頭 7b76775652aa. 記録 #39 の .so とバイト一致することを見る)
#   ahead1   impl/39_rank_lean の写しに patches/ahead1.patch を当てる (unmoveStep の中だけ. g_dtm の先読みを1局面先にする)
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
ARM="${1:?腕を指定すること (base|ahead1)}"
DST="${2:?出力先を指定すること}"
MODE="${3:-}"
SRC="$ROOT/impl/39_rank_lean"
case "$ARM" in
    base) WANT=7b76775652aa ;;
    ahead1) WANT=db2ea39f8828 ;;
    *) echo "腕は base / ahead1: $ARM" >&2; exit 2 ;;
esac
mkdir -p "$DST"
find "$SRC" -maxdepth 1 -type f -exec cp {} "$DST/" \;
if [ "$ARM" = ahead1 ]; then
    patch --quiet --fuzz=0 -d "$DST" -p1 < "$HERE/patches/ahead1.patch"
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
echo "$ARM: ${SRC#"$ROOT"/}$([ "$ARM" = ahead1 ] && echo " + ahead1.patch")$([ "$MODE" = perf ] && echo " + perf_ctl.patch") (so sha256 $SHA, py sha256 $(sha256sum "$DST/animal_shogi.py" | cut -c1-12))"
