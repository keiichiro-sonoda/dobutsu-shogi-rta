#!/bin/bash
# 回す前の静的な確かめ (実験 prep_ahead。記録試行ではない). 出力は logs/static_check.txt
#
#   static_check.sh
#
# 2腕を build_arm.sh で組み, 次を出す:
#   - .so の sha256 (base は記録 #40 の .so と同じ db2ea39f8828 であること. build_arm.sh が止める)
#   - -Wall -Wextra での警告の数 (Makefile の gcc 行に -Wextra を足して組み直す. .so は捨てる)
#   - 関数の記号 (nm の t / T) が2腕で同じか
#   - 番地か大きさが変わった関数 (nm -S. 熱い関数の区画 .text.hot_layout とそのほか)
#   - unmoveStep の機械語の命令の数, prefetchw の数 (g_dtm と g_prep の先読み), unmoveCandidates の呼び出しの数
set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
OUT="$HERE/logs/static_check.txt"
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
mkdir -p "$HERE/logs"
exec > >(tee "$OUT") 2>&1
echo "# 静的な確かめ $(date --iso-8601=seconds) (gcc: $(gcc --version | head -1))"
for a in base prep1; do
    "$HERE/build_arm.sh" "$a" "$T/$a"
    LINE=$(grep -E '^\s+gcc ' "$T/$a/Makefile" | sed -e 's/^\s*//' -e 's/-o animal_shogi.so/-o wextra.so/')
    N=$(cd "$T/$a" && eval "$LINE -Wextra" 2>&1 | grep -c 'warning:' || true)
    echo "$a: -Wall -Wextra の警告 $N 個"
done
echo "--- 関数の記号 (nm の t / T) ---"
sym() { nm "$1" | awk 'NF == 3 && ($2 == "t" || $2 == "T") {print $3}' | sort; }
if diff <(sym "$T/base/animal_shogi.so") <(sym "$T/prep1/animal_shogi.so") > /dev/null; then
    echo "2腕で同じ ($(sym "$T/base/animal_shogi.so" | wc -l) 個)"
else
    echo "!!! 2腕で違う"; diff <(sym "$T/base/animal_shogi.so") <(sym "$T/prep1/animal_shogi.so") || true
fi
echo "--- 番地か大きさが変わった関数 (base → prep1. 番地の差と大きさの差はバイト) ---"
tab() { nm -S "$1" | awk 'NF == 4 && ($3 == "t" || $3 == "T") {print $4, $1, $2}' | sort -u; }
join <(tab "$T/base/animal_shogi.so") <(tab "$T/prep1/animal_shogi.so") \
    | awk '{d = strtonum("0x" $4) - strtonum("0x" $2); s = strtonum("0x" $5) - strtonum("0x" $3)
            if (d || s) printf "%-28s 0x%s (0x%x バイト) → 0x%s (0x%x バイト)  番地 %+d / 大きさ %+d\n",
                                $1, substr($2, 13), strtonum("0x" $3), substr($4, 13), strtonum("0x" $5), d, s}'
for sec in .text.hot_layout .text; do
    echo "$sec の大きさ: $(readelf -SW "$T/base/animal_shogi.so" | awk -v s="$sec" '$2 == s {print "0x" $6}') →" \
        "$(readelf -SW "$T/prep1/animal_shogi.so" | awk -v s="$sec" '$2 == s {print "0x" $6}')"
done
echo "--- unmoveStep の機械語 ---"
for a in base prep1; do
    objdump -d --no-show-raw-insn "$T/$a/animal_shogi.so" > "$T/$a.asm"
    D=$(awk '/^[0-9a-f]+ <unmoveStep>:/ {on = 1; next} on && /^$/ {exit} on' "$T/$a.asm")
    echo "$a: 命令 $(grep -c . <<< "$D") 個, prefetchw $(grep -c 'prefetchw' <<< "$D") 個," \
        "unmoveCandidates の呼び出し $(grep -c 'call.*<unmoveCandidates' <<< "$D") 個"
done
