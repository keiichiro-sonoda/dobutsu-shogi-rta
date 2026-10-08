#!/bin/bash
# ベンチの .so と本体をビルドする (実験 perf_34。記録試行ではない)
#
#   build_bench.sh <出力先ディレクトリ>
#
# impl/34_unmove の animal_shogi.c / .h / hot_layout.ld と glue.c (animal_shogi.c を取り込む) を写し,
# impl/34_unmove の Makefile の gcc 行のまま (入力と出力の名前だけ替えて) bench.so にする
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SRC="$ROOT/impl/34_unmove"
DST="${1:?出力先を指定すること}"
mkdir -p "$DST"
cp "$SRC/animal_shogi.c" "$SRC/animal_shogi.h" "$SRC/hot_layout.ld" "$HERE/glue.c" "$HERE/bench.c" "$DST/"
LINE=$(grep -E '^\s+gcc ' "$SRC/Makefile" | sed -e 's/^\s*//')
CMD=${LINE/animal_shogi.c -o animal_shogi.so/glue.c -o bench.so}
[ "$CMD" != "$LINE" ] || { echo "gcc 行の入力と出力を置き換えられない: $LINE" >&2; exit 2; }
echo "# impl/34 の gcc 行: $LINE"
echo "# bench.so: $CMD"
(cd "$DST" && eval "$CMD")
(cd "$DST" && gcc -O2 -Wall -Wextra bench.c -o bench -ldl)
echo "bench.so sha256 $(sha256sum "$DST/bench.so" | cut -c1-12) / bench sha256 $(sha256sum "$DST/bench" | cut -c1-12)"
