#!/bin/bash
# old new new old を2回, 計8本 (記録試行ではない)
#
# 対で向きを入れ替えると「対のなかの位置」が片方の腕に乗らない
# (記録 #14 の門番で P0 に出た形).
#
# ⚠️ 本走と違い, 両腕の採番順は同じ. convert_fixture.py が .bin のフィクスチャを
#    array("Q", pickle.load(f)) で書いているので, #16 がファイルから読む順は
#    #15 が pickle から読む順と一致する. 形式だけが1変数になる.
#
# ⚠️ 1本あたり後退解析 8 分ほどなので, 8本で約1.1時間かかる.
#    その間このマシンで他の計算を回さないこと.
set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

for i in 1 2; do
    # 1組目だけ dat/ を残す. 採番順が本当に一致したかをバイトで照合する
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
