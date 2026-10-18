#!/bin/bash
# 段2の腕のソースを作ってビルドし, 静的な確かめをする (実験 rank_fast。記録試行ではない)
#
#   build_arm2.sh <腕> <出力先>
#
# impl/38_precheck を出力先に写し (中へ cd しない), base でなければ patches/<腕>.patch を当てる.
# 確かめること (どれかが外れたら exit 3):
#   - 変わったのは animal_shogi.c だけ (animal_shogi.h・animal_shogi.py・Makefile・hot_layout.ld はバイト同一)
#   - Makefile の gcc 行に -Wextra を足して組んでも警告が 0 (-Wall は Makefile にある)
#   - 関数の記号 (nm の T / t) が base と同じ (新しい下請けは全部インライン展開された). 増えてよいのは .bss の表だけ
# .so は Makefile のまま組む (出力先/animal_shogi.so). 標準出力の最後の行に .so の sha256 の先頭
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ARM="${1:?腕を指定すること}"
DST="${2:?出力先を指定すること}"
SRC="$ROOT/impl/38_precheck"
mkdir -p "$DST"
find "$SRC" -maxdepth 1 -type f -exec cp {} "$DST/" \;
if [ "$ARM" != base ]; then
    patch --quiet --fuzz=0 -d "$DST" -p1 < "$HERE/patches/$ARM.patch"
fi
for f in animal_shogi.h animal_shogi.py Makefile hot_layout.ld; do
    cmp -s "$SRC/$f" "$DST/$f" || { echo "!!! $ARM: $f が impl/38_precheck と違う" >&2; exit 3; }
done
(cd "$DST" && make --quiet animal_shogi.so)
LINE=$(grep -E '^\s+gcc ' "$SRC/Makefile" | sed -e 's/^\s*//')
W=${LINE/-o animal_shogi.so/-o wextra.so}
(cd "$DST" && eval "$W -Wextra" 2> wextra.txt)
if [ -s "$DST/wextra.txt" ]; then
    echo "!!! $ARM: -Wall -Wextra で警告が出た" >&2
    cat "$DST/wextra.txt" >&2
    exit 3
fi
rm -f "$DST/wextra.so"
nm "$DST/animal_shogi.so" | awk '$2 ~ /^[Tt]$/ {print $3}' | LC_ALL=C sort > "$DST/funcs.txt"
nm "$DST/animal_shogi.so" | awk '$2 ~ /^[bB]$/ {print $3}' | LC_ALL=C sort > "$DST/bss.txt"
if [ "$ARM" != base ]; then
    BASE="$DST/../base_ref"
    rm -rf "$BASE"
    mkdir -p "$BASE"
    find "$SRC" -maxdepth 1 -type f -exec cp {} "$BASE/" \;
    (cd "$BASE" && make --quiet animal_shogi.so)
    nm "$BASE/animal_shogi.so" | awk '$2 ~ /^[Tt]$/ {print $3}' | LC_ALL=C sort > "$BASE/funcs.txt"
    if ! cmp -s "$BASE/funcs.txt" "$DST/funcs.txt"; then
        echo "!!! $ARM: 関数の記号が base と違う (インライン展開されていない下請けがある)" >&2
        diff "$BASE/funcs.txt" "$DST/funcs.txt" >&2 || true
        exit 3
    fi
    nm "$BASE/animal_shogi.so" | awk '$2 ~ /^[bB]$/ {print $3}' | LC_ALL=C sort > "$BASE/bss.txt"
    echo "$ARM: .bss に足した記号: $(comm -13 "$BASE/bss.txt" "$DST/bss.txt" | tr '\n' ' ')"
fi
echo "$ARM: 警告 0, 関数の記号は base と同じ, so sha256 $(sha256sum "$DST/animal_shogi.so" | cut -c1-12)"
