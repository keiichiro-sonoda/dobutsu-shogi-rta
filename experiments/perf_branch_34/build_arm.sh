#!/bin/bash
# 腕を組む (実験 perf_branch_34。記録試行ではない)
#
#   build_arm.sh <出力先ディレクトリ>
#
# impl/34_unmove の写しに experiments/perf_34/patches/perf_ctl.patch (animal_shogi.py だけ. 段の境界で perf の
# 数えを止めたり動かしたりする) を当てる. .so は impl/34_unmove の Makefile の gcc 行に -g を足した行でビルドする
# (Makefile は書き換えない. 行を取り出して置き換える). 分岐の標本を C のソース行まで落とすため.
#
# 同じ場所に -g なしの .so (Makefile のまま) も作り, 機械語が変わっていないことを確かめる:
#   - -g なしの .so の sha256 が #34 本走と同じ (先頭 572517006344)
#   - .text.hot_layout と .text の中身 (objcopy -O binary --only-section) がバイト一致
#   - その2つの区画の番地と大きさ (readelf -S) が一致
# どれかが合わなければ exit 3 (止める条件 2)
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
SRC="$ROOT/impl/34_unmove"
PATCH="$ROOT/experiments/perf_34/patches/perf_ctl.patch"
DST="${1:?出力先を指定すること}"
REF_SHA=572517006344
mkdir -p "$DST/nog"
find "$SRC" -maxdepth 1 -type f -exec cp {} "$DST/" \;
patch --quiet --fuzz=0 -d "$DST" -p1 < "$PATCH"
for f in animal_shogi.c animal_shogi.h Makefile hot_layout.ld; do
    cmp -s "$SRC/$f" "$DST/$f" || { echo "$f が impl/34_unmove と違う" >&2; exit 1; }
done
LINE=$(grep -E '^\s+gcc ' "$SRC/Makefile" | sed -e 's/^\s*//')
GLINE=${LINE/ -O2 / -O2 -g }
[ "$GLINE" != "$LINE" ] || { echo "gcc 行に -g を足せない: $LINE" >&2; exit 2; }
# -g なし (Makefile のまま) を nog/ に
cp "$DST/animal_shogi.c" "$DST/animal_shogi.h" "$DST/hot_layout.ld" "$DST/nog/"
(cd "$DST/nog" && eval "$LINE")
(cd "$DST" && eval "$GLINE")
NOG_SHA=$(sha256sum "$DST/nog/animal_shogi.so" | cut -c1-12)
if [ "$NOG_SHA" != "$REF_SHA" ]; then
    echo "!!! -g なしの .so が #34 本走と違う ($NOG_SHA)" >&2
    exit 3
fi
for sec in .text.hot_layout .text; do
    objcopy -O binary --only-section="$sec" "$DST/nog/animal_shogi.so" "$DST/nog/sec$sec.bin"
    objcopy -O binary --only-section="$sec" "$DST/animal_shogi.so" "$DST/sec$sec.bin"
    if ! cmp -s "$DST/nog/sec$sec.bin" "$DST/sec$sec.bin"; then
        echo "!!! $sec の中身が -g の有無で違う" >&2
        exit 3
    fi
    A=$(readelf -SW "$DST/nog/animal_shogi.so" | awk -v s="$sec" '$2 == s {print $4, $6}')
    B=$(readelf -SW "$DST/animal_shogi.so" | awk -v s="$sec" '$2 == s {print $4, $6}')
    if [ -z "$A" ] || [ "$A" != "$B" ]; then
        echo "!!! $sec の番地か大きさが -g の有無で違う ($A / $B)" >&2
        exit 3
    fi
done
echo "perf_branch_34 (-g の so sha256 $(sha256sum "$DST/animal_shogi.so" | cut -c1-12)," \
     "-g なし $NOG_SHA = #34 本走, .text.hot_layout と .text は一致)"
