#!/bin/bash
# 腕を組む (実験 forward_prep。記録試行ではない)
#
#   build_arm.sh <old|recalc|carry|carry_check> <作業ディレクトリ>
#
# impl/33_hot_layout の animal_shogi.{c,h,py} / hot_layout.ld / Makefile を写し, 腕のパッチ (patches/<腕>.patch) を当て,
# impl/33 の Makefile のまま .so を作る. old はパッチを当てない (impl/33 そのもの).
# carry_check は carry に -DPREP_CHECK を足したもの (一致の検査だけで使う. 積んだランクを計算し直して比べる)
# 標準出力の最後の行に, 腕の説明と .so の sha256 を出す
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ARM="${1:?腕を指定すること}"
DST="${2:?作業ディレクトリを指定すること}"
SRC="$ROOT/impl/33_hot_layout"
mkdir -p "$DST"
cp "$SRC/animal_shogi.c" "$SRC/animal_shogi.h" "$SRC/animal_shogi.py" "$SRC/hot_layout.ld" "$SRC/Makefile" "$DST/"
case "$ARM" in
    old) PATCH="" ;;
    recalc) PATCH="$HERE/patches/recalc.patch" ;;
    carry | carry_check) PATCH="$HERE/patches/carry.patch" ;;
    *) echo "腕は old / recalc / carry / carry_check: $ARM" >&2; exit 2 ;;
esac
if [ -n "$PATCH" ]; then
    patch -s -p1 --fuzz=0 -d "$DST" < "$PATCH"
fi
LINE=$(grep -E '^\s+gcc ' "$DST/Makefile" | sed -e 's/^\s*//')
if [ "$ARM" = "carry_check" ]; then
    LINE="${LINE/gcc /gcc -DPREP_CHECK }"
fi
(cd "$DST" && eval "$LINE") >&2
echo "$ARM: impl/33_hot_layout${PATCH:+ + patches/$(basename "$PATCH")} / animal_shogi.so sha256 $(sha256sum "$DST/animal_shogi.so" | cut -c1-12)"
