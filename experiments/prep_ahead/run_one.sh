#!/bin/bash
# 実験 prep_ahead: 空の dat/ から完走を1本 (記録試行ではない. perf なし)
#
#   LOGS=<生ログの置き場所> run_one.sh <base|prep1> <ラベル>
#
# experiments/dtm_ahead/run_one.sh の写しを, この実験の腕と #40 本走に向けたもの.
# 走る前に, ノード0の 2 MiB 以上の空きブロックが HUGEFREE_MIN_GIB (既定 8. tools/run.sh と同じ) 以上あるかを見て
# <LOGS>/<ラベル>_hugefree.txt に残す. 足りなければ走らずに止める (exit 4. 止める条件 4). キャッシュを落とすかは本人が決める.
#
# 走ったあとは毎本その場で見て, どれかに掛かったら dat/ を残して止める (止める条件 1〜3):
#   - thp_fault_fallback の前後差が 0, 巨大ページが表と配列の全部に付いている (check.py huge)
#   - オラクル174行 (tools/verify_log.py)
#   - 答え (check.py answer): 両腕とも dat/ の md5 一覧の sha256 が #40 本走と同じ (a982b554596c…)
#   - forward.tsv の件数の列が results/40_dtm_ahead/forward.tsv と一致 (check.py rounds)
#   - DIFF_DAT=1 なら, dat/ 全213ファイルを #40 本走の dat/ と diff -rq でも比べる (一致の検査の1本)
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$HERE/lib.sh"
ARM="${1:?腕を指定すること (base|prep1)}"
LABEL="${2:?ラベルを指定すること}"
LOGDIR="${LOGS:?生ログの置き場所を LOGS で渡すこと}"
W="$ROOT/runs/prep_ahead/$LABEL"
REFDAT="$ROOT/runs/20261020-163501_40_dtm_ahead/dat"
NUMA=(numactl --cpunodebind=0 --membind=0)
HUGEFREE_MIN_GIB="${HUGEFREE_MIN_GIB:-8}"
L="$LOGDIR/$LABEL"

command -v numactl > /dev/null || { echo "numactl が無い" >&2; exit 2; }
[ -d "$REFDAT" ] || { echo "#40 本走の dat/ が無い: $REFDAT" >&2; exit 2; }
if [ -e "$W" ]; then
    echo "前回の $W が残っている. 退避するか消してから起動すること" >&2
    exit 2
fi
AVAIL_KB=$(df -Pk "$ROOT" | awk 'NR==2 {print $4}')
if [ "$AVAIL_KB" -lt 10000000 ]; then
    echo "空きが 10 GB 未満 ($AVAIL_KB KB)" >&2
    exit 2
fi

mkdir -p "$LOGDIR"
FREE0=$(hugefree_gib 0)
{
    echo "# 走る前 ($(date --iso-8601=seconds)) のノード0の /proc/buddyinfo. 2 MiB 以上の空きブロック $FREE0 GiB (しきい値 $HUGEFREE_MIN_GIB GiB)"
    grep '^Node 0' /proc/buddyinfo 2>/dev/null || true
} > "${L}_hugefree.txt"
echo "--- $LABEL の前のノード0: 2 MiB 以上の空きブロック $FREE0 GiB (しきい値 $HUGEFREE_MIN_GIB) ---"
if ! awk -v have="$FREE0" -v need="$HUGEFREE_MIN_GIB" 'BEGIN { exit !(have != "-" && have + 0 >= need + 0) }'; then
    echo "!!! ノード0の巨大ページのための空きが足りない. $LABEL は走らせずに止める (本人に知らせる. 止める条件 4)" >&2
    exit 4
fi

mkdir -p "$W/dat" "$W/kaiseki_log"
BUILD=$("$HERE/build_arm.sh" "$ARM" "$W")
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
echo "U_loop：$(awk -F'\t' '$1 == "U_loop" {print $2}' "$W/kaiseki_log/retreat_summary.tsv") 秒"

cp "$W/kaiseki_log/kaizenkaiseki1.txt" "${L}_main.log"
cp "$W/kaiseki_log/forward.tsv" "${L}_forward.tsv"
cp "$W/kaiseki_log/forward_summary.tsv" "${L}_forward_summary.tsv"
cp "$W/kaiseki_log/retreat_summary.tsv" "${L}_retreat_summary.tsv"
# 計時したコマンド行に作業の絶対パスが入るなら, リポジトリの場所を伏せて残す
sed -e "s|$ROOT|<repo>|g" "$W/time.txt" > "${L}_time.txt"
cp "$W/freq.log" "${L}_freq.log"
cp "$W/vmstat.tsv" "${L}_vmstat.tsv"

echo "--- 巨大ページと thp_fault_fallback ---"
if ! LOGS="$LOGDIR" python3 "$HERE/check.py" huge "$LABEL"; then
    echo "!!! 巨大ページが頼んだぶん付かなかった (止める条件 3). 調査用に dat/ を残して止める" >&2
    exit 1
fi
echo "--- オラクル 174行 ---"
if ! python3 "$ROOT/tools/verify_log.py" "$W/kaiseki_log/kaizenkaiseki1.txt"; then
    echo "!!! オラクル検証 FAIL (止める条件 1・2). 調査用に dat/ を残して止める" >&2
    exit 1
fi
echo "--- 答え ($ARM) ---"
set +e
LOGS="$LOGDIR" python3 "$HERE/check.py" answer "$W/dat" > "${L}_answer.txt" 2>&1
RC=$?
set -e
cat "${L}_answer.txt"
if [ "$RC" -ne 0 ]; then
    echo "!!! 答えの検査が外れた (止める条件 1・2). 調査用に dat/ を残して止める" >&2
    exit 1
fi
echo "--- 件数の列を #40 本走と照合 ---"
if ! LOGS="$LOGDIR" python3 "$HERE/check.py" rounds "$LABEL"; then
    echo "!!! 件数の列が #40 と違う (止める条件 1・2). 調査用に dat/ を残して止める" >&2
    exit 1
fi
if [ "${DIFF_DAT:-0}" = 1 ]; then
    echo "--- dat/ を #40 本走の dat/ と diff -rq ---"
    set +e
    diff -rq "$W/dat" "$REFDAT" > "${L}_diff.txt" 2>&1
    RC=$?
    set -e
    sed -i -e "s|$ROOT|<repo>|g" "${L}_diff.txt"
    echo "diff -rq: exit=$RC ($(wc -l < "${L}_diff.txt") 行). ファイル $(find "$W/dat" -type f | wc -l) 個" | tee -a "${L}_diff.txt"
    if [ "$RC" -ne 0 ]; then
        echo "!!! dat/ が #40 本走と違う (止める条件 1). 調査用に dat/ を残して止める" >&2
        exit 1
    fi
fi
rm -rf "$W/dat"
echo "=== 完了 $LABEL $(date --iso-8601=seconds) ==="
