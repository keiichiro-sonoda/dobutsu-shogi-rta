#!/bin/bash
# 全探索の門番: old new new old を2回 = 8本 (記録試行ではない)
#
# 基準は後退解析の門番の入力 runs/g19_fixture_bin/dat の md5 一覧の sha256.
# 入力は impl/19 の全探索の出力そのものなので, 旧新とも一致するはず.
# 入力が無ければ, old の1本目の dat/ をそのまま入力にする (全探索は決定的).
#
# ⚠️ 約17分かかる. その間このマシンで他の計算を回さないこと
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$HERE/lib.sh"
FIX="$ROOT/runs/g19_fixture_bin/dat"
REF_FILE="$HERE/logs/ref_forward_sha256.txt"

MAKE_FIX=""
if [ "$(find "$FIX" -maxdepth 1 -name "*.bin" 2>/dev/null | wc -l)" -eq 51 ]; then
    md5_list_sha "$FIX" > "$REF_FILE"
    echo "基準: ${FIX#"$ROOT"/} の md5 一覧の sha256 $(cat "$REF_FILE")"
else
    MAKE_FIX=1
    : > "$REF_FILE"
    echo "入力が無いので, old の1本目から作る"
fi

for i in 1 2; do
    for pos in a b c d; do
        case "$pos" in a|d) arm=old ;; b|c) arm=new ;; esac
        label="f${i}${pos}_$arm"
        if [ -n "$MAKE_FIX" ] && [ "$i" -eq 1 ] && [ "$pos" = a ]; then
            "$HERE/run_forward.sh" "$arm" "$label" keep
            mkdir -p "$(dirname "$FIX")"
            mv "$ROOT/runs/exp_g20f_$label/dat" "$FIX"
            md5_list_sha "$FIX" > "$REF_FILE"
            echo "入力を作った: ${FIX#"$ROOT"/} / 基準 $(cat "$REF_FILE")"
        else
            "$HERE/run_forward.sh" "$arm" "$label"
        fi
    done
done
echo "=== 全探索 全8本 完了 $(date --iso-8601=seconds) ==="
