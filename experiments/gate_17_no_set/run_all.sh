#!/bin/bash
# old new new old を2回, 計8本 (記録試行ではない)
#
# 対で向きを入れ替えると「対のなかの位置」が片方の腕に乗らない
# (記録 #14 の門番で P0 に出た形).
#
# ⚠️ 両腕とも同じフィクスチャ (runs/g1_11_fixture_bin/dat) を読む. どちらも
#    frombytes なので packed は完全に同一で, P0〜P4 は同じ仕事をする.
#    動くのは174段ループの書き出しと writeUnknownChunks だけ.
#
# ⚠️ 1本あたり後退解析 7〜8 分ほどなので, 8本で約1.0時間かかる.
#    その間このマシンで他の計算を回さないこと.
set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

for i in 1 2; do
    # 1組目だけ dat/ を残す. 並びが実際に動いたことをバイトで照合する
    if [ "$i" -eq 1 ]; then
        "$HERE/run.sh" old "g${i}a" keep
        "$HERE/run.sh" new "g${i}b" keep
    else
        "$HERE/run.sh" old "g${i}a"
        "$HERE/run.sh" new "g${i}b"
    fi
    "$HERE/run.sh" new "g${i}c"
    "$HERE/run.sh" old "g${i}d"
done
echo "=== 全8本 完了 $(date --iso-8601=seconds) ==="
