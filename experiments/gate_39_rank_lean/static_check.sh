#!/bin/bash
# 回す前の静的な確かめを logs/static_check.txt に残す (門番 #39。記録試行ではない)
#
#   static_check.sh <lean の animal_shogi.so>
#
# 2腕を build_arm.sh で組み (-Wall -Wextra の警告も別に数える), static_check.py に渡す.
# lean の .so は実験 rank_fast の run_stage2.sh が組んだもの (runs/ にある. git 管理外)
set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
LEAN="${1:?lean の animal_shogi.so を指定すること}"
OUT="$HERE/logs/static_check.txt"
if [ -e "$OUT" ]; then
    echo "$OUT が既にある. 上書きしない" >&2
    exit 2
fi
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
mkdir -p "$HERE/logs"
{
    echo "# $(date --iso-8601=seconds) の静的な確かめ (static_check.sh)"
    "$HERE/build_arm.sh" old "$T/old"
    "$HERE/build_arm.sh" new "$T/new"
    # 警告: Makefile の gcc 行に -Wextra を足して組み直す (.so は捨てる)
    (cd "$T/new" && gcc -O2 -fno-semantic-interposition -march=native -ffunction-sections animal_shogi.c \
        -o "$T/wextra.so" -Wall -Wextra -fPIC -shared -Wl,-T,hot_layout.ld 2> "$T/warn.txt")
    echo "new を -Wall -Wextra で組んだ警告: $(grep -c 'warning:' "$T/warn.txt" || true) 個"
    python3 "$HERE/static_check.py" "$T/old/animal_shogi.so" "$T/new/animal_shogi.so" "$LEAN"
} > "$OUT"
cat "$OUT"
