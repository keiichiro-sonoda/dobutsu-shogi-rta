#!/bin/bash
# 腕を組む (実験 mirror1_keep。記録試行ではない)
#
#   build_arm.sh <base|mirror1|mirror1_keep> <出力先ディレクトリ>
#
# impl/36_bb_unmove を写し, base 以外なら patches/<腕>.patch (逆向きの生成器 unmoveCandidates と,
# その下請けと表だけを書き換える) を当てる. .so は impl/36_bb_unmove の Makefile のままビルドする (出力先/animal_shogi.so).
# 静的な確かめのために, 同じソースを gcc 行に -g を足してビルドした .so も g/ に作り, .text.hot_layout と .text の
# 中身 (objcopy -O binary --only-section) と番地・大きさ (readelf -S) が -g なしと同じことを確かめる.
# base は -g なしの .so が #36 本走と同じバイト列 (sha256 の先頭 c7106b9e0aaf) であることも見る.
# -Wall -Wextra の警告を出力先/warnings.txt に残す. どれかが合わなければ exit 3
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ARM="${1:?腕を指定すること (base|mirror1|mirror1_keep)}"
DST="${2:?出力先を指定すること}"
SRC="$ROOT/impl/36_bb_unmove"
case "$ARM" in base | mirror1 | mirror1_keep) ;; *) echo "知らない腕: $ARM" >&2; exit 2 ;; esac
mkdir -p "$DST/g"
find "$SRC" -maxdepth 1 -type f -exec cp {} "$DST/" \;
if [ "$ARM" != base ]; then
    patch --quiet --fuzz=0 -d "$DST" -p1 < "$HERE/patches/$ARM.patch"
fi
for f in animal_shogi.h animal_shogi.py Makefile hot_layout.ld; do
    cmp -s "$SRC/$f" "$DST/$f" || { echo "$f が impl/36_bb_unmove と違う" >&2; exit 3; }
done
(cd "$DST" && make --quiet animal_shogi.so)
LINE=$(grep -E '^\s+gcc ' "$SRC/Makefile" | sed -e 's/^\s*//')
GLINE=${LINE/ -O2 / -O2 -g }
cp "$DST/animal_shogi.c" "$DST/animal_shogi.h" "$DST/hot_layout.ld" "$DST/g/"
(cd "$DST/g" && eval "$GLINE")
# 警告: Makefile の -Wall に -Wextra を足して, 同じソースをオブジェクトまでコンパイルする
(cd "$DST" && gcc -O2 -fno-semantic-interposition -march=native -ffunction-sections -fPIC \
    -Wall -Wextra -c animal_shogi.c -o /dev/null) > "$DST/warnings.txt" 2>&1 || true
NW=$(grep -c 'warning:' "$DST/warnings.txt" || true)
if [ "$NW" != 0 ]; then
    echo "!!! $ARM: -Wall -Wextra の警告が $NW 件" >&2
    exit 3
fi
for sec in .text.hot_layout .text; do
    objcopy -O binary --only-section="$sec" "$DST/animal_shogi.so" "$DST/sec$sec.bin"
    objcopy -O binary --only-section="$sec" "$DST/g/animal_shogi.so" "$DST/g/sec$sec.bin"
    cmp -s "$DST/sec$sec.bin" "$DST/g/sec$sec.bin" || { echo "!!! $ARM: $sec の中身が -g の有無で違う" >&2; exit 3; }
    A=$(readelf -SW "$DST/animal_shogi.so" | awk -v s="$sec" '$2 == s {print $4, $6}')
    B=$(readelf -SW "$DST/g/animal_shogi.so" | awk -v s="$sec" '$2 == s {print $4, $6}')
    [ -n "$A" ] && [ "$A" = "$B" ] || { echo "!!! $ARM: $sec の番地か大きさが -g の有無で違う" >&2; exit 3; }
done
SHA=$(sha256sum "$DST/animal_shogi.so" | cut -c1-12)
if [ "$ARM" = base ] && [ "$SHA" != c7106b9e0aaf ]; then
    echo "!!! base の .so が #36 本走と違う ($SHA)" >&2
    exit 3
fi
# 逆向きの生成器が熱い関数の区画に入っているか (名前は同じなので区画は変わらないはず)
HOT=$(readelf -SW "$DST/animal_shogi.so" | awk '$2 == ".text.hot_layout" {print $4, $6}')
GEN=$(nm "$DST/animal_shogi.so" | awk '$3 == "unmoveCandidates" {print $1}')
python3 - "$HOT" "$GEN" <<'PY'
import sys
lo, size = (int(x, 16) for x in sys.argv[1].split())
gen = int(sys.argv[2], 16)
if not lo <= gen < lo + size:
    sys.exit("!!! unmoveCandidates が .text.hot_layout の外にある")
PY
echo "$ARM (so sha256 $SHA, -g の .text は一致, 警告 0)"
