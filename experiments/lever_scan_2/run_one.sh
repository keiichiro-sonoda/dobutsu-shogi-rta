#!/bin/bash
# 実験 lever_scan_2: 空の dat/ から完走を1本 (記録試行ではない)
#
#   run_one.sh <base|pf2|pf3|hugeR|reuse|all> <ラベル>
#
# 単位は完走. #22 から後退解析はファイルを読まない (全探索がメモリに残したものを P0 が詰める) ので,
# 後退解析だけを入力から回すには driver が要る. 完走でも1本3分強なので完走で揃える.
#
# 止める条件は毎本その場で見る. どれかに掛かったら dat/ を残して止める (run_all.sh も止まる).
#   ① オラクル174行 (tools/verify_log.py) と, dat/ の md5 一覧の sha256 が
#      results/22_in_memory/bytecompare.txt の #22 の値と一致すること
#   ② forward.tsv の件数の列が results/22_in_memory/forward.tsv と一致すること (stop_rule.py rounds)
#   ③ 解析が落ちないこと (終了コード 0). 落ちた本は再開しない
#   ④ 巨大ページが頼んだぶん付くこと (/proc/vmstat の thp_fault_fallback の前後差が 0)。
#      1回目の起動で, ノード0のメモリが断片化していて付かなかったので, 止めたあとに足した (README)
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$HERE/lib.sh"
ARM="${1:?腕を指定すること (base|pf2|pf3|hugeR|reuse|all)}"
LABEL="${2:?ラベルを指定すること}"
W="$ROOT/runs/exp_ls2_$LABEL"
NUMA=(numactl --cpunodebind=0 --membind=0)
BC="$HERE/logs/bytecompare.tsv"
# 基準は #22 本走の dat/ (#19〜#21 と同じ値). 手で写さず, 記録の証拠から読む
REF=$(grep -oE '#22 [0-9a-f]{64}' "$ROOT/results/22_in_memory/bytecompare.txt" | cut -d' ' -f2)
[ -n "$REF" ] || { echo "results/22_in_memory/bytecompare.txt から基準の値が読めない" >&2; exit 2; }

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

mkdir -p "$W/dat" "$W/kaiseki_log" "$HERE/logs"
BUILD=$("$HERE/make_arm.sh" "$ARM" "$W")
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
    echo "!!! 解析が落ちた (exit=$RC). 止める条件③. 再開せず, 調査用に dat/ を残して止める" >&2
    exit "$RC"
fi
# gate_stats.py の forward モードが「全探索 合計」として読む行 (要約ファイルの生値)
FT=$(awk -F'\t' '$1 == "forward_total" {print $2}' "$W/kaiseki_log/forward_summary.tsv")
echo "全探索の所要時間：$FT 秒"
grep -E "^(F1|minflt_F1|stime_F1)\s" "$W/kaiseki_log/forward_summary.tsv" | tr '\n' ' ' || true
grep -E "^(P4|loop174|retreat_total|anonhuge_loop_kB)\s" "$W/kaiseki_log/retreat_summary.tsv" \
    | tr '\n' ' ' || true
echo

cp "$W/kaiseki_log/kaizenkaiseki1.txt" "$HERE/logs/${LABEL}_main.log"
cp "$W/kaiseki_log/kaiseki_log7.txt" "$HERE/logs/${LABEL}_sub.log"
cp "$W/kaiseki_log/forward.tsv" "$HERE/logs/${LABEL}_forward.tsv"
cp "$W/kaiseki_log/forward_summary.tsv" "$HERE/logs/${LABEL}_forward_summary.tsv"
cp "$W/kaiseki_log/retreat_summary.tsv" "$HERE/logs/${LABEL}_retreat_summary.tsv"
cp "$W/time.txt" "$HERE/logs/${LABEL}_time.txt"
cp "$W/freq.log" "$HERE/logs/${LABEL}_freq.log"
cp "$W/vmstat.tsv" "$HERE/logs/${LABEL}_vmstat.tsv"

FB=$(awk -F'\t' 'NR == 1 {for (i = 1; i <= NF; i++) if ($i == "thp_fault_fallback") c = i}
                 NR == 2 {b = $c} NR == 3 {print $c - b}' "$W/vmstat.tsv")
echo "--- thp_fault_fallback の前後差: $FB ---"
if [ "$FB" != "0" ]; then
    echo "!!! 巨大ページが頼んだぶん付かなかった. 止める条件④. 調査用に dat/ を残して止める" >&2
    exit 1
fi

echo "--- オラクル 174行 ---"
if ! python3 "$ROOT/tools/verify_log.py" "$W/kaiseki_log/kaizenkaiseki1.txt"; then
    echo "!!! オラクル検証 FAIL. 止める条件①. 調査用に dat/ を残して止める" >&2
    exit 1
fi

SHA=$(md5_list_sha "$W/dat")
FILES=$(find "$W/dat" -type f | wc -l)
BYTES=$(find "$W/dat" -type f -printf '%s\n' | awk '{s+=$1} END {print s}')
if [ "$SHA" = "$REF" ]; then VS="一致"; else VS="不一致"; fi
[ -s "$BC" ] || printf 'label\tarm\tfiles\tbytes\tmd5_list_sha256\tvs_record22\n' > "$BC"
printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$LABEL" "$ARM" "$FILES" "$BYTES" "$SHA" "$VS" >> "$BC"
echo "--- dat/ のバイト比較 (#22 本走と): $FILES ファイル / $BYTES バイト / $VS ---"
if [ "$VS" = "不一致" ]; then
    echo "!!! $ARM の出力が #22 本走と違う. 止める条件①. 調査用に dat/ を残して止める" >&2
    exit 1
fi

echo "--- 件数の列を #22 本走と照合 ---"
if ! python3 "$HERE/stop_rule.py" rounds "$HERE/logs/${LABEL}_forward.tsv"; then
    echo "!!! 件数の列が #22 と違う. 止める条件②. 調査用に dat/ を残して止める" >&2
    exit 1
fi
rm -rf "$W/dat"
echo "=== 完了 $LABEL $(date --iso-8601=seconds) ==="
