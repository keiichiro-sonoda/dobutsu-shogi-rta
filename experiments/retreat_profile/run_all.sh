#!/bin/bash
# 計装ありを8本, 計装なしを1本走らせる (記録試行ではない)
#
# ⚠️ 旧新の比較ではないので腕は1本でいい。base は対照群ではなく、
#    「計装が答えを変えていないこと」のバイト比較の相手と、計装コストの比較対象。
#
# 8本にする理由: gate_15 では16本中5本 (31%) が高フォルト側だった。
# 8本で1本も高フォルト側が出ない確率は (11/16)^8 = 5.0%。
# 1本も出なかったら、そのこと自体を README に書いて止める。
#
# ⚠️ 1本あたり後退解析 8 分ほどなので、9本で約1.3時間かかる。
#    その間このマシンで他の計算を回さないこと。
set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

# 計装なし。dat/ を残してバイト比較の相手にする
"$HERE/run.sh" impl/15_c_successors base keep

# 計装あり。p1 だけ dat/ を残す
for i in 1 2 3 4 5 6 7 8; do
    if [ "$i" -eq 1 ]; then
        "$HERE/run.sh" experiments/retreat_profile "p$i" keep
    else
        "$HERE/run.sh" experiments/retreat_profile "p$i"
    fi
done
echo "=== 全9本 完了 $(date --iso-8601=seconds) ==="
