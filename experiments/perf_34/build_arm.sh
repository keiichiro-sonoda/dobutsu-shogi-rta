#!/bin/bash
# 腕のソースを写し, perf の切り替えのパッチを当ててビルドする (実験 perf_34。記録試行ではない)
#
#   build_arm.sh <出力先ディレクトリ>
#
# impl/34_unmove の写しに patches/perf_ctl.patch (animal_shogi.py だけ. 段の境界で perf の数えを
# 止めたり動かしたりする) を当てる. C・ヘッダ・Makefile・hot_layout.ld は impl/34_unmove とバイト同一で,
# .so は impl/34_unmove の Makefile でビルドする. PERF_STAGE を渡さなければパッチは何もしない
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
DST="${1:?出力先を指定すること}"
SRC="$ROOT/impl/34_unmove"
mkdir -p "$DST"
find "$SRC" -maxdepth 1 -type f -exec cp {} "$DST/" \;
patch --quiet --fuzz=0 -d "$DST" -p1 < "$HERE/patches/perf_ctl.patch"
(cd "$DST" && make --quiet animal_shogi.so)
for f in animal_shogi.c animal_shogi.h Makefile hot_layout.ld; do
    cmp -s "$SRC/$f" "$DST/$f" || { echo "$f が impl/34_unmove と違う" >&2; exit 1; }
done
echo "perf_34 (so sha256 $(sha256sum "$DST/animal_shogi.so" | cut -c1-12), py sha256 $(sha256sum "$DST/animal_shogi.py" | cut -c1-12))"
