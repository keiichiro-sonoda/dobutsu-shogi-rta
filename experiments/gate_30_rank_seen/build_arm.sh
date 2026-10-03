#!/bin/bash
# 腕のソースを写して, その実装の Makefile でビルドする (門番 #30。記録試行ではない)
#
#   build_arm.sh <old|new> <出力先ディレクトリ>
#
#   old  impl/28_march_native
#   new  impl/30_rank_seen (impl/28 の発見済み表を, ランクで引く到達済みビット表に替えたもの. #29 は欠番)
#
# 2腕の差が発見済み集合の節 (.c) とその宣言 (.h) だけであること, .py と Makefile がバイト同一である
# ことは tests/test_impl_30_rank_seen.py が固定している. どちらもその実装の Makefile でビルドする
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
ARM="${1:?腕を指定すること (old|new)}"
DST="${2:?出力先を指定すること}"
case "$ARM" in
    old) SRC="$ROOT/impl/28_march_native" ;;
    new) SRC="$ROOT/impl/30_rank_seen" ;;
    *)   echo "腕は old か new: $ARM" >&2; exit 2 ;;
esac
mkdir -p "$DST"
cp "$SRC/animal_shogi.c" "$SRC/animal_shogi.h" "$SRC/animal_shogi.py" "$SRC/Makefile" "$DST/"
(cd "$DST" && make --quiet animal_shogi.so)
echo "$ARM: ${SRC#"$ROOT"/} (so sha256 $(sha256sum "$DST/animal_shogi.so" | cut -c1-12))"
