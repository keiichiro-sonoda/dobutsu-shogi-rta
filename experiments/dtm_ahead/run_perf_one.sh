#!/bin/bash
# 実験 dtm_ahead: 空の dat/ から完走を1本, U_loop (と F1) の区間を perf で数える (記録試行ではない)
#
#   LOGS=<生ログの置き場所> run_perf_one.sh <base|ahead1> <種類> <ラベル>
#
# 種類:
#   stat:T1 / stat:M1   perf stat (experiments/perf_39 の組 T1 (topdown) と M1 (stalls_mem_any など). 多重化しない3つずつ)
#   record:cyc          perf record で cycles の標本を取る (pp. 周期 2000003)
#
# experiments/perf_39/run_one.sh の写し. 違いは, 腕を選べること (build_arm.sh <腕> <先> perf),
# 組を T1・M1 だけにしたこと, 手数ごとの計装 (perf_39 の depth_log.patch) を当てないこと,
# 標本の寄せ先に perf_39 の attribute.py をそのまま使うこと (番地 → 行は腕の -g の .so で引くので, 行番号は腕のソースの行).
# F1 は起動した perf, U_loop は python に -p で付けた perf. 2つとも -D -1 と --control fifo: で,
# perf_34 の perf_ctl.patch が区間の境界で enable / disable を送る. 解析は numactl --cpunodebind=0 --membind=0 で固定する.
#
# 走る前に, ノード0の 2 MiB 以上の空きブロックが HUGEFREE_MIN_GIB (既定 8) 以上あるかを見て
# <LOGS>/<ラベル>_hugefree.txt に残す. 足りなければ走らずに止める (exit 4. 止める条件 4).
# 走ったあとは毎本その場で見て, どれかに掛かったら dat/ を残して止める:
#   - オラクル174行, 答え (dat/ の md5 一覧の sha256 が #39 本走と同じ), 件数の列 (止める条件 2)
#   - thp_fault_fallback の前後差が 0, 巨大ページが表と配列の全部に付いている (止める条件 3)
#   - U_loop を数える perf が 0 以外で終わった
#   - perf stat の多重化 (どのイベントも 100% で数えたか)
# perf stat の -x, は出力の区切りの指定 (配列の要素の区切りではない)
# shellcheck disable=SC2054
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$HERE/lib.sh"
ARM="${1:?腕を指定すること (base|ahead1)}"
KIND="${2:?種類を指定すること (stat:T1|stat:M1|record:cyc)}"
LABEL="${3:?ラベルを指定すること}"
LOGDIR="${LOGS:?生ログの置き場所を LOGS で渡すこと}"
W="$ROOT/runs/dtm_ahead/$LABEL"
NUMA=(numactl --cpunodebind=0 --membind=0)
HUGEFREE_MIN_GIB="${HUGEFREE_MIN_GIB:-8}"
L="$LOGDIR/$LABEL"

# 組ごとのイベント (perf_39 と同じ). cycles と instructions は固定カウンタ. ほかは3つまで (NMI watchdog が汎用を1つ使う)
declare -A EVENTS=(
    [T1]="cycles,instructions,uops_issued.any,uops_retired.retire_slots,idq_uops_not_delivered.core"
    [M1]="cycles,instructions,cycle_activity.stalls_mem_any,cycle_activity.stalls_total,resource_stalls.sb"
)
case "$KIND" in
    record:cyc) EV=(-e "cpu/cycles,period=2000003/pp") ;;
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
BUILD=$("$HERE/build_arm.sh" "$ARM" "$W" perf)
echo "=== 開始 $LABEL ($KIND: $BUILD) $(date --iso-8601=seconds) ==="

freq_header > "$W/freq.log"
sample_hw >> "$W/freq.log" 2>/dev/null &
SPID=$!
trap 'kill "$SPID" 2>/dev/null || true' EXIT
{ vmstat_header; vmstat_row before; } > "$W/vmstat.tsv"

# 区間ごとの FIFO. このシェルが読み書き両方で開いておく (perf と python が片側だけで開いても止まらないように)
mkfifo "$W/ctl_F1" "$W/ack_F1" "$W/ctl_U" "$W/ack_U"
exec 20<>"$W/ctl_F1" 21<>"$W/ack_F1" 22<>"$W/ctl_U" 23<>"$W/ack_U"
CF="--control=fifo:$W/ctl_F1,$W/ack_F1"
CU="--control=fifo:$W/ctl_U,$W/ack_U"
case "$KIND" in
    stat:*)
        E="${EVENTS[${KIND#stat:}]}"
        PA=(perf stat -x, -o "$W/stat_F1.csv" -e "$E" -D -1 "$CF" --)
        PB=(perf stat -x, -o "$W/stat_U_loop.csv" -e "$E" -D -1 "$CU")
        ;;
    record:*)
        PA=(perf record -q -o "$W/rec_F1.data" "${EV[@]}" -D -1 "$CF" --)
        PB=(perf record -q -o "$W/rec_U_loop.data" "${EV[@]}" -D -1 "$CU")
        ;;
esac

set +e
(cd "$W" && PERF_CTL_F1="$W/ctl_F1" PERF_ACK_F1="$W/ack_F1" \
    PERF_CTL_U_loop="$W/ctl_U" PERF_ACK_U_loop="$W/ack_U" \
    exec /usr/bin/time -v "${PA[@]}" "${NUMA[@]}" python3 ./animal_shogi.py > stdout.txt 2> time.txt) &
TPID=$!
# /usr/bin/time → perf → (numactl が exec した) python3 の順に親子になる. python3 が出るまで待つ
PY=""
for _ in $(seq 1 300); do
    PERFPID=$(pgrep -P "$TPID" -x perf | head -n1 || true)
    if [ -z "$PERFPID" ]; then
        PERFPID=$(pgrep -P "$(pgrep -P "$TPID" | head -n1)" -x perf | head -n1 || true)
    fi
    if [ -n "$PERFPID" ]; then
        PY=$(pgrep -P "$PERFPID" -x python3 | head -n1 || true)
        [ -n "$PY" ] && break
    fi
    sleep 0.1
done
if [ -z "$PY" ]; then
    echo "!!! python3 の pid が取れない. 止める" >&2
    kill "$TPID" 2>/dev/null || true
    exit 1
fi
echo "python3 pid を取った. U_loop の perf を付ける"
"${PB[@]}" -p "$PY" > "$W/perf_U_loop.out" 2>&1 &
PBPID=$!
wait "$TPID"
RC=$?
wait "$PBPID"
RCB=$?
set -e
vmstat_row after >> "$W/vmstat.tsv"
kill "$SPID" 2>/dev/null || true

echo "=== 終了 $LABEL $(date --iso-8601=seconds) (exit=$RC) ==="
grep -E "Elapsed|Maximum resident|Minor \(reclaiming" "$W/time.txt" || true
if [ "$RC" -ne 0 ]; then
    echo "!!! 解析が落ちた (exit=$RC). 再開せず, 調査用に dat/ を残して止める" >&2
    exit "$RC"
fi
if [ "$RCB" -ne 0 ]; then
    echo "!!! U_loop を数える perf が 0 以外で終わった ($RCB). 調査用に dat/ を残して止める" >&2
    exit 1
fi
echo "F1：$(awk -F'\t' '$1 == "F1" {print $2}' "$W/kaiseki_log/forward_summary.tsv") 秒"
echo "U_loop：$(awk -F'\t' '$1 == "U_loop" {print $2}' "$W/kaiseki_log/retreat_summary.tsv") 秒"

cp "$W/kaiseki_log/kaizenkaiseki1.txt" "${L}_main.log"
cp "$W/kaiseki_log/forward.tsv" "${L}_forward.tsv"
cp "$W/kaiseki_log/forward_summary.tsv" "${L}_forward_summary.tsv"
cp "$W/kaiseki_log/retreat_summary.tsv" "${L}_retreat_summary.tsv"
# 計時したコマンド行に作業の絶対パスが入るので, リポジトリの場所を伏せて残す
sed -e "s|$ROOT|<repo>|g" "$W/time.txt" > "${L}_time.txt"
cp "$W/freq.log" "${L}_freq.log"
cp "$W/vmstat.tsv" "${L}_vmstat.tsv"
case "$KIND" in
    record:*)
        for s in F1 U_loop; do
            perf script -i "$W/rec_$s.data" -F event,ip,sym,symoff,dso 2> /dev/null \
                | python3 "$ROOT/experiments/perf_39/attribute.py" "$W/animal_shogi.so" "$W/g/animal_shogi.so" > "${L}_record_$s.tsv"
            {
                echo "# perf report --stats の THROTTLE / UNTHROTTLE と標本の数 (kernel.perf_event_max_sample_rate = $(cat /proc/sys/kernel/perf_event_max_sample_rate))"
                perf report -i "$W/rec_$s.data" --stats 2> /dev/null | grep -E "THROTTLE|SAMPLE|LOST" || true
            } > "${L}_record_stats_$s.txt"
            head -4 "${L}_record_$s.tsv"
        done
        ;;
    stat:*)
        # perf stat の出力の先頭の "# started on <日時>" の行はそのまま残す (ホスト名は入らない)
        for s in F1 U_loop; do
            cp "$W/stat_$s.csv" "${L}_stat_$s.csv"
            if awk -F, '!/^#/ && NF > 4 && $5 + 0 < 100 {bad = 1} END {exit !bad}' "${L}_stat_$s.csv"; then
                echo "!!! $s で多重化が起きた. 組を分け直す方法は決めずに報告する" >&2
                exit 1
            fi
        done
        ;;
esac

echo "--- 巨大ページと thp_fault_fallback ---"
if ! LOGS="$LOGDIR" python3 "$HERE/check.py" huge "$LABEL"; then
    echo "!!! 巨大ページが頼んだぶん付かなかった (止める条件 3). 調査用に dat/ を残して止める" >&2
    exit 1
fi
echo "--- オラクル 174行 ---"
if ! python3 "$ROOT/tools/verify_log.py" "$W/kaiseki_log/kaizenkaiseki1.txt"; then
    echo "!!! オラクル検証 FAIL (止める条件 2). 調査用に dat/ を残して止める" >&2
    exit 1
fi
echo "--- 答え ---"
set +e
LOGS="$LOGDIR" python3 "$HERE/check.py" answer "$W/dat" > "${L}_answer.txt" 2>&1
RC=$?
set -e
cat "${L}_answer.txt"
if [ "$RC" -ne 0 ]; then
    echo "!!! 答えの検査が外れた (止める条件 2). 調査用に dat/ を残して止める" >&2
    exit 1
fi
echo "--- 件数の列を #39 本走と照合 ---"
if ! LOGS="$LOGDIR" python3 "$HERE/check.py" rounds "$LABEL"; then
    echo "!!! 件数の列が #39 と違う (止める条件 2). 調査用に dat/ を残して止める" >&2
    exit 1
fi
rm -rf "$W/dat"
echo "=== 完了 $LABEL $(date --iso-8601=seconds) ==="
