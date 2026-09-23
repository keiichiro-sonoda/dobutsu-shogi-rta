#!/bin/bash
# 腕のソースを組んで, その実装の Makefile でビルドする (門番 #22。記録試行ではない)
#
#   build_arm.sh <old|chunk|whole> <出力先ディレクトリ>
#
#   old    impl/21_hugepages そのまま (中間ファイルで受け渡す)
#   chunk  impl/22_in_memory そのまま (待ち行列を BOARD_NUM_MAX ずつに区切る. 門番で採った腕)
#   whole  impl/22_in_memory ＋ patches/whole.patch (待ち行列を区切らない)
#
# chunk と whole の差は queuePush() の1関数だけ (tests/test_impl_22_in_memory.py が固定している).
# 門番を回した時点 (83924f5) では impl/22_in_memory が whole で, chunk をパッチで組んでいた.
# 採った腕で impl/22_in_memory を確定させたので向きを入れ替えた. 組む2腕のコードは同じ
# (whole.patch を当てると, 回した時点の impl/22_in_memory とバイト一致する).
# .c / .h / Makefile は3腕ともバイト同一 (gcc -O2). フラグを門番側に書かない
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ARM="${1:?腕を指定すること (old|chunk|whole)}"
DST="${2:?出力先を指定すること}"
case "$ARM" in
    old)         SRC="$ROOT/impl/21_hugepages" ;;
    chunk|whole) SRC="$ROOT/impl/22_in_memory" ;;
    *)           echo "腕は old / chunk / whole のどれか: $ARM" >&2; exit 2 ;;
esac
mkdir -p "$DST"
cp "$SRC/animal_shogi.c" "$SRC/animal_shogi.h" "$SRC/animal_shogi.py" "$SRC/Makefile" "$DST/"
WHAT="${SRC#"$ROOT"/}"
if [ "$ARM" = whole ]; then
    patch --forward --fuzz=0 --no-backup-if-mismatch --quiet -p1 -d "$DST" \
        < "$HERE/patches/whole.patch"
    WHAT="$WHAT + patches/whole.patch"
fi
(cd "$DST" && make --quiet animal_shogi.so)
echo "$ARM: $WHAT"
