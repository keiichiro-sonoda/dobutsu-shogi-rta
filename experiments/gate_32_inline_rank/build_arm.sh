#!/bin/bash
# 腕のソースを写して, その実装の Makefile でビルドする (門番 #32。記録試行ではない)
#
#   build_arm.sh <old|new> <出力先ディレクトリ>
#
#   old  impl/30_rank_seen
#   new  impl/32_inline_rank (impl/30 の rankOf() に always_inline を付けたもの. #31 は欠番)
#
# 2腕の差が rankOf() の定義の行 (とその説明のコメント) だけであることは
# tests/test_impl_32_inline_rank.py が固定している. どちらもその実装の Makefile でビルドする
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
ARM="${1:?腕を指定すること (old|new)}"
DST="${2:?出力先を指定すること}"
case "$ARM" in
    old) SRC="$ROOT/impl/30_rank_seen" ;;
    new) SRC="$ROOT/impl/32_inline_rank" ;;
    *)   echo "腕は old か new: $ARM" >&2; exit 2 ;;
esac
mkdir -p "$DST"
cp "$SRC/animal_shogi.c" "$SRC/animal_shogi.h" "$SRC/animal_shogi.py" "$SRC/Makefile" "$DST/"
(cd "$DST" && make --quiet animal_shogi.so)
echo "$ARM: ${SRC#"$ROOT"/} (so sha256 $(sha256sum "$DST/animal_shogi.so" | cut -c1-12))"
