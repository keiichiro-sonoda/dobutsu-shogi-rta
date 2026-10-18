#!/bin/bash
# 実験 rank_fast の段1: 空の dat/ から完走を1本, F1・U_loop・U_draw の3つの区間を perf record で取る (記録試行ではない)
#
#   run_one.sh <ラベル>
#
# experiments/perf_34/run_one.sh の record の本の作り (F1 は起動した perf, U_loop は python に -p で付けた perf) に,
# U_draw を数える3つ目の perf (これも -p で付ける) を足したもの. 3つとも -D -1 (止めた状態で始める) と --control fifo: で,
# 腕のパッチ (perf_34 の perf_ctl.patch と patches/u_draw_ctl.patch) が区間の境界で enable / disable を送る.
# 取るのは3つのイベントで, どれも pp (PEBS) と -d (ロードの番地). 周期は素数で, イベントごとに cpu/…,period=…/ で書く
# (experiments/perf_38 の試しの本で, -c を並べる書き方だと cycles の番地が全部カーネルに付いた):
#   cycles                             F1・U_loop 2000003, U_draw 400009
#   mem_load_uops_retired.l1_miss      F1・U_loop 2003,    U_draw 20011
#   mem_load_uops_retired.l2_hit       F1・U_loop 2003,    U_draw 20011
# 解析は numactl --cpunodebind=0 --membind=0 で固定する. perf 自身は固定しない.
#
# 走る前に, ノード0の 2 MiB 以上の空きブロックが HUGEFREE_MIN_GIB (既定 8) 以上あるかを見て
# logs/<ラベル>_hugefree.txt に残す. 足りなければ走らずに止める (exit 4. 止める条件 5). キャッシュを落とすかは本人が決める.
# 走ったあとは毎本その場で見て, どれかに掛かったら dat/ を残して止める (止める条件 1):
#   - オラクル174行 (tools/verify_log.py)
#   - 答え (check.py answer): dat/ の md5 一覧の sha256 が #38 本走と同じ (a982b554596c…)
#   - forward.tsv の件数の列が results/38_precheck/forward.tsv と一致 (check.py rounds)
#   - thp_fault_fallback の前後差が 0, 巨大ページが表と配列の全部に付いている (check.py huge)
#   - U_loop と U_draw を数える perf が 0 以外で終わった
# shellcheck disable=SC2054
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$HERE/lib.sh"
LABEL="${1:?ラベルを指定すること}"
W="$ROOT/runs/rank_fast/$LABEL"
NUMA=(numactl --cpunodebind=0 --membind=0)
HUGEFREE_MIN_GIB="${HUGEFREE_MIN_GIB:-8}"
L="$HERE/logs/$LABEL"

EV_BIG=(-e "cpu/cycles,period=2000003/pp" -e "cpu/mem_load_uops_retired.l1_miss,period=2003/pp"
    -e "cpu/mem_load_uops_retired.l2_hit,period=2003/pp")
EV_DRAW=(-e "cpu/cycles,period=400009/pp" -e "cpu/mem_load_uops_retired.l1_miss,period=20011/pp"
    -e "cpu/mem_load_uops_retired.l2_hit,period=20011/pp")

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
    echo "!!! ノード0の巨大ページのための空きが足りない. $LABEL は走らせずに止める (本人に知らせる. 止める条件 5)" >&2
    exit 4
fi

mkdir -p "$W/dat" "$W/kaiseki_log"
BUILD=$("$HERE/build_arm.sh" "$W")
echo "=== 開始 $LABEL ($BUILD) $(date --iso-8601=seconds) ==="

freq_header > "$W/freq.log"
sample_hw >> "$W/freq.log" 2>/dev/null &
SPID=$!
trap 'kill "$SPID" 2>/dev/null || true' EXIT
{ vmstat_header; vmstat_row before; } > "$W/vmstat.tsv"

# 区間ごとの FIFO. このシェルが読み書き両方で開いておく (perf と python が片側だけで開いても止まらないように)
mkfifo "$W/ctl_F1" "$W/ack_F1" "$W/ctl_U" "$W/ack_U" "$W/ctl_D" "$W/ack_D"
exec 20<>"$W/ctl_F1" 21<>"$W/ack_F1" 22<>"$W/ctl_U" 23<>"$W/ack_U" 24<>"$W/ctl_D" 25<>"$W/ack_D"
PA=(perf record -q -d -o "$W/rec_F1.data" "${EV_BIG[@]}" -D -1 "--control=fifo:$W/ctl_F1,$W/ack_F1" --)
PB=(perf record -q -d -o "$W/rec_U_loop.data" "${EV_BIG[@]}" -D -1 "--control=fifo:$W/ctl_U,$W/ack_U")
PC=(perf record -q -d -o "$W/rec_U_draw.data" "${EV_DRAW[@]}" -D -1 "--control=fifo:$W/ctl_D,$W/ack_D")

set +e
(cd "$W" && PERF_CTL_F1="$W/ctl_F1" PERF_ACK_F1="$W/ack_F1" \
    PERF_CTL_U_loop="$W/ctl_U" PERF_ACK_U_loop="$W/ack_U" \
    PERF_CTL_U_draw="$W/ctl_D" PERF_ACK_U_draw="$W/ack_D" \
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
echo "python3 pid を取った. U_loop と U_draw の perf を付ける"
"${PB[@]}" -p "$PY" > "$W/perf_U_loop.out" 2>&1 &
PBPID=$!
"${PC[@]}" -p "$PY" > "$W/perf_U_draw.out" 2>&1 &
PCPID=$!
wait "$TPID"
RC=$?
wait "$PBPID"
RCB=$?
wait "$PCPID"
RCC=$?
set -e
vmstat_row after >> "$W/vmstat.tsv"
kill "$SPID" 2>/dev/null || true

echo "=== 終了 $LABEL $(date --iso-8601=seconds) (exit=$RC) ==="
grep -E "Elapsed|Maximum resident|Minor \(reclaiming" "$W/time.txt" || true
if [ "$RC" -ne 0 ]; then
    echo "!!! 解析が落ちた (exit=$RC). 再開せず, 調査用に dat/ を残して止める" >&2
    exit "$RC"
fi
if [ "$RCB" -ne 0 ] || [ "$RCC" -ne 0 ]; then
    echo "!!! U_loop か U_draw を数える perf が 0 以外で終わった ($RCB / $RCC). 調査用に dat/ を残して止める" >&2
    exit 1
fi
echo "F1：$(awk -F'\t' '$1 == "F1" {print $2}' "$W/kaiseki_log/forward_summary.tsv") 秒"
for s in U_loop U_draw; do
    echo "$s：$(awk -F'\t' -v s="$s" '$1 == s {print $2}' "$W/kaiseki_log/retreat_summary.tsv") 秒"
done

cp "$W/kaiseki_log/kaizenkaiseki1.txt" "${L}_main.log"
cp "$W/kaiseki_log/forward.tsv" "${L}_forward.tsv"
cp "$W/kaiseki_log/forward_summary.tsv" "${L}_forward_summary.tsv"
cp "$W/kaiseki_log/retreat_summary.tsv" "${L}_retreat_summary.tsv"
# 計時したコマンド行に作業の絶対パスが入るので, リポジトリの場所を伏せて残す
sed -e "s|$ROOT|<repo>|g" "$W/time.txt" > "${L}_time.txt"
cp "$W/freq.log" "${L}_freq.log"
cp "$W/vmstat.tsv" "${L}_vmstat.tsv"
for s in F1 U_loop U_draw; do
    perf script -i "$W/rec_$s.data" -F event,ip,sym,symoff,dso,addr 2> /dev/null \
        | python3 "$HERE/attribute.py" "$W/animal_shogi.so" "$W/g/animal_shogi.so" > "${L}_record_$s.tsv"
    {
        echo "# perf report --stats の THROTTLE / UNTHROTTLE と標本の数 (kernel.perf_event_max_sample_rate = $(cat /proc/sys/kernel/perf_event_max_sample_rate))"
        perf report -i "$W/rec_$s.data" --stats 2> /dev/null | grep -E "THROTTLE|SAMPLE|LOST" || true
    } > "${L}_record_stats_$s.txt"
    head -4 "${L}_record_$s.tsv"
done

echo "--- 巨大ページと thp_fault_fallback ---"
if ! python3 "$HERE/check.py" huge "$LABEL"; then
    echo "!!! 巨大ページが頼んだぶん付かなかった. 調査用に dat/ を残して止める" >&2
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
echo "--- 件数の列を #38 本走と照合 ---"
if ! python3 "$HERE/check.py" rounds "$LABEL"; then
    echo "!!! 件数の列が #38 と違う (止める条件 1). 調査用に dat/ を残して止める" >&2
    exit 1
fi
rm -rf "$W/dat"
echo "=== 完了 $LABEL $(date --iso-8601=seconds) ==="
