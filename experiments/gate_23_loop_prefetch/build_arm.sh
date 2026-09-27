#!/bin/bash
# 腕のソースを組んで, その実装の Makefile でビルドする (門番 #23。記録試行ではない)
#
#   build_arm.sh <old|new> <出力先ディレクトリ>
#
#   old  impl/22_in_memory
#   new  impl/23_loop_prefetch (retreatStep() に2段の先読み)
#
# 2腕の差は C の retreatStep() だけ (tests/test_impl_23_loop_prefetch.py が固定している).
# .py / .h / Makefile はバイト同一 (gcc -O2). フラグを門番側に書かない
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
ARM="${1:?腕を指定すること (old|new)}"
DST="${2:?出力先を指定すること}"
case "$ARM" in
    old) SRC="$ROOT/impl/22_in_memory" ;;
    new) SRC="$ROOT/impl/23_loop_prefetch" ;;
    *)   echo "腕は old か new: $ARM" >&2; exit 2 ;;
esac
mkdir -p "$DST"
cp "$SRC/animal_shogi.c" "$SRC/animal_shogi.h" "$SRC/animal_shogi.py" "$SRC/Makefile" "$DST/"
(cd "$DST" && make --quiet animal_shogi.so)
echo "$ARM: ${SRC#"$ROOT"/}"
