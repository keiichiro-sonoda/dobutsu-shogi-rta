#!/bin/bash
# rankOf だけのベンチ (rank_glue.c ＋ rank_bench.c) と, 文脈の中のベンチ (perf_34 の glue.c ＋ bench.c) を
# 腕ごとにビルドする (実験 rank_fast。記録試行ではない)
#
#   build_bench.sh <腕の animal_shogi.c があるディレクトリ> <出力先>
#
# 腕のディレクトリには animal_shogi.c・animal_shogi.h・hot_layout.ld があること (base は impl/38_precheck そのもの.
# 段2の腕は patches/ のパッチを当てた写し). gcc 行は impl/38_precheck の Makefile から取り, 入力と出力の名前だけ替える.
# 出力: rank.so と rank_bench (rankOf だけ), bench.so と bench (perf_34 の benchFwd / benchUnmove).
# 腕のディレクトリへは cd しない (impl/ の中に .claude/ や中間生成物を作らないため. 写してからビルドする)
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SRC="${1:?腕のディレクトリを指定すること}"
DST="${2:?出力先を指定すること}"
P34="$ROOT/experiments/perf_34"
mkdir -p "$DST"
cp "$SRC/animal_shogi.c" "$SRC/animal_shogi.h" "$SRC/hot_layout.ld" "$HERE/rank_glue.c" "$HERE/rank_bench.c" \
    "$P34/glue.c" "$P34/bench.c" "$DST/"
LINE=$(grep -E '^\s+gcc ' "$ROOT/impl/38_precheck/Makefile" | sed -e 's/^\s*//')
R=${LINE/animal_shogi.c -o animal_shogi.so/rank_glue.c -o rank.so}
B=${LINE/animal_shogi.c -o animal_shogi.so/glue.c -o bench.so}
[ "$R" != "$LINE" ] && [ "$B" != "$LINE" ] || { echo "gcc 行の入力と出力を置き換えられない: $LINE" >&2; exit 2; }
(cd "$DST" && eval "$R -Wextra" && eval "$B")
(cd "$DST" && gcc -O2 -Wall -Wextra rank_bench.c -o rank_bench -ldl && gcc -O2 -Wall -Wextra bench.c -o bench -ldl)
echo "rank.so sha256 $(sha256sum "$DST/rank.so" | cut -c1-12) / bench.so sha256 $(sha256sum "$DST/bench.so" | cut -c1-12)"
