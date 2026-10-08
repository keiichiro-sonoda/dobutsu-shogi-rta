#!/bin/bash
# 実験 perf_34: 空の dat/ から完走を1本 (記録試行ではない)
#
#   run_one.sh <種類> <ラベル>
#
# 種類:
#   base         perf を付けない (段の秒の基準)
#   dump         perf を付けず, ベンチの入力 (F1 の各ラウンドと U_loop の各段から連続した 4,096 局面) を書き出す.
#                段の秒は比べない
#   stat:<組>    perf stat で, F1 と U_loop を別々の perf が数える (EVENTS の組. 多重化しないように分けた)
#   record       perf record (cycles の標本) で, F1 と U_loop を別々の perf が取る
#
# F1 は起動した perf が, U_loop は python に -p で付けた perf が数える. どちらも -D -1 (止めた状態で始める) と
# --control fifo: で, 腕のパッチ (patches/perf_ctl.patch) が段の境界で enable / disable を送る
# (FIFO のパスを PERF_CTL_<段> / PERF_ACK_<段> で渡す).
# 解析は numactl --cpunodebind=0 --membind=0 で固定する. perf 自身は固定しない.
#
# 走る前に, ノード0の 2 MiB 以上の空きブロックが HUGEFREE_MIN_GIB (既定 16. 門番と同じ) 以上あるかを見て
# logs/<ラベル>_hugefree.txt に残す. 足りなければ走らずに止める (exit 4). キャッシュを落とすかは本人が決める.
# 走ったあとは毎本その場で見て, どれかに掛かったら dat/ を残して止める:
#   - オラクル174行 (tools/verify_log.py)
#   - 答え (experiments/gate_34_unmove/check_answer.py new): 全探索の側のバイト比較・名前と件数・指紋
#   - forward.tsv の件数の列が results/34_unmove/forward.tsv と一致 (check.py rounds)
#   - thp_fault_fallback の前後差が 0, 巨大ページが表と配列の全部に付いている (check.py huge)
# perf stat の -x, は出力の区切りの指定 (配列の要素の区切りではない)
# shellcheck disable=SC2054
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$HERE/lib.sh"
KIND="${1:?種類を指定すること (base|dump|stat:<組>|record)}"
LABEL="${2:?ラベルを指定すること}"
W="$ROOT/runs/perf_34/$LABEL"
REFDAT="$ROOT/runs/20261004-091929_33_hot_layout/dat"
NUMA=(numactl --cpunodebind=0 --membind=0)
HUGEFREE_MIN_GIB="${HUGEFREE_MIN_GIB:-16}"
L="$HERE/logs/$LABEL"

# 組ごとのイベント. cycles と instructions は固定カウンタ. ほかは3つまで (NMI watchdog が汎用を1つ使う)
declare -A EVENTS=(
    [T1]="cycles,instructions,uops_issued.any,uops_retired.retire_slots,idq_uops_not_delivered.core"
    [T2]="cycles,instructions,int_misc.recovery_cycles,idq_uops_not_delivered.cycles_0_uops_deliv.core,br_misp_retired.all_branches"
    [M1]="cycles,instructions,cycle_activity.stalls_mem_any,cycle_activity.stalls_total,resource_stalls.sb"
    [M2]="cycles,instructions,uops_executed.cycles_ge_1_uop_exec,uops_executed.cycles_ge_2_uops_exec,uops_executed.cycles_ge_3_uops_exec"
    [M3]="cycles,instructions,rs_events.empty_cycles,br_inst_retired.all_branches,cycle_activity.stalls_l2_miss"
    [C1]="cycles,instructions,mem_load_uops_retired.l1_miss,mem_load_uops_retired.l2_miss,mem_load_uops_retired.l3_miss"
    [C2]="cycles,instructions,dtlb_load_misses.miss_causes_a_walk,dtlb_load_misses.walk_duration,dtlb_load_misses.stlb_hit"
)
case "$KIND" in
    base | dump | record) ;;
    stat:*) [ -n "${EVENTS[${KIND#stat:}]:-}" ] || { echo "知らない組: $KIND" >&2; exit 2; } ;;
    *) echo "知らない種類: $KIND" >&2; exit 2 ;;
esac

command -v numactl > /dev/null || { echo "numactl が無い" >&2; exit 2; }
command -v perf > /dev/null || { echo "perf が無い" >&2; exit 2; }
[ -d "$REFDAT" ] || { echo "#33 本走の dat/ が無い: $REFDAT" >&2; exit 2; }
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
    echo "!!! ノード0の巨大ページのための空きが足りない. $LABEL は走らせずに止める (本人に知らせる)" >&2
    exit 4
fi

mkdir -p "$W/dat" "$W/kaiseki_log"
BUILD=$("$HERE/build_arm.sh" "$W")
echo "=== 開始 $LABEL ($KIND: $BUILD) $(date --iso-8601=seconds) ==="

freq_header > "$W/freq.log"
sample_hw >> "$W/freq.log" 2>/dev/null &
SPID=$!
trap 'kill "$SPID" 2>/dev/null || true' EXIT
{ vmstat_header; vmstat_row before; } > "$W/vmstat.tsv"

# 段ごとの FIFO. このシェルが読み書き両方で開いておく (perf と python が片側だけで開いても止まらないように)
if [ "$KIND" != base ] && [ "$KIND" != dump ]; then
    mkfifo "$W/ctl_F1" "$W/ack_F1" "$W/ctl_U" "$W/ack_U"
    exec 20<>"$W/ctl_F1" 21<>"$W/ack_F1" 22<>"$W/ctl_U" 23<>"$W/ack_U"
fi
CF="--control=fifo:$W/ctl_F1,$W/ack_F1"
CU="--control=fifo:$W/ctl_U,$W/ack_U"
case "$KIND" in
    stat:*)
        EV="${EVENTS[${KIND#stat:}]}"
        PA=(perf stat -x, -o "$W/stat_F1.csv" -e "$EV" -D -1 "$CF" --)
        PB=(perf stat -x, -o "$W/stat_U_loop.csv" -e "$EV" -D -1 "$CU")
        ;;
    record)
        PA=(perf record -q -e cycles -F 999 -o "$W/rec_F1.data" -D -1 "$CF" --)
        PB=(perf record -q -e cycles -F 999 -o "$W/rec_U_loop.data" -D -1 "$CU")
        ;;
    *) PA=() ;;
esac

set +e
if [ "$KIND" = base ]; then
    (cd "$W" && /usr/bin/time -v "${NUMA[@]}" python3 ./animal_shogi.py > stdout.txt 2> time.txt)
    RC=$?
elif [ "$KIND" = dump ]; then
    mkdir -p "$W/blocks"
    (cd "$W" && PERF_DUMP_DIR="$W/blocks" /usr/bin/time -v "${NUMA[@]}" python3 ./animal_shogi.py \
        > stdout.txt 2> time.txt)
    RC=$?
else
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
    if [ "$RCB" -ne 0 ]; then
        echo "!!! U_loop を数える perf が exit=$RCB で終わった (止める条件). 調査用に dat/ を残して止める" >&2
        exit 1
    fi
fi
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

cp "$W/kaiseki_log/kaizenkaiseki1.txt" "${L}_main.log"
cp "$W/kaiseki_log/forward.tsv" "${L}_forward.tsv"
cp "$W/kaiseki_log/forward_summary.tsv" "${L}_forward_summary.tsv"
cp "$W/kaiseki_log/retreat_summary.tsv" "${L}_retreat_summary.tsv"
cp "$W/time.txt" "${L}_time.txt"
cp "$W/freq.log" "${L}_freq.log"
cp "$W/vmstat.tsv" "${L}_vmstat.tsv"
for s in F1 U_loop; do
    # perf stat の出力の先頭の "# started on <日時>" の行はそのまま残す (ホスト名は入らない)
    [ -f "$W/stat_$s.csv" ] && cp "$W/stat_$s.csv" "${L}_stat_$s.csv"
done
if [ "$KIND" = record ]; then
    for s in F1 U_loop; do
        # 見出し (--header) は出さない. -q で注記の行も出さない. dso は名前だけ (パスは出ない)
        perf report -i "$W/rec_$s.data" --stdio -q --no-children --sort dso,sym --percent-limit 0.2 \
            2> /dev/null > "${L}_report_$s.txt"
        perf report -i "$W/rec_$s.data" --stdio -q --no-children --sort dso --percent-limit 0.1 \
            2> /dev/null > "${L}_report_dso_$s.txt"
    done
fi
if [ "$KIND" = dump ]; then
    cp "$W/blocks/index.tsv" "${L}_blocks_index.tsv"
fi

echo "--- 巨大ページと thp_fault_fallback ---"
if ! python3 "$HERE/check.py" huge "$LABEL"; then
    echo "!!! 巨大ページが頼んだぶん付かなかった (止める条件). 調査用に dat/ を残して止める" >&2
    exit 1
fi
echo "--- オラクル 174行 ---"
if ! python3 "$ROOT/tools/verify_log.py" "$W/kaiseki_log/kaizenkaiseki1.txt"; then
    echo "!!! オラクル検証 FAIL (止める条件). 調査用に dat/ を残して止める" >&2
    exit 1
fi
echo "--- 答え ---"
set +e
python3 "$ROOT/experiments/gate_34_unmove/check_answer.py" new "$W/dat" "$REFDAT" > "${L}_answer.txt" 2>&1
RC=$?
set -e
cat "${L}_answer.txt"
if [ "$RC" -ne 0 ]; then
    echo "!!! 答えの検査が外れた (止める条件). 調査用に dat/ を残して止める" >&2
    exit 1
fi
echo "--- 件数の列を #34 本走と照合 ---"
if ! python3 "$HERE/check.py" rounds "$LABEL"; then
    echo "!!! 件数の列が #34 と違う (止める条件). 調査用に dat/ を残して止める" >&2
    exit 1
fi
echo "--- 参考: dat/ の md5 一覧の sha256 (#34 本走は 851de9569efc. 判定には使わない) ---"
echo "md5_list_sha256 $(md5_list_sha "$W/dat")" | tee "${L}_md5.txt"
rm -rf "$W/dat"
echo "=== 完了 $LABEL $(date --iso-8601=seconds) ==="
