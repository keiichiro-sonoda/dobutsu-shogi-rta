#!/bin/bash
# 完走の比較: 空の dat/ から完走を1本 (実験 mirror1_keep。記録試行ではない. 記録の門番でもない)
#
#   run_one.sh <base|mirror1|mirror1_keep> <ラベル>
#
# experiments/gate_36_bb_unmove/run_one.sh の写し. 腕は build_arm.sh (impl/36_bb_unmove の写しにパッチ) で組む.
# 走る前に, ノード0の 2 MiB 以上の空きブロックが HUGEFREE_MIN_GIB (既定 16) 以上あるかを見て
# logs/compare/<ラベル>_hugefree.txt に残す. 足りなければ走らずに止める (exit 4). キャッシュを落とすかは本人が決める.
#
# 走ったあとは毎本その場で見て, どれかに掛かったら dat/ を残して止める:
#   - オラクル174行 (tools/verify_log.py)
#   - 答え (check_full.py): base と mirror1_keep は dat/ の md5 一覧の sha256 が #36 本走と同じ.
#     mirror1 は 指紋・全探索の側のバイト一致・ファイルの名前と件数・手数ごとに束ねた集合の一致
#   - forward.tsv の件数の列が results/36_bb_unmove/forward.tsv と一致 (compare_stats.py rounds)
#   - /proc/vmstat の thp_fault_fallback の前後差が 0
#   - 巨大ページが表と配列の全部に付いている (しきい値は門番 #36 と同じ. compare_stats.py huge)
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$HERE/lib.sh"
ARM="${1:?腕を指定すること (base|mirror1|mirror1_keep)}"
case "$ARM" in base | mirror1 | mirror1_keep) ;; *) echo "知らない腕: $ARM" >&2; exit 2 ;; esac
LABEL="${2:?ラベルを指定すること}"
W="$ROOT/runs/mirror1_keep/cmp_$LABEL"
L="$HERE/logs/compare"
NUMA=(numactl --cpunodebind=0 --membind=0)
HUGEFREE_MIN_GIB="${HUGEFREE_MIN_GIB:-16}"

command -v numactl > /dev/null || { echo "numactl が無い" >&2; exit 2; }
if [ -e "$W" ]; then
    echo "前回の $W が残っている. 退避するか消してから起動すること" >&2
    exit 2
fi
AVAIL_KB=$(df -Pk "$ROOT" | awk 'NR==2 {print $4}')
if [ "$AVAIL_KB" -lt 10000000 ]; then
    echo "空きが 10 GB 未満 ($AVAIL_KB KB)" >&2
    exit 2
fi

mkdir -p "$L"
FREE0=$(hugefree_gib 0)
{
    echo "# 走る前 ($(date --iso-8601=seconds)) のノード0の /proc/buddyinfo. 2 MiB 以上の空きブロック $FREE0 GiB (しきい値 $HUGEFREE_MIN_GIB GiB)"
    grep '^Node 0' /proc/buddyinfo 2>/dev/null || true
} > "$L/${LABEL}_hugefree.txt"
echo "--- $LABEL の前のノード0: 2 MiB 以上の空きブロック $FREE0 GiB (しきい値 $HUGEFREE_MIN_GIB) ---"
if ! awk -v have="$FREE0" -v need="$HUGEFREE_MIN_GIB" 'BEGIN { exit !(have != "-" && have + 0 >= need + 0) }'; then
    echo "!!! ノード0の巨大ページのための空きが足りない. $LABEL は走らせずに止める (本人に知らせる)" >&2
    exit 4
fi

mkdir -p "$W/dat" "$W/kaiseki_log"
BUILD=$("$HERE/build_arm.sh" "$ARM" "$W" | tail -1)
echo "=== 開始 $LABEL ($BUILD) $(date --iso-8601=seconds) ==="

freq_header > "$W/freq.log"
sample_hw >> "$W/freq.log" 2>/dev/null &
SPID=$!
trap 'kill "$SPID" 2>/dev/null || true' EXIT
{ vmstat_header; vmstat_row before; } > "$W/vmstat.tsv"
set +e
(cd "$W" && /usr/bin/time -v "${NUMA[@]}" python3 ./animal_shogi.py > stdout.txt 2> time.txt)
RC=$?
set -e
vmstat_row after >> "$W/vmstat.tsv"
kill "$SPID" 2>/dev/null || true

echo "=== 終了 $LABEL $(date --iso-8601=seconds) (exit=$RC) ==="
grep -E "Elapsed|Maximum resident|Minor \(reclaiming" "$W/time.txt" || true
if [ "$RC" -ne 0 ]; then
    echo "!!! 解析が落ちた (exit=$RC). 再開せず, 調査用に dat/ を残して止める" >&2
    exit "$RC"
fi
FT=$(awk -F'\t' '$1 == "forward_total" {print $2}' "$W/kaiseki_log/forward_summary.tsv")
RT=$(awk -F'\t' '$1 == "retreat_total" {print $2}' "$W/kaiseki_log/retreat_summary.tsv")
echo "全探索の所要時間：$FT 秒 / 後退解析の所要時間：$RT 秒"

cp "$W/kaiseki_log/kaizenkaiseki1.txt" "$L/${LABEL}_main.log"
cp "$W/kaiseki_log/kaiseki_log7.txt" "$L/${LABEL}_sub.log"
cp "$W/kaiseki_log/forward.tsv" "$L/${LABEL}_forward.tsv"
cp "$W/kaiseki_log/forward_summary.tsv" "$L/${LABEL}_forward_summary.tsv"
cp "$W/kaiseki_log/retreat_summary.tsv" "$L/${LABEL}_retreat_summary.tsv"
cp "$W/time.txt" "$L/${LABEL}_time.txt"
cp "$W/freq.log" "$L/${LABEL}_freq.log"
cp "$W/vmstat.tsv" "$L/${LABEL}_vmstat.tsv"

FB=$(awk -F'\t' 'NR == 1 {for (i = 1; i <= NF; i++) if ($i == "thp_fault_fallback") c = i}
                 NR == 2 {b = $c} NR == 3 {print $c - b}' "$W/vmstat.tsv")
echo "--- thp_fault_fallback の前後差: $FB ---"
if [ "$FB" != "0" ]; then
    echo "!!! 巨大ページが頼んだぶん付かなかった (止める条件). 調査用に dat/ を残して止める" >&2
    exit 1
fi
echo "--- 巨大ページ (表と配列) ---"
if ! python3 "$HERE/compare_stats.py" huge "$LABEL"; then
    echo "!!! 巨大ページが表と配列の全部に付いていない (止める条件). 調査用に dat/ を残して止める" >&2
    exit 1
fi
echo "--- オラクル 174行 ---"
if ! python3 "$ROOT/tools/verify_log.py" "$W/kaiseki_log/kaizenkaiseki1.txt"; then
    echo "!!! オラクル検証 FAIL (止める条件). 調査用に dat/ を残して止める" >&2
    exit 1
fi
echo "--- 答え ($ARM) ---"
MODE=md5
[ "$ARM" = mirror1 ] && MODE=mirror1
set +e
python3 "$HERE/check_full.py" "$MODE" "$W/dat" "$L/${LABEL}_depth.tsv" 2>&1 | sed -e "s|$ROOT|<repo>|g" \
    > "$L/${LABEL}_answer.txt"
RC=${PIPESTATUS[0]}
set -e
cat "$L/${LABEL}_answer.txt"
if [ "$RC" -ne 0 ]; then
    echo "!!! 答えの検査が外れた (止める条件). 調査用に dat/ を残して止める" >&2
    exit 1
fi
echo "--- 件数の列を #36 本走と照合 ---"
if ! python3 "$HERE/compare_stats.py" rounds "$L/${LABEL}_forward.tsv"; then
    echo "!!! 件数の列が #36 と違う (止める条件). 調査用に dat/ を残して止める" >&2
    exit 1
fi
rm -rf "$W/dat"
echo "=== 完了 $LABEL $(date --iso-8601=seconds) ==="
