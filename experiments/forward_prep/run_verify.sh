#!/bin/bash
# 一致の検査 (実験 forward_prep。記録試行ではない). 計時の門番 (run_all.sh) の前に回す
#
#   run_verify.sh
#
# 1. 3本を verify で走らせる (計時には使わない): v_old (old), v_recalc (recalc), v_carry (carry_check: 積んだランクを
#    盤面から計算し直して比べる検査用ビルド). どの本も run_one.sh の照合 (全探索の側の dat/ と forward.tsv の件数の列が #33 と一致,
#    3本の列の sha256 が old と一致) を通す. v_old が基準の sha256 を logs/out_ref.txt に書く
# 2. v_recalc の配列 (prep.bin) を check_prep で確かめる (cls.bin と, いまの生成器で数え直したキャッチ抜きの数)
# 3. v_carry の配列が v_recalc の配列とバイト一致し, 積んだランクの食い違いが 0
# cls.bin は runs/unmove_flip/cls.bin を使う (unmove_prune・unmove_flip の logs/prep.txt と同じ sha256 であることを先に確かめる)
# 出力は logs/verify.txt. 開始と終了の時刻は logs/console_verify.log
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
R="$ROOT/runs/forward_prep"
CLS="$ROOT/runs/unmove_flip/cls.bin"
CLS_SHA=8ecd2dbc39444ee3487f9e111f893d00dbdbfccbc76e011440b50cca00076c95
mkdir -p "$R" "$HERE/logs"
if [ -e "$HERE/logs/console_verify.log" ]; then
    echo "logs/console_verify.log が残っている. 退避してから起動すること" >&2
    exit 2
fi
exec > >(tee "$HERE/logs/console_verify.log") 2>&1
echo "=== forward_prep 一致の検査 開始 $(date --iso-8601=seconds) ==="
GOT=$(sha256sum "$CLS" | cut -d' ' -f1)
[ "$GOT" = "$CLS_SHA" ] || { echo "!!! cls.bin の sha256 が違う: $GOT" >&2; exit 2; }
echo "cls.bin sha256 ${GOT:0:12} (unmove_prune・unmove_flip と同じ)"
"$HERE/run_one.sh" old v_old verify
"$HERE/run_one.sh" recalc v_recalc verify
"$HERE/run_one.sh" carry_check v_carry verify
gcc -O2 -Wall -Wextra "$HERE/check_prep.c" -o "$R/check_prep" -ldl
{
    echo "## v_recalc の配列"
    set +e
    "$R/check_prep" "$R/v_old/animal_shogi.so" "$CLS" "$R/v_recalc/prep.bin" "$ROOT/runs/20261004-091929_33_hot_layout/dat"
    RC1=$?
    set -e
    echo
    echo "## v_carry の配列"
    if cmp -s "$R/v_recalc/prep.bin" "$R/v_carry/prep.bin"; then CMP="バイト一致"; RC2=0; else CMP="一致しない"; RC2=1; fi
    echo "v_recalc の配列と: $CMP"
    grep '^積んだランク' "$HERE/logs/v_carry_stdout.txt"
    BADR=$(grep '^積んだランク' "$HERE/logs/v_carry_stdout.txt" | grep -oE '[0-9]+$')
    [ "$BADR" = "0" ] || RC2=1
    echo
    if [ "$RC1" -eq 0 ] && [ "$RC2" -eq 0 ]; then echo "一致の検査: PASS"; else echo "一致の検査: FAIL"; fi
} | tee "$HERE/logs/verify.txt"
if grep -qx '一致の検査: PASS' "$HERE/logs/verify.txt"; then
    rm -f "$R/v_recalc/prep.bin" "$R/v_carry/prep.bin"
fi
echo "=== forward_prep 一致の検査 終了 $(date --iso-8601=seconds) ==="
grep -qx '一致の検査: PASS' "$HERE/logs/verify.txt"
