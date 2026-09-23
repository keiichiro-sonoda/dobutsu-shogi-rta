#!/bin/bash
# 腕のソースを組んで, その実装の Makefile でビルドする (門番 #21。記録試行ではない)
#
#   build_arm.sh <old|new> <出力先ディレクトリ>
#
#   old  impl/20_prefetch の .c / .h + impl/21_hugepages の .py + Makefile
#        (= #21 から C の変更だけを戻したもの)
#   new  impl/21_hugepages
#
# ⚠️ old を #20 そのものにしない. #21 は Python にユーザー時間とカーネル時間の計装を
#    入れている. 計装が片方の腕にだけ入ると, 計装の費用が巨大ページの効果に混ざる
#    (#19 の門番が old を「#18 + 計装だけ」にしたのと同じ理由).
# フラグを門番側に書かない. Makefile は #20 と #21 でバイト同一 (gcc -O2)
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
ARM="${1:?腕を指定すること (old|new)}"
DST="${2:?出力先を指定すること}"
NEW="$ROOT/impl/21_hugepages"
case "$ARM" in
    old) C_SRC="$ROOT/impl/20_prefetch" ;;
    new) C_SRC="$NEW" ;;
    *)   echo "腕は old か new: $ARM" >&2; exit 2 ;;
esac
mkdir -p "$DST"
cp "$C_SRC/animal_shogi.c" "$C_SRC/animal_shogi.h" "$DST/"
cp "$NEW/animal_shogi.py" "$NEW/Makefile" "$DST/"
(cd "$DST" && make --quiet animal_shogi.so)
echo "$ARM: C ${C_SRC#"$ROOT"/} / Python ${NEW#"$ROOT"/} (Makefile のまま)"
