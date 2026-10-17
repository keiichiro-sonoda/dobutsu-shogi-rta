#!/bin/bash
# 腕のソースを写して, その実装の Makefile でビルドする (門番 #37。記録試行ではない)
#
#   build_arm.sh <old|new> <出力先ディレクトリ>
#
#   old   impl/36_bb_unmove
#   new   impl/37_mirror1 (逆向きの生成器で鏡像を1回にした: q だけから手を戻して正規化する. ほかは #36 と同じ)
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
ARM="${1:?腕を指定すること (old|new)}"
DST="${2:?出力先を指定すること}"
case "$ARM" in
    old) SRC="$ROOT/impl/36_bb_unmove" ;;
    new) SRC="$ROOT/impl/37_mirror1" ;;
    *) echo "腕は old / new: $ARM" >&2; exit 2 ;;
esac
mkdir -p "$DST"
find "$SRC" -maxdepth 1 -type f -exec cp {} "$DST/" \;
(cd "$DST" && make --quiet animal_shogi.so)
echo "$ARM: ${SRC#"$ROOT"/} (so sha256 $(sha256sum "$DST/animal_shogi.so" | cut -c1-12))"
