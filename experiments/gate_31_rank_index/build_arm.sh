#!/bin/bash
# 腕のソースを組んで, その実装の Makefile でビルドする (門番 #31。記録試行ではない)
#
#   build_arm.sh <old|new> <出力先ディレクトリ>
#
#   old  impl/30_rank_seen
#   new  impl/30_rank_seen ＋ patches/rank_index.patch (後退解析の索引を「ランク -> 連番」の対応表にしたもの)
#
# ⚠️ 門番を回したときの new は impl/31_rank_index だった. 同点で記録にしなかったので, その版を
#    このパッチにして impl/ から外した (番号 31 は欠番). パッチを当てた .so は, 門番を回したときの
#    new と同じ sha256 (14effc10ba75) になる (コメントは .so に入らない).
#    パッチは fuzz なしで当て, 衝突したら止める. どちらもその実装の Makefile でビルドする
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ARM="${1:?腕を指定すること (old|new)}"
DST="${2:?出力先を指定すること}"
SRC="$ROOT/impl/30_rank_seen"
case "$ARM" in
    old) PATCHES=() ;;
    new) PATCHES=("$HERE/patches/rank_index.patch") ;;
    *)   echo "腕は old か new: $ARM" >&2; exit 2 ;;
esac
mkdir -p "$DST"
cp "$SRC/animal_shogi.c" "$SRC/animal_shogi.h" "$SRC/animal_shogi.py" "$SRC/Makefile" "$DST/"
for p in "${PATCHES[@]}"; do
    patch --quiet --forward --fuzz=0 --no-backup-if-mismatch -p1 -d "$DST" < "$p"
done
(cd "$DST" && make --quiet animal_shogi.so)
DESC="${SRC#"$ROOT"/}"
[ "${#PATCHES[@]}" -eq 0 ] || DESC="$DESC + rank_index.patch"
echo "$ARM: $DESC (so sha256 $(sha256sum "$DST/animal_shogi.so" | cut -c1-12))"
