#!/bin/bash
# 腕のソースを組んで .so までビルドする (実験 lever_scan。記録試行ではない)
#
#   make_arm.sh <腕> <出力先ディレクトリ>
#
# 出発点は7腕とも impl/19_c_gather。.py は計装ごとバイト同一の写しで, 動かすのは
# 下の表の差分だけ。パッチは patches/ にあり, impl/19_c_gather に対する unified diff。
#
#   base    何も変えない (-O2)
#   fnsi    -fno-semantic-interposition
#   const   patches/const.patch (移動表4本を static const に)
#   native  -march=native
#   huge    patches/huge.patch (索引と発見済み表に MADV_HUGEPAGE)
#   pf      patches/pf.patch (先読み4か所, 距離 16)
#   all     const → huge → pf の順に3本 + 上の2フラグ
#
# ビルドの行は impl/19 の Makefile と同じで, 腕の CFLAGS を前に足すだけ。
# ⚠️ CFLAGS はクォートしない (base では空なので, 空の引数を渡さないため)
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ARM="${1:?腕を指定すること (base|fnsi|const|native|huge|pf|all)}"
DST="${2:?出力先を指定すること}"

case "$ARM" in
    base)   CFLAGS="";                                          PATCHES=() ;;
    fnsi)   CFLAGS="-fno-semantic-interposition";               PATCHES=() ;;
    const)  CFLAGS="";                                          PATCHES=(const) ;;
    native) CFLAGS="-march=native";                             PATCHES=() ;;
    huge)   CFLAGS="";                                          PATCHES=(huge) ;;
    pf)     CFLAGS="";                                          PATCHES=(pf) ;;
    all)    CFLAGS="-fno-semantic-interposition -march=native"; PATCHES=(const huge pf) ;;
    *)      echo "腕は base fnsi const native huge pf all のどれか: $ARM" >&2; exit 2 ;;
esac

mkdir -p "$DST"
cp "$ROOT/impl/19_c_gather/animal_shogi.py" "$ROOT/impl/19_c_gather/animal_shogi.c" \
   "$ROOT/impl/19_c_gather/animal_shogi.h" "$DST/"
for p in "${PATCHES[@]}"; do
    # 衝突したら (fuzz で黙って当てずに) 止める
    patch --quiet --forward --fuzz=0 -p1 -d "$DST" < "$HERE/patches/$p.patch"
done
# shellcheck disable=SC2086
(cd "$DST" && gcc $CFLAGS -O2 animal_shogi.c -o animal_shogi.so -Wall -fPIC -shared)
echo "$ARM: gcc「${CFLAGS:-追加なし} -O2」パッチ「${PATCHES[*]:-なし}」"
