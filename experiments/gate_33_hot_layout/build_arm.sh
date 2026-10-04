#!/bin/bash
# 腕のソースを写して, その実装の Makefile でビルドする (門番 #33。記録試行ではない)
#
#   build_arm.sh <腕> <出力先ディレクトリ>
#
#   old            impl/32_inline_rank
#   new            impl/33_hot_layout (C は #32 とバイト同一. Makefile と hot_layout.ld で置き場所を固定)
#   old_pad<N>     old の .c の頭 (#include "animal_shogi.h" の直後) に, N バイトの nop を持つだけの
#   new_pad<N>     関数を1つ足したもの. 置き場所の振れを測る本 (run_pad.sh) だけが使う. 判定には使わない
#
# 詰め物の関数は呼ばれないので, 出力は変わらない (run_one.sh が毎本バイト比較で確かめる).
# 足し方は tests/test_impl_33_hot_layout.py の padded(..., "top", N) と同じ.
# 2腕の差が Makefile と hot_layout.ld だけであることは, そのテストが固定している
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
ARM="${1:?腕を指定すること (old|new|old_pad<N>|new_pad<N>)}"
DST="${2:?出力先を指定すること}"
PAD=""
case "$ARM" in
    old | old_pad*) SRC="$ROOT/impl/32_inline_rank" ;;
    new | new_pad*) SRC="$ROOT/impl/33_hot_layout" ;;
    *) echo "腕は old / new / old_pad<N> / new_pad<N>: $ARM" >&2; exit 2 ;;
esac
case "$ARM" in
    *_pad*)
        PAD="${ARM#*_pad}"
        [[ "$PAD" =~ ^[0-9]+$ ]] || { echo "詰め物の大きさが数でない: $ARM" >&2; exit 2; }
        ;;
esac
mkdir -p "$DST"
find "$SRC" -maxdepth 1 -type f -exec cp {} "$DST/" \;
if [ -n "$PAD" ]; then
    ANCHOR='#include "animal_shogi.h"'
    [ "$(grep -cxF "$ANCHOR" "$DST/animal_shogi.c")" = 1 ] || { echo "$ANCHOR が1行でない" >&2; exit 2; }
    LINE="__attribute__((used, noinline)) void layoutPad(void) { __asm__ volatile(\".skip $PAD, 0x90\"); }"
    awk -v a="$ANCHOR" -v l="$LINE" '{print} $0 == a {print l}' "$DST/animal_shogi.c" > "$DST/animal_shogi.c.new"
    mv "$DST/animal_shogi.c.new" "$DST/animal_shogi.c"
fi
(cd "$DST" && make --quiet animal_shogi.so)
echo "$ARM: ${SRC#"$ROOT"/}${PAD:+ + 詰め物 $PAD バイト} (so sha256 $(sha256sum "$DST/animal_shogi.so" | cut -c1-12))"
