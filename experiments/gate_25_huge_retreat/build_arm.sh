#!/bin/bash
# 腕のソースを組んで, その実装の Makefile でビルドする (門番 #25。記録試行ではない)
#
#   build_arm.sh <old|new> <出力先ディレクトリ>
#
#   old  impl/24_reuse_buffers ＋ 計装 (lever_scan_2 の instr.patch) ＋ 受け皿の片付け (patches/release.patch)
#   new  impl/25_huge_retreat (old に hugeR を足したもの. 後退解析の4配列を hugeAlloc で確保する)
#
# ⚠️ old を impl/24 そのものにしない. 計装と片付けが片方の腕にだけ入ると, その差が hugeR の効果に混ざる.
# old ＋ hugeR.patch が impl/25 とコード (コメントを除く) で一致することは
# tests/test_impl_25_huge_retreat.py が固定している. パッチは fuzz なしで当て, 衝突したら止める
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ARM="${1:?腕を指定すること (old|new)}"
DST="${2:?出力先を指定すること}"
case "$ARM" in
    old) SRC="$ROOT/impl/24_reuse_buffers"
         PATCHES=("$ROOT/experiments/lever_scan_2/patches/instr.patch" "$HERE/patches/release.patch") ;;
    new) SRC="$ROOT/impl/25_huge_retreat"; PATCHES=() ;;
    *)   echo "腕は old か new: $ARM" >&2; exit 2 ;;
esac
mkdir -p "$DST"
cp "$SRC/animal_shogi.c" "$SRC/animal_shogi.h" "$SRC/animal_shogi.py" "$SRC/Makefile" "$DST/"
for p in "${PATCHES[@]}"; do
    patch --quiet --forward --fuzz=0 --no-backup-if-mismatch -p1 -d "$DST" < "$p"
done
(cd "$DST" && make --quiet animal_shogi.so)
DESC="${SRC#"$ROOT"/}"
[ "${#PATCHES[@]}" -eq 0 ] || DESC="$DESC + instr + release"
echo "$ARM: $DESC (so sha256 $(sha256sum "$DST/animal_shogi.so" | cut -c1-12))"
