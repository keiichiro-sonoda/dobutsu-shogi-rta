#!/bin/bash
# 実験 perf_38: 空の dat/ から完走を1本, F1 の区間だけを perf で数える (記録試行ではない)
#
#   run_one.sh <r37|r38> <種類> <ラベル>
#
# 種類:
#   stat:<組>   perf stat で F1 を数える (EVENTS の組. 多重化しないように3つずつに分けた)
#   record      perf record で F1 の標本を取る (cycles:pp と mem_load_uops_retired.l3_miss:pp. 周期は素数)
#
# experiments/perf_34/run_one.sh の写しを F1 だけにしたもの. 起動した perf が -D -1 (止めた状態で始める) と
# --control fifo: で, 腕のパッチ (perf_34 の perf_ctl.patch) が F1 の境界で送る enable / disable を受ける.
# U_loop は数えない (#38 でコードが変わっていない). 解析は numactl --cpunodebind=0 --membind=0 で固定する. perf 自身は固定しない.
#
# 走る前に, ノード0の 2 MiB 以上の空きブロックが HUGEFREE_MIN_GIB (既定 8. experiments/hugefree_need2 で見直した基準) 以上あるかを
# 見て logs/<ラベル>_hugefree.txt に残す. 足りなければ走らずに止める (exit 4). キャッシュを落とすかは本人が決める.
# 走ったあとは毎本その場で見て, どれかに掛かったら dat/ を残して止める:
#   - オラクル174行 (tools/verify_log.py)
#   - 答え (check.py answer): dat/ の md5 一覧の sha256 が #37 本走と同じ (a982b554596c…. #38 本走とも同じ)
#   - forward.tsv の件数の列が results/37_mirror1/forward.tsv と一致 (check.py rounds)
#   - thp_fault_fallback の前後差が 0, 巨大ページが表と配列の全部に付いている (check.py huge)
#   - perf stat の多重化 (どのイベントも 100% で数えたか)
# perf stat の -x, は出力の区切りの指定 (配列の要素の区切りではない)
# shellcheck disable=SC2054
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$HERE/lib.sh"
ARM="${1:?腕を指定すること (r37|r38)}"
KIND="${2:?種類を指定すること (stat:<組>|record)}"
LABEL="${3:?ラベルを指定すること}"
W="$ROOT/runs/perf_38/$LABEL"
NUMA=(numactl --cpunodebind=0 --membind=0)
HUGEFREE_MIN_GIB="${HUGEFREE_MIN_GIB:-8}"
L="$HERE/logs/$LABEL"
# 標本の周期 (素数). cycles は F1 (約 1.5 × 10^11 サイクル) で 7 万個ほど, LLC のロードミスは (#34 で局面 100 個に1個) 1万個ほど
P_CYC=2000003
P_L3=211

# 組ごとのイベント. cycles と instructions は固定カウンタ. ほかは3つまで (NMI watchdog が汎用を1つ使う). T1〜C2 は perf_34 と同じ
declare -A EVENTS=(
    [T1]="cycles,instructions,uops_issued.any,uops_retired.retire_slots,idq_uops_not_delivered.core"
    [T2]="cycles,instructions,int_misc.recovery_cycles,idq_uops_not_delivered.cycles_0_uops_deliv.core,br_misp_retired.all_branches"
    [M1]="cycles,instructions,cycle_activity.stalls_mem_any,cycle_activity.stalls_total,resource_stalls.sb"
    [M2]="cycles,instructions,uops_executed.cycles_ge_1_uop_exec,uops_executed.cycles_ge_2_uops_exec,uops_executed.cycles_ge_3_uops_exec"
    [M3]="cycles,instructions,rs_events.empty_cycles,br_inst_retired.all_branches,cycle_activity.stalls_l2_miss"
    [C1]="cycles,instructions,mem_load_uops_retired.l1_miss,mem_load_uops_retired.l2_miss,mem_load_uops_retired.l3_miss"
    [C2]="cycles,instructions,dtlb_load_misses.miss_causes_a_walk,dtlb_load_misses.walk_duration,dtlb_load_misses.stlb_hit"
    [S1]="cycles,instructions,mem_uops_retired.all_stores,resource_stalls.sb,l2_rqsts.rfo_miss"
)
case "$ARM" in r37 | r38) ;; *) echo "腕は r37 / r38: $ARM" >&2; exit 2 ;; esac
case "$KIND" in
    record) ;;
    stat:*) [ -n "${EVENTS[${KIND#stat:}]:-}" ] || { echo "知らない組: $KIND" >&2; exit 2; } ;;
    *) echo "知らない種類: $KIND" >&2; exit 2 ;;
esac

command -v numactl > /dev/null || { echo "numactl が無い" >&2; exit 2; }
command -v perf > /dev/null || { echo "perf が無い" >&2; exit 2; }
if [ -e "$W" ]; then
    echo "前回の $W が残っている. 退避するか消してから起動すること" >&2
    exit 2
fi
AVAIL_KB=$(df -Pk "$ROOT" | awk 'NR==2 {print $4}')
if [ "$AVAIL_KB" -lt 10000000 ]; then
    echo "空きが 10 GB 未満 ($AVAIL_KB KB)" >&2
    exit 2
fi

mkdir -p "$HERE/logs"
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
echo "=== 開始 $LABEL ($ARM $KIND: $BUILD) $(date --iso-8601=seconds) ==="

freq_header > "$W/freq.log"
sample_hw >> "$W/freq.log" 2>/dev/null &
SPID=$!
trap 'kill "$SPID" 2>/dev/null || true' EXIT
{ vmstat_header; vmstat_row before; } > "$W/vmstat.tsv"

# F1 の FIFO. このシェルが読み書き両方で開いておく (perf と python が片側だけで開いても止まらないように)
mkfifo "$W/ctl_F1" "$W/ack_F1"
exec 20<>"$W/ctl_F1" 21<>"$W/ack_F1"
CF="--control=fifo:$W/ctl_F1,$W/ack_F1"
case "$KIND" in
    stat:*)
        PA=(perf stat -x, -o "$W/stat_F1.csv" -e "${EVENTS[${KIND#stat:}]}" -D -1 "$CF" --)
        ;;
    record)
        PA=(perf record -q -o "$W/rec_F1.data" -e cycles:pp -c "$P_CYC" -e mem_load_uops_retired.l3_miss:pp -c "$P_L3"
            -D -1 "$CF" --)
        ;;
esac

set +e
(cd "$W" && PERF_CTL_F1="$W/ctl_F1" PERF_ACK_F1="$W/ack_F1" \
    exec /usr/bin/time -v "${PA[@]}" "${NUMA[@]}" python3 ./animal_shogi.py > stdout.txt 2> time.txt)
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
F1=$(awk -F'\t' '$1 == "F1" {print $2}' "$W/kaiseki_log/forward_summary.tsv")
echo "F1：$F1 秒"

cp "$W/kaiseki_log/kaizenkaiseki1.txt" "${L}_main.log"
cp "$W/kaiseki_log/forward.tsv" "${L}_forward.tsv"
cp "$W/kaiseki_log/forward_summary.tsv" "${L}_forward_summary.tsv"
cp "$W/kaiseki_log/retreat_summary.tsv" "${L}_retreat_summary.tsv"
# 計時したコマンド行に作業の絶対パスが入るので, リポジトリの場所を伏せて残す
sed -e "s|$ROOT|<repo>|g" "$W/time.txt" > "${L}_time.txt"
cp "$W/freq.log" "${L}_freq.log"
cp "$W/vmstat.tsv" "${L}_vmstat.tsv"
if [ "$KIND" = record ]; then
    perf script -i "$W/rec_F1.data" -F event,ip,sym,symoff,dso 2> /dev/null \
        | python3 "$HERE/attribute.py" "$W/animal_shogi.so" "$W/g/animal_shogi.so" > "${L}_record.tsv"
    {
        echo "# perf report --stats の THROTTLE / UNTHROTTLE と標本の数 (kernel.perf_event_max_sample_rate = $(cat /proc/sys/kernel/perf_event_max_sample_rate))"
        perf report -i "$W/rec_F1.data" --stats 2> /dev/null | grep -E "THROTTLE|SAMPLE" || true
    } > "${L}_record_stats.txt"
    head -3 "${L}_record.tsv"
else
    # perf stat の出力の先頭の "# started on <日時>" の行はそのまま残す (ホスト名は入らない)
    cp "$W/stat_F1.csv" "${L}_stat_F1.csv"
    if awk -F, '!/^#/ && NF > 4 && $5 + 0 < 100 {bad = 1} END {exit !bad}' "${L}_stat_F1.csv"; then
        echo "!!! 多重化が起きた (止める条件 3). 組を分け直す方法は決めずに報告する" >&2
        exit 1
    fi
fi

echo "--- 巨大ページと thp_fault_fallback ---"
if ! python3 "$HERE/check.py" huge "$LABEL"; then
    echo "!!! 巨大ページが頼んだぶん付かなかった (止める条件 4). 調査用に dat/ を残して止める" >&2
    exit 1
fi
echo "--- オラクル 174行 ---"
if ! python3 "$ROOT/tools/verify_log.py" "$W/kaiseki_log/kaizenkaiseki1.txt"; then
    echo "!!! オラクル検証 FAIL (止める条件 1). 調査用に dat/ を残して止める" >&2
    exit 1
fi
echo "--- 答え ---"
set +e
python3 "$HERE/check.py" answer "$W/dat" > "${L}_answer.txt" 2>&1
RC=$?
set -e
cat "${L}_answer.txt"
if [ "$RC" -ne 0 ]; then
    echo "!!! 答えの検査が外れた (止める条件 1). 調査用に dat/ を残して止める" >&2
    exit 1
fi
echo "--- 件数の列を #37 本走と照合 ---"
if ! python3 "$HERE/check.py" rounds "$LABEL"; then
    echo "!!! 件数の列が #37 と違う (止める条件 1). 調査用に dat/ を残して止める" >&2
    exit 1
fi
rm -rf "$W/dat"
echo "=== 完了 $LABEL $(date --iso-8601=seconds) ==="
