#!/bin/bash
# plain と numa を交互に16本 (記録試行ではない)
#
# 並びは plain numa numa plain の4つ組を4回. 対で向きを入れ替えると,
# 「対のなかの位置」が片方の腕に乗らない (記録 #15 の門番で P0 に出た形).
#
# ⚠️ experiments/retreat_profile の8本と比べない. 別の日の走行で機械の状態が違う.
#    比べるのはこの16本の中だけ.
#
# 本数の根拠: retreat_profile では8本中2本 (p1 が 2.41 倍, p7 が 1.14 倍),
# gate_15 では16本中5本 (31%) が高フォルト側だった.
# 対照側 (plain) 8本で1本も出ない確率は (11/16)^8 = 5.0%.
# plain 側に1本も出なかったら判定不能. そう書いて止める.
#
# ⚠️ 1本あたり後退解析 8 分ほどなので, 16本で約3時間かかる.
#    その間このマシンで他の計算を回さないこと.
set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

for i in 1 2 3 4; do
    "$HERE/run.sh" plain "n${i}a"
    # n1b だけ dat/ を残す. oracle/fingerprint.tsv と照合して
    # 「片ノードに固定しても答えが変わっていない」ことを見る
    if [ "$i" -eq 1 ]; then
        "$HERE/run.sh" numa "n${i}b" keep
    else
        "$HERE/run.sh" numa "n${i}b"
    fi
    "$HERE/run.sh" numa  "n${i}c"
    "$HERE/run.sh" plain "n${i}d"
done
echo "=== 全16本 完了 $(date --iso-8601=seconds) ==="
