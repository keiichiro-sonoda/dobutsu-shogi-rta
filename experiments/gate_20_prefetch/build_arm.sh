#!/bin/bash
# 腕のソースを写して, その実装の Makefile でビルドする (門番 #20。記録試行ではない)
#
#   build_arm.sh <old|new> <出力先ディレクトリ>
#
#   old  impl/19_c_gather
#   new  impl/20_prefetch (先読み4か所 + moves = NULL)
#
# フラグを門番側に書かない. 両腕とも実装の Makefile (gcc -O2) をそのまま使う
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
ARM="${1:?腕を指定すること (old|new)}"
DST="${2:?出力先を指定すること}"
case "$ARM" in
    old) SRC="$ROOT/impl/19_c_gather" ;;
    new) SRC="$ROOT/impl/20_prefetch" ;;
    *)   echo "腕は old か new: $ARM" >&2; exit 2 ;;
esac
mkdir -p "$DST"
cp "$SRC/animal_shogi.py" "$SRC/animal_shogi.c" "$SRC/animal_shogi.h" "$SRC/Makefile" "$DST/"
(cd "$DST" && make --quiet animal_shogi.so)
echo "$ARM: ${SRC#"$ROOT"/} (Makefile のまま)"
