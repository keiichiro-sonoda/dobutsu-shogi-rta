#!/bin/bash
# catch.so とベンチ本体をビルドする (実験 unmove_catch。記録試行ではない)
#
#   build_so.sh <出力先ディレクトリ>
#
# impl/33_hot_layout の animal_shogi.c / .h / hot_layout.ld と, experiments/unmove_bench/unmove.c (素朴な逆向きの生成器。
# 書き換えずにそのまま使う) を写し, catch.c (unmove.c を取り込む) を impl/33 の Makefile の gcc 行のまま
# (入力のファイル名と出力名だけを替えて) .so にする. ベンチ本体 (bench.c) は .so を dlopen して呼ぶ
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SRC="$ROOT/impl/33_hot_layout"
DST="${1:?出力先を指定すること}"
mkdir -p "$DST"
cp "$SRC/animal_shogi.c" "$SRC/animal_shogi.h" "$SRC/hot_layout.ld" "$ROOT/experiments/unmove_bench/unmove.c" \
    "$HERE/catch.c" "$HERE/bench.c" "$DST/"
LINE=$(grep -E '^\s+gcc ' "$SRC/Makefile" | sed -e 's/^\s*//')
[ -n "$LINE" ] || { echo "impl/33 の Makefile に gcc 行が無い" >&2; exit 2; }
CMD=${LINE/animal_shogi.c -o animal_shogi.so/catch.c -o catch.so}
[ "$CMD" != "$LINE" ] || { echo "gcc 行の入力と出力を置き換えられない: $LINE" >&2; exit 2; }
echo "# impl/33 の gcc 行: $LINE"
echo "# catch.so: $CMD"
(cd "$DST" && eval "$CMD")
(cd "$DST" && gcc -O2 -Wall -Wextra bench.c -o bench -ldl)
echo "unmove.c sha256 $(sha256sum "$DST/unmove.c" | cut -c1-12) (experiments/unmove_bench と同じ)"
echo "catch.so sha256 $(sha256sum "$DST/catch.so" | cut -c1-12) / bench sha256 $(sha256sum "$DST/bench" | cut -c1-12)"
