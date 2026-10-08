#!/bin/bash
# 腕のソースを写して, その実装の Makefile でビルドする (門番 #34。記録試行ではない)
#
#   build_arm.sh <old|new> <出力先ディレクトリ>
#
#   old   impl/33_hot_layout
#   new   impl/34_unmove (後退解析を「一手前を直接作る」作りに替えた. 全探索は準備の配列を書く)
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
ARM="${1:?腕を指定すること (old|new)}"
DST="${2:?出力先を指定すること}"
case "$ARM" in
    old) SRC="$ROOT/impl/33_hot_layout" ;;
    new) SRC="$ROOT/impl/34_unmove" ;;
    *) echo "腕は old / new: $ARM" >&2; exit 2 ;;
esac
mkdir -p "$DST"
find "$SRC" -maxdepth 1 -type f -exec cp {} "$DST/" \;
(cd "$DST" && make --quiet animal_shogi.so)
echo "$ARM: ${SRC#"$ROOT"/} (so sha256 $(sha256sum "$DST/animal_shogi.so" | cut -c1-12))"
