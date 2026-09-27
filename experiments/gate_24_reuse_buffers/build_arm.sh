#!/bin/bash
# 腕のソースを組んで, その実装の Makefile でビルドする (門番 #24。記録試行ではない)
#
#   build_arm.sh <old|new> <出力先ディレクトリ>
#
#   old  impl/23_loop_prefetch
#   new  impl/24_reuse_buffers (展開の受け皿を使い回す)
#
# 2腕の差は animal_shogi.py の searchNext() (F1) だけ (tests/test_impl_24_reuse_buffers.py が固定している).
# C / .h / Makefile はバイト同一 (gcc -O2) なので, .so もバイト同一のはず. フラグを門番側に書かない
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
ARM="${1:?腕を指定すること (old|new)}"
DST="${2:?出力先を指定すること}"
case "$ARM" in
    old) SRC="$ROOT/impl/23_loop_prefetch" ;;
    new) SRC="$ROOT/impl/24_reuse_buffers" ;;
    *)   echo "腕は old か new: $ARM" >&2; exit 2 ;;
esac
mkdir -p "$DST"
cp "$SRC/animal_shogi.c" "$SRC/animal_shogi.h" "$SRC/animal_shogi.py" "$SRC/Makefile" "$DST/"
(cd "$DST" && make --quiet animal_shogi.so)
echo "$ARM: ${SRC#"$ROOT"/} (so sha256 $(sha256sum "$DST/animal_shogi.so" | cut -c1-12))"
