#!/bin/bash
# 実験 perf_branch_34: 空の dat/ から完走を1本 (記録試行ではない)
#
#   run_one.sh <種類> <ラベル>
#
# 種類:
#   base   perf を付けない (段の秒の基準)
#   pebs   予測ミスの標本: br_misp_retired.all_branches_pebs:pp を周期 10,007 で (標本は分岐そのものか,
#          それと融合した直前の比較の番地に付く. probe で確かめた)
#   lbr    LBR: cycles:u を周期 2,000,003 で, -j any,u (取られた分岐の記録と外れの印. 区間から実行回数を組み立てる)
#
# F1 は起動した perf が, U_loop は python に -p で付けた perf が取る (experiments/perf_34 と同じ作り).
# 腕は build_arm.sh (impl/34_unmove ＋ perf_34 の perf_ctl.patch, .so は -g を足してビルドし, 機械語が
# #34 本走の .so と同じことを確かめる). 解析は numactl --cpunodebind=0 --membind=0 で固定し, perf は固定しない.
#
# 走る前に止める (走らせない): ノード0の 2 MiB 以上の空きが HUGEFREE_MIN_GIB (既定 16) 未満 (exit 4),
#   kernel.perf_event_paranoid が 1 でない (exit 5)
# 走ったあとは毎本その場で見て, どれかに掛かったら dat/ を残して止める:
#   - 解析が落ちた, U_loop の perf が 0 以外で終わった
#   - オラクル174行 (tools/verify_log.py)
#   - 答え (experiments/gate_34_unmove/check_answer.py new): 全探索の側のバイト一致・名前と件数・指紋
#   - forward.tsv の件数の列が results/34_unmove/forward.tsv と一致, thp_fault_fallback 0, 巨大ページ (check.py)
# 参考に dat/ の md5 一覧の sha256 を残す (#34 本走は 851de9569efc).
# perf.data は runs/ に残し, perf script を aggregate.py で数えた表だけを logs/ に写す.
# perf の分の時間を含む time.txt は, コマンド行のリポジトリの場所を <repo> に置き換えて写す.
# -j any,u は分岐の種類の指定 (配列の要素の区切りではない)
# shellcheck disable=SC2054
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$HERE/lib.sh"
KIND="${1:?種類を指定すること (base|pebs|lbr)}"
LABEL="${2:?ラベルを指定すること}"
W="$ROOT/runs/perf_branch_34/$LABEL"
REFDAT="$ROOT/runs/20261004-091929_33_hot_layout/dat"
NUMA=(numactl --cpunodebind=0 --membind=0)
HUGEFREE_MIN_GIB="${HUGEFREE_MIN_GIB:-16}"
L="$HERE/logs/$LABEL"
case "$KIND" in
    base | pebs | lbr) ;;
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
PARANOID=$(cat /proc/sys/kernel/perf_event_paranoid)
if [ "$PARANOID" != 1 ]; then
    echo "!!! kernel.perf_event_paranoid が $PARANOID (1 でない). 走らせずに止める (本人に知らせる)" >&2
    exit 5
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

if [ "$KIND" != base ]; then
    mkfifo "$W/ctl_F1" "$W/ack_F1" "$W/ctl_U" "$W/ack_U"
    exec 20<>"$W/ctl_F1" 21<>"$W/ack_F1" 22<>"$W/ctl_U" 23<>"$W/ack_U"
fi
CF="--control=fifo:$W/ctl_F1,$W/ack_F1"
CU="--control=fifo:$W/ctl_U,$W/ack_U"
case "$KIND" in
    pebs)
        EV=(-e br_misp_retired.all_branches_pebs:pp -c 10007)
        ;;
    lbr)
        EV=(-j any,u -e cycles:u -c 2000003)
        ;;
    *) EV=() ;;
esac

set +e
if [ "$KIND" = base ]; then
    (cd "$W" && /usr/bin/time -v "${NUMA[@]}" python3 ./animal_shogi.py > stdout.txt 2> time.txt)
    RC=$?
else
    (cd "$W" && PERF_CTL_F1="$W/ctl_F1" PERF_ACK_F1="$W/ack_F1" \
        PERF_CTL_U_loop="$W/ctl_U" PERF_ACK_U_loop="$W/ack_U" \
        exec /usr/bin/time -v perf record -q -o "$W/F1.data" "${EV[@]}" -D -1 "$CF" -- \
        "${NUMA[@]}" python3 ./animal_shogi.py > stdout.txt 2> time.txt) &
    TPID=$!
    # /usr/bin/time → perf → (numactl が exec した) python3 の順に親子になる. python3 が出るまで待つ
    PY=""
    for _ in $(seq 1 300); do
        PERFPID=$(pgrep -P "$TPID" -x perf | head -n1 || true)
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
    perf record -q -o "$W/U_loop.data" "${EV[@]}" -D -1 "$CU" -p "$PY" > "$W/perf_U_loop.out" 2>&1 &
    PBPID=$!
    wait "$TPID"
    RC=$?
    wait "$PBPID"
    RCB=$?
    if [ "$RCB" -ne 0 ]; then
        echo "!!! U_loop の perf が exit=$RCB で終わった (止める条件). 調査用に dat/ を残して止める" >&2
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
sed -e "s|$ROOT/|<repo>/|g" "$W/time.txt" > "${L}_time.txt"
cp "$W/freq.log" "${L}_freq.log"
cp "$W/vmstat.tsv" "${L}_vmstat.tsv"
if [ "$KIND" != base ]; then
    for s in F1 U_loop; do
        if [ "$KIND" = pebs ]; then
            perf script -i "$W/$s.data" -F ip,sym,symoff,dso 2> /dev/null \
                | python3 "$HERE/aggregate.py" pebs "$W/animal_shogi.so" > "${L}_${s}_misp.tsv"
        else
            perf script -i "$W/$s.data" -F brstacksym 2> /dev/null \
                | python3 "$HERE/aggregate.py" lbr "$W/animal_shogi.so" > "${L}_${s}_lbr.tsv"
        fi
        head -2 "${L}_${s}_"*.tsv | grep '^#' | sed "s/^/$s /"
    done
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
