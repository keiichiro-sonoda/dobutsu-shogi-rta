#!/bin/bash
# 腕ごとのベンチの .so と本体をビルドする (実験 mirror1_keep。記録試行ではない)
#
#   build_bench.sh <腕> <build_arm.sh の出力先> <ベンチの出力先>
#
# experiments/unmove_gen/build_bench.sh の写し (もとは experiments/perf_34/build_bench.sh). 違いは, 取り込む
# animal_shogi.c を腕のもの (build_arm.sh の出力先) にすることと, gcc 行を impl/36_bb_unmove の Makefile から取ること
# (impl/34_unmove・impl/35_bitboard と同じ行). glue.c と bench.c は experiments/perf_34 のものをそのまま使う.
# benchUnmove (逆向きの生成器 ＋ 候補ごとの rankOf) は3腕で同じ.
# 束ごとの帰属のために, gcc 行に -g を足した .so も g/animal_shogi.so に作る (perf_branch_34 の aggregate.py が
# animal_shogi.so という名前の dso を数えるため). .text の中身と番地が -g なしと同じことを確かめる.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
ARM="${1:?腕を指定すること}"
ARMDIR="${2:?build_arm.sh の出力先を指定すること}"
DST="${3:?出力先を指定すること}"
P34="$ROOT/experiments/perf_34"
mkdir -p "$DST/g"
cp "$ARMDIR/animal_shogi.c" "$ARMDIR/animal_shogi.h" "$ARMDIR/hot_layout.ld" "$P34/glue.c" "$P34/bench.c" "$DST/"
LINE=$(grep -E '^\s+gcc ' "$ROOT/impl/36_bb_unmove/Makefile" | sed -e 's/^\s*//')
CMD=${LINE/animal_shogi.c -o animal_shogi.so/glue.c -o bench.so}
[ "$CMD" != "$LINE" ] || { echo "gcc 行の入力と出力を置き換えられない: $LINE" >&2; exit 2; }
GCMD=${CMD/ -O2 / -O2 -g }
GCMD=${GCMD/-o bench.so/-o g\/animal_shogi.so}
(cd "$DST" && eval "$CMD" && eval "$GCMD")
(cd "$DST" && gcc -O2 -Wall -Wextra bench.c -o bench -ldl)
for sec in .text.hot_layout .text; do
    objcopy -O binary --only-section="$sec" "$DST/bench.so" "$DST/a.bin"
    objcopy -O binary --only-section="$sec" "$DST/g/animal_shogi.so" "$DST/b.bin"
    cmp -s "$DST/a.bin" "$DST/b.bin" || { echo "!!! $ARM: ベンチの $sec が -g の有無で違う" >&2; exit 3; }
done
echo "$ARM: bench.so sha256 $(sha256sum "$DST/bench.so" | cut -c1-12) / bench sha256 $(sha256sum "$DST/bench" | cut -c1-12)"
