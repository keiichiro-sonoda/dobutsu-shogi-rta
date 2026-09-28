#!/bin/bash
# 腕のソースを写して, その実装の Makefile でビルドする (門番 #26。記録試行ではない)
#
#   build_arm.sh <old|new> <出力先ディレクトリ>
#
#   old  impl/25_huge_retreat
#   new  impl/26_inv_bits (impl/25 に experiments/gen_bench/patches/invbits.patch を足したもの)
#
# 2腕の差が invBoard() だけであること (コメントを除く) は tests/test_impl_26_inv_bits.py が固定している.
# .py / .h / Makefile は2腕でバイト同一なので, old にパッチを当てる必要は無い
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
ARM="${1:?腕を指定すること (old|new)}"
DST="${2:?出力先を指定すること}"
case "$ARM" in
    old) SRC="$ROOT/impl/25_huge_retreat" ;;
    new) SRC="$ROOT/impl/26_inv_bits" ;;
    *)   echo "腕は old か new: $ARM" >&2; exit 2 ;;
esac
mkdir -p "$DST"
cp "$SRC/animal_shogi.c" "$SRC/animal_shogi.h" "$SRC/animal_shogi.py" "$SRC/Makefile" "$DST/"
(cd "$DST" && make --quiet animal_shogi.so)
echo "$ARM: ${SRC#"$ROOT"/} (so sha256 $(sha256sum "$DST/animal_shogi.so" | cut -c1-12))"
