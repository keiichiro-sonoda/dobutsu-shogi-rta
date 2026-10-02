#!/bin/bash
# 腕のソースを写して, その実装の Makefile でビルドする (門番 #29。記録試行ではない)
#
#   build_arm.sh <old|new> <出力先ディレクトリ>
#
#   old  impl/28_march_native
#   new  impl/29_static_const_moves (impl/28 の移動表4本を static const にしたもの)
#
# 2腕の差が移動表4本の static const と moves の型 (と .h の extern 宣言) だけであること,
# .py と Makefile がバイト同一であることは tests/test_impl_29_static_const_moves.py が固定している.
# どちらもその実装の Makefile でビルドする (自前の gcc 行を書かない)
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
ARM="${1:?腕を指定すること (old|new)}"
DST="${2:?出力先を指定すること}"
case "$ARM" in
    old) SRC="$ROOT/impl/28_march_native" ;;
    new) SRC="$ROOT/impl/29_static_const_moves" ;;
    *)   echo "腕は old か new: $ARM" >&2; exit 2 ;;
esac
mkdir -p "$DST"
cp "$SRC/animal_shogi.c" "$SRC/animal_shogi.h" "$SRC/animal_shogi.py" "$SRC/Makefile" "$DST/"
(cd "$DST" && make --quiet animal_shogi.so)
echo "$ARM: ${SRC#"$ROOT"/} (so sha256 $(sha256sum "$DST/animal_shogi.so" | cut -c1-12))"
