#!/bin/bash
# 生成器の版を, 本番と同じ Makefile (gcc -O2 ... -Wall -fPIC -shared) で .so にする (実験 gen_bench。記録試行ではない)
#
#   build_so.sh <base|B|A|AB> <出力先ディレクトリ>
#
#   base  impl/25_huge_retreat/animal_shogi.c のまま
#   B     ＋ patches/invbits.patch     (ループを使わない invBoard)
#   A     ＋ patches/catchfirst.patch  (キャッチの先行判定. nextBoardCatchFirst を足す)
#   AB    ＋ 両方
#
# ⚠️ ベンチ本体は .so を dlopen して呼ぶ. .c ごと1つの実行ファイルにすると, -fPIC -shared で起きている
#    「同じ .so の中の normalBoard / invBoard の呼び出しもインライン展開されない」条件が変わり, 本番より速く出る
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
VARIANT="${1:?版を指定すること (base|B|A|AB)}"
DST="${2:?出力先を指定すること}"
SRC="$ROOT/impl/25_huge_retreat"
case "$VARIANT" in
    base) PATCHES=() ;;
    B)    PATCHES=(invbits) ;;
    A)    PATCHES=(catchfirst) ;;
    AB)   PATCHES=(invbits catchfirst) ;;
    *)    echo "版は base B A AB のどれか: $VARIANT" >&2; exit 2 ;;
esac
mkdir -p "$DST"
cp "$SRC/animal_shogi.c" "$SRC/animal_shogi.h" "$SRC/Makefile" "$DST/"
for p in "${PATCHES[@]}"; do
    patch --quiet --forward --fuzz=0 --no-backup-if-mismatch -p1 -d "$DST" < "$HERE/patches/$p.patch"
done
(cd "$DST" && make --quiet animal_shogi.so)
echo "$VARIANT: impl/25_huge_retreat + [${PATCHES[*]}] (so sha256 $(sha256sum "$DST/animal_shogi.so" | cut -c1-12))"
